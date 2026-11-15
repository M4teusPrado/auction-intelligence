"""Ficha do imóvel: dados da fonte, histórico, checklist de investigação, anexos
enviados à mão e simulação. Nada é apagado: cada mudança é uma linha nova.
Nenhuma busca na internet: os anexos vêm do navegador de quem usa a tela.
"""
import hashlib
import json
import os
import re
from datetime import datetime

from . import simulador
from .triagem import COLUNAS_IMOVEL, EntradaInvalida, NaoEncontrado, _imovel

ITENS = [  # (chave, rótulo, o que conferir)
    ("leilao", "Tipo de leilão", "Extrajudicial ou judicial, praça, data e regras de pagamento."),
    ("edital", "Edital lido", "Quem paga débitos, prazo de pagamento, condições de venda."),
    ("matricula", "Matrícula", "Proprietário, ônus, penhoras, averbações e a consolidação da propriedade."),
    ("ocupacao", "Ocupação", "Ocupado ou desocupado; por quem (ex-mutuário, inquilino)."),
    ("iptu", "Débitos de IPTU", "Valor em aberto e quem assume, segundo o edital."),
    ("condominio", "Débitos de condomínio", "Valor em aberto e quem assume, segundo o edital."),
    ("vistoria", "Localização e vistoria externa", "Rua, vizinhança, estado aparente, acesso."),
]
ITENS_CHAVES = [i[0] for i in ITENS]
STATUS = {"pendente": "Pendente", "ok": "OK", "atencao": "Atenção",
          "impeditivo": "Impeditivo", "nao_se_aplica": "Não se aplica"}
TIPOS_ANEXO = {"matricula": "Matrícula", "edital": "Edital", "laudo": "Laudo", "foto": "Foto", "outro": "Outro"}
ANEXO_MAX = 25 * 1024 * 1024
NOTA_MAX = 2000
ASSINATURAS = [(b"%PDF-", ".pdf", "application/pdf"), (b"\x89PNG\r\n\x1a\n", ".png", "image/png"),
               (b"\xff\xd8\xff", ".jpg", "image/jpeg")]


def _agora(agora=None):
    return agora or datetime.now().isoformat(timespec="seconds")


def _buscar_imovel(con, imovel_id: int) -> dict:
    r = con.execute(f"SELECT {COLUNAS_IMOVEL} FROM imoveis WHERE id=?", (imovel_id,)).fetchone()
    if r is None:
        raise NaoEncontrado(f"imóvel {imovel_id} não encontrado")
    return _imovel(r)


def _checklist(con, imovel_id: int) -> list:
    atuais = {r["item"]: r for r in con.execute(
        "SELECT item, status, nota, quando FROM investigacao WHERE id IN "
        "(SELECT MAX(id) FROM investigacao WHERE imovel_id=? GROUP BY item)", (imovel_id,))}
    return [{"item": k, "rotulo": rot, "ajuda": ajuda,
             "status": atuais[k]["status"] if k in atuais else "pendente",
             "nota": atuais[k]["nota"] if k in atuais else None,
             "quando": atuais[k]["quando"] if k in atuais else None} for k, rot, ajuda in ITENS]


def _anexos(con, imovel_id: int) -> list:
    return [dict(r) for r in con.execute(
        "SELECT id, tipo, nome_original, tamanho, quando FROM anexos WHERE imovel_id=? ORDER BY id DESC",
        (imovel_id,))]


def ficha(con, imovel_id: int) -> dict:
    im = _buscar_imovel(con, imovel_id)
    historico = [dict(r) for r in con.execute(
        "SELECT h.quando, h.evento, h.campo, h.valor_antigo, h.valor_novo FROM historico h "
        "WHERE h.imovel_id=? ORDER BY h.id", (imovel_id,))]
    triagens = [dict(r) for r in con.execute(
        "SELECT id, de, para, nota, quando FROM triagens WHERE imovel_id=? ORDER BY id", (imovel_id,))]
    salva = con.execute("SELECT premissas, quando FROM simulacoes WHERE imovel_id=? ORDER BY id DESC LIMIT 1",
                        (imovel_id,)).fetchone()
    return {"imovel": im, "historico": historico, "triagens": triagens,
            "investigacao": _checklist(con, imovel_id), "status": STATUS,
            "anexos": _anexos(con, imovel_id), "tipos_anexo": TIPOS_ANEXO,
            "premissas": simulador.descricao_premissas(),
            "premissas_padrao": simulador.padrao_para(im),
            "simulacao_salva": {"premissas": json.loads(salva["premissas"]), "quando": salva["quando"]} if salva else None}


def investigar(con, imovel_id: int, corpo, agora: str = None) -> dict:
    if not isinstance(corpo, dict) or set(corpo) - {"item", "status", "nota"}:
        raise EntradaInvalida("envie {item, status, nota}")
    _buscar_imovel(con, imovel_id)
    item, status, nota = corpo.get("item"), corpo.get("status"), corpo.get("nota")
    if item not in ITENS_CHAVES:
        raise EntradaInvalida("item inválido: use " + ", ".join(ITENS_CHAVES))
    if status not in STATUS:
        raise EntradaInvalida("status inválido: use " + ", ".join(STATUS))
    if nota is not None:
        if not isinstance(nota, str):
            raise EntradaInvalida("'nota' deve ser texto")
        nota = nota.strip()
        if len(nota) > NOTA_MAX:
            raise EntradaInvalida(f"nota muito longa (máximo {NOTA_MAX} caracteres)")
        nota = nota or None
    con.execute("INSERT INTO investigacao (imovel_id, item, status, nota, quando) VALUES (?,?,?,?,?)",
                (imovel_id, item, status, nota, _agora(agora)))
    con.commit()
    return {"investigacao": _checklist(con, imovel_id)}


def anexar(con, pasta: str, imovel_id: int, tipo: str, nome: str, dados: bytes, agora: str = None) -> dict:
    _buscar_imovel(con, imovel_id)
    if tipo not in TIPOS_ANEXO:
        raise EntradaInvalida("tipo de anexo inválido: use " + ", ".join(TIPOS_ANEXO))
    if not dados:
        raise EntradaInvalida("arquivo vazio")
    if len(dados) > ANEXO_MAX:
        raise EntradaInvalida("arquivo maior que 25 MB")
    ext = next((e for assinatura, e, _ in ASSINATURAS if dados.startswith(assinatura)), None)
    if ext is None:
        raise EntradaInvalida("formato não aceito: envie PDF, PNG ou JPG")
    nome = re.sub(r"[\x00-\x1f]", "", os.path.basename((nome or "").replace("\\", "/"))).strip()[:150] or f"anexo{ext}"
    sha = hashlib.sha256(dados).hexdigest()
    igual = con.execute("SELECT id FROM anexos WHERE imovel_id=? AND sha256=?", (imovel_id, sha)).fetchone()
    if igual:
        return {"anexos": _anexos(con, imovel_id), "duplicado": True}
    relativo = os.path.join(str(imovel_id), sha[:24] + ext)       # nome no disco nunca vem do usuário
    destino = os.path.join(pasta, relativo)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    with open(destino, "wb") as f:
        f.write(dados)
    con.execute("INSERT INTO anexos (imovel_id, tipo, nome_original, arquivo, tamanho, sha256, quando) "
                "VALUES (?,?,?,?,?,?,?)", (imovel_id, tipo, nome, relativo, len(dados), sha, _agora(agora)))
    con.commit()
    return {"anexos": _anexos(con, imovel_id), "duplicado": False}


def arquivo_anexo(con, pasta: str, anexo_id: int):
    """Devolve (caminho no disco, nome original, tipo MIME)."""
    r = con.execute("SELECT arquivo, nome_original FROM anexos WHERE id=?", (anexo_id,)).fetchone()
    if r is None:
        raise NaoEncontrado("anexo não encontrado")
    caminho = os.path.realpath(os.path.join(pasta, r["arquivo"]))
    if not caminho.startswith(os.path.realpath(pasta) + os.sep) or not os.path.isfile(caminho):
        raise NaoEncontrado("arquivo do anexo não está na pasta de anexos")
    mime = next(m for _, e, m in ASSINATURAS if caminho.endswith(e))
    return caminho, r["nome_original"], mime


def simular(corpo) -> dict:
    if not isinstance(corpo, dict) or set(corpo) != {"premissas"}:
        raise EntradaInvalida("envie {premissas: {...}}")
    try:
        return simulador.simular(corpo["premissas"])
    except simulador.PremissaInvalida as e:
        raise EntradaInvalida(str(e))


def salvar_simulacao(con, imovel_id: int, corpo, agora: str = None) -> dict:
    _buscar_imovel(con, imovel_id)
    r = simular(corpo)
    quando = _agora(agora)
    con.execute("INSERT INTO simulacoes (imovel_id, premissas, resultado, quando) VALUES (?,?,?,?)",
                (imovel_id, json.dumps(r["premissas"]), json.dumps(r, ensure_ascii=False), quando))
    con.commit()
    return {"resultado": r, "quando": quando}
