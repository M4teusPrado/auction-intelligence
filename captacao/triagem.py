"""Funções da tela de triagem, sem servidor: recebem a conexão e parâmetros já
lidos (dicionário de listas, como devolve urllib.parse.parse_qs) e devolvem dicts
prontos para virar JSON. Toda entrada é validada; o SQL é sempre parametrizado.
"""
import math
from datetime import datetime
from typing import Dict, List, Optional

from .classifica import CATEGORIAS
from .normaliza import chave
from .repositorio import ESTAGIOS

POR_PAGINA = 50
CATEGORIAS_VALIDAS = sorted(set(CATEGORIAS.values()) | {"outros"})
ORDENS = {   # nulos sempre no fim; id desempata para a paginação ser estável
    "desconto": "desconto_pct IS NULL, desconto_pct DESC, id",
    "preco": "preco IS NULL, preco ASC, id",
    "area_terreno": "area_terreno IS NULL, area_terreno DESC, id",
    "recente": "primeira_vez DESC, id DESC",
}
PARAMS_LISTA = {"estagio", "modalidade", "categoria", "cidade", "preco_min", "preco_max",
                "desconto_min", "area_terreno_min", "sem_alertas", "ordem", "pagina"}
MULTIPLOS = {"modalidade", "categoria"}
NOTA_MAX = 1000

COLUNAS_IMOVEL = """
  id, fonte, id_fonte, uf, cidade, bairro, endereco, preco, valor_avaliacao, desconto_pct,
  modalidade, tipo, categoria, area_privativa, area_terreno, area_total, link, data_fonte,
  alertas, situacao, estagio, primeira_vez, ultima_vez,
  (SELECT nota FROM triagens t WHERE t.imovel_id = imoveis.id ORDER BY t.id DESC LIMIT 1) AS nota
"""


class EntradaInvalida(ValueError):
    """Parâmetro ou corpo inválido (HTTP 400)."""


class NaoEncontrado(LookupError):
    """Imóvel inexistente (HTTP 404)."""


def _preparar(con) -> None:
    con.create_function("chave", 1, chave, deterministic=True)


def _imovel(r) -> dict:
    d = dict(r)
    d["alertas"] = [a for a in (d.get("alertas") or "").split(",") if a]
    return d


# ---------- validação ----------

def _um(params: Dict[str, List[str]], nome: str) -> Optional[str]:
    vals = params.get(nome) or []
    if len(vals) > 1:
        raise EntradaInvalida(f"'{nome}' aceita um só valor")
    v = vals[0].strip() if vals else ""
    return v or None


def _numero(params, nome: str) -> Optional[float]:
    v = _um(params, nome)
    if v is None:
        return None
    try:
        n = float(v.replace(",", "."))
    except ValueError:
        raise EntradaInvalida(f"'{nome}' deve ser um número")
    if not math.isfinite(n) or n < 0 or n > 1e10:
        raise EntradaInvalida(f"'{nome}' fora do intervalo aceito")
    return n


def _booleano(params, nome: str) -> bool:
    v = _um(params, nome)
    if v is None or v.lower() in ("0", "false", "nao", "não"):
        return False
    if v.lower() in ("1", "true", "sim"):
        return True
    raise EntradaInvalida(f"'{nome}' deve ser 1 ou 0")


def _texto(valor: str, nome: str, maximo: int) -> str:
    if len(valor) > maximo:
        raise EntradaInvalida(f"'{nome}' muito longo (máximo {maximo} caracteres)")
    return valor


# ---------- leitura ----------

def listar(con, params: Dict[str, List[str]]) -> dict:
    desconhecidos = set(params) - PARAMS_LISTA
    if desconhecidos:
        raise EntradaInvalida("parâmetro desconhecido: " + ", ".join(sorted(desconhecidos)))
    for nome in set(params) - MULTIPLOS:
        _um(params, nome)                     # rejeita repetição em parâmetro simples

    where, args = ["situacao = 'ativo'"], []
    estagio = _um(params, "estagio")
    if estagio is not None:
        if estagio not in ESTAGIOS:
            raise EntradaInvalida("estágio inválido: use " + ", ".join(ESTAGIOS))
        where.append("estagio = ?"); args.append(estagio)

    modalidades = [_texto(m.strip(), "modalidade", 120) for m in params.get("modalidade", []) if m.strip()]
    if len(modalidades) > 30:
        raise EntradaInvalida("modalidades demais")
    if modalidades:
        where.append(f"modalidade IN ({','.join('?' * len(modalidades))})"); args += modalidades

    categorias = [c.strip().lower() for c in params.get("categoria", []) if c.strip()]
    for c in categorias:
        if c not in CATEGORIAS_VALIDAS:
            raise EntradaInvalida("categoria inválida: use " + ", ".join(CATEGORIAS_VALIDAS))
    if categorias:
        where.append(f"categoria IN ({','.join('?' * len(categorias))})"); args += categorias

    cidade = _um(params, "cidade")
    if cidade is not None and chave(_texto(cidade, "cidade", 80)):
        where.append("chave(cidade) LIKE ?"); args.append(f"%{chave(cidade)}%")

    for nome, expr in (("preco_min", "preco >= ?"), ("preco_max", "preco <= ?"),
                       ("desconto_min", "desconto_pct >= ?"),
                       ("area_terreno_min", "area_terreno >= ?")):
        n = _numero(params, nome)
        if n is not None:
            where.append(expr); args.append(n)

    if _booleano(params, "sem_alertas"):
        where.append("COALESCE(alertas, '') = ''")

    ordem = _um(params, "ordem") or "desconto"
    if ordem not in ORDENS:
        raise EntradaInvalida("ordem inválida: use " + ", ".join(ORDENS))

    pagina_txt = _um(params, "pagina") or "1"
    if not pagina_txt.isdigit() or not 1 <= int(pagina_txt) <= 100000:
        raise EntradaInvalida("'pagina' deve ser um inteiro a partir de 1")
    pagina = int(pagina_txt)

    _preparar(con)
    cond = " AND ".join(where)
    total = con.execute(f"SELECT COUNT(*) FROM imoveis WHERE {cond}", args).fetchone()[0]
    linhas = con.execute(
        f"SELECT {COLUNAS_IMOVEL} FROM imoveis WHERE {cond} ORDER BY {ORDENS[ordem]} "
        "LIMIT ? OFFSET ?", args + [POR_PAGINA, (pagina - 1) * POR_PAGINA]).fetchall()
    return {"total": total, "pagina": pagina, "por_pagina": POR_PAGINA,
            "paginas": max(1, math.ceil(total / POR_PAGINA)), "ordem": ordem,
            "itens": [_imovel(r) for r in linhas]}


def resumo(con) -> dict:
    por_estagio = {e: 0 for e in ESTAGIOS}
    for e, n in con.execute("SELECT estagio, COUNT(*) FROM imoveis WHERE situacao='ativo' "
                            "GROUP BY estagio"):
        por_estagio[e] = n
    ult = con.execute("SELECT * FROM coletas ORDER BY id DESC LIMIT 1").fetchone()
    coleta = None
    if ult:
        quedas = con.execute(
            "SELECT COUNT(*) FROM historico WHERE coleta_id=? AND evento='alterado' "
            "AND campo='preco' AND CAST(valor_novo AS REAL) < CAST(valor_antigo AS REAL)",
            (ult["id"],)).fetchone()[0]
        data_fonte = con.execute(
            "SELECT data_fonte FROM imoveis WHERE fonte=? AND uf=? ORDER BY ultima_vez DESC LIMIT 1",
            (ult["fonte"], ult["recorte"])).fetchone()
        coleta = {"id": ult["id"], "quando": ult["quando"], "fonte": ult["fonte"],
                  "recorte": ult["recorte"], "data_fonte": data_fonte[0] if data_fonte else None,
                  "total": ult["total"], "novos": ult["novos"], "quedas_preco": quedas,
                  "saidos": ult["saidos"]}
    return {"total_ativo": sum(por_estagio.values()), "por_estagio": por_estagio,
            "ultima_coleta": coleta}


def opcoes(con) -> dict:
    def contar(coluna, ordem):
        return [{"valor": v, "n": n} for v, n in con.execute(
            f"SELECT {coluna}, COUNT(*) FROM imoveis WHERE situacao='ativo' AND {coluna} IS NOT NULL "
            f"AND {coluna} <> '' GROUP BY {coluna} ORDER BY {ordem}")]
    return {"modalidades": contar("modalidade", "2 DESC, 1"),
            "categorias": contar("categoria", "2 DESC, 1"),
            "cidades": contar("cidade", "1"),
            "estagios": list(ESTAGIOS), "ordens": list(ORDENS)}


# ---------- escrita ----------

def triar(con, imovel_id: int, corpo, agora: str = None) -> dict:
    """Muda o estágio e registra em triagens. {"desfazer": true} volta ao estágio
    anterior à última triagem, com uma linha nova (nada é apagado)."""
    if not isinstance(corpo, dict):
        raise EntradaInvalida("o corpo deve ser um objeto JSON")
    extras = set(corpo) - {"para", "nota", "desfazer"}
    if extras:
        raise EntradaInvalida("campo desconhecido: " + ", ".join(sorted(extras)))
    atual = con.execute("SELECT estagio FROM imoveis WHERE id=?", (imovel_id,)).fetchone()
    if atual is None:
        raise NaoEncontrado(f"imóvel {imovel_id} não encontrado")

    if corpo.get("desfazer") is not None:
        if corpo["desfazer"] is not True or "para" in corpo or "nota" in corpo:
            raise EntradaInvalida("desfazer: envie só {\"desfazer\": true}")
        ultima = con.execute("SELECT id, de, para FROM triagens WHERE imovel_id=? "
                             "ORDER BY id DESC LIMIT 1", (imovel_id,)).fetchone()
        if ultima is None:
            raise EntradaInvalida("não há triagem para desfazer")
        if ultima["para"] != atual["estagio"]:
            raise EntradaInvalida("o estágio mudou desde a última triagem; recarregue a lista")
        para, nota = ultima["de"], None
    else:
        para = corpo.get("para")
        if para not in ESTAGIOS:
            raise EntradaInvalida("'para' deve ser um de: " + ", ".join(ESTAGIOS))
        if para == atual["estagio"]:
            raise EntradaInvalida(f"o imóvel já está em '{para}'")
        nota = corpo.get("nota")
        if nota is not None:
            if not isinstance(nota, str):
                raise EntradaInvalida("'nota' deve ser texto")
            nota = _texto(nota.strip(), "nota", NOTA_MAX) or None

    agora = agora or datetime.now().isoformat(timespec="seconds")
    cur = con.execute("INSERT INTO triagens (imovel_id, de, para, nota, quando) VALUES (?,?,?,?,?)",
                      (imovel_id, atual["estagio"], para, nota, agora))
    con.execute("UPDATE imoveis SET estagio=? WHERE id=?", (para, imovel_id))
    con.commit()
    im = _imovel(con.execute(f"SELECT {COLUNAS_IMOVEL} FROM imoveis WHERE id=?",
                             (imovel_id,)).fetchone())
    im["triagem"] = {"id": cur.lastrowid, "de": atual["estagio"], "para": para}
    return im
