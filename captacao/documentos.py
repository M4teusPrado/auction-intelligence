"""Leitura dos PDFs anexados (matrícula, edital...) e busca de trechos por regra fixa.

Não há IA aqui: o texto é extraído com pypdf e procurado por uma lista de termos.
O resultado são TRECHOS para alguém ler, nunca uma conclusão. Encontrar "penhora"
não quer dizer que a penhora está ativa (pode ter sido cancelada depois); não
encontrar nada não quer dizer que o documento está limpo (PDF escaneado não tem texto).

pypdf é opcional: sem ele a ficha funciona e só avisa que a leitura está desligada.
"""
import io
import re
import unicodedata
from typing import List

try:
    import pypdf
except ImportError:              # leitura de PDF desligada
    pypdf = None

PAGINAS_MAX = 200
TRECHO = 110                     # caracteres antes e depois do termo
POR_TERMO_MAX = 4                # trechos por termo e documento

# (item da investigação, rótulo mostrado, termos). Termos sem acento e minúsculos;
# o texto do PDF é normalizado do mesmo jeito antes da busca.
REGRAS = [
    ("matricula", "Penhora, arresto ou sequestro", ["penhora", "arresto", "sequestro"]),
    ("matricula", "Indisponibilidade", ["indisponibilidade", "indisponivel"]),
    ("matricula", "Hipoteca", ["hipoteca"]),
    ("matricula", "Usufruto", ["usufruto"]),
    ("matricula", "Ação, execução ou citação", ["citacao", "execucao", "acao judicial", "ajuizada", "processo"]),
    ("matricula", "Arrolamento ou servidão", ["arrolamento", "servidao"]),
    ("matricula", "Foro ou laudêmio", ["enfiteuse", "foreiro", "laudemio", "aforamento"]),
    ("matricula", "Consolidação da propriedade", ["consolidacao da propriedade", "consolidada a propriedade"]),
    ("matricula", "Cancelamento (pode anular um ônus acima)", ["cancelamento", "cancelada", "cancelado"]),
    ("leilao", "Alienação fiduciária / Lei 9.514", ["alienacao fiduciaria", "9.514", "9514"]),
    ("leilao", "Datas e praças do leilão", ["primeiro leilao", "segundo leilao", "1o leilao", "2o leilao", "praca"]),
    ("edital", "Forma de pagamento", ["a vista", "financiamento", "fgts", "parcelamento", "sinal"]),
    ("edital", "Comissão do leiloeiro", ["comissao do leiloeiro", "comissao de leiloeiro", "5% (cinco"]),
    ("edital", "Prazos", ["prazo de", "dias uteis", "dias corridos"]),
    ("ocupacao", "Ocupação e desocupação", ["ocupado", "desocupado", "desocupacao", "imissao na posse", "reintegracao de posse", "ocupante"]),
    ("iptu", "IPTU e tributos", ["iptu", "tributos", "impostos"]),
    ("condominio", "Condomínio", ["condominio", "condominiais"]),
    ("edital", "Débitos por conta do comprador", ["por conta do adquirente", "por conta do arrematante", "por conta do comprador",
                                                 "responsabilidade do adquirente", "responsabilidade do arrematante",
                                                 "responsabilidade do comprador"]),
]


class LeituraIndisponivel(RuntimeError):
    pass


def leitura_ligada() -> bool:
    return pypdf is not None


def extrair_paginas(dados: bytes) -> List[str]:
    """Texto de cada página. Lista de textos vazios = PDF sem texto (provável imagem escaneada)."""
    if pypdf is None:
        raise LeituraIndisponivel("pypdf não instalado")
    leitor = pypdf.PdfReader(io.BytesIO(dados))
    paginas = []
    for i, pagina in enumerate(leitor.pages):
        if i >= PAGINAS_MAX:
            break
        try:
            paginas.append(pagina.extract_text() or "")
        except Exception:        # página com problema não derruba o documento
            paginas.append("")
    return paginas


def _normalizar_mesmo_tamanho(texto: str) -> str:
    """Minúsculo e sem acento, caractere por caractere, para as posições baterem com o original."""
    return "".join((unicodedata.normalize("NFKD", c)[:1] or c).lower() for c in texto)


def _limpar(t: str) -> str:
    return re.sub(r"\s+", " ", t)


def buscar(paginas: List[str]) -> List[dict]:
    """Trechos encontrados: item, rótulo, termo, página (1 = primeira), antes, achado, depois."""
    achados = []
    for n, texto in enumerate(paginas, start=1):
        if not texto.strip():
            continue
        norm = _normalizar_mesmo_tamanho(texto)
        for item, rotulo, termos in REGRAS:
            for termo in termos:
                padrao = re.compile(r"(?<![a-z0-9])" + re.escape(termo) + r"(?![a-z0-9])")
                for k, m in enumerate(padrao.finditer(norm)):
                    if k >= POR_TERMO_MAX:
                        break
                    a, b = m.start(), m.end()
                    achados.append({"item": item, "rotulo": rotulo, "termo": termo, "pagina": n,
                                    "antes": _limpar(texto[max(0, a - TRECHO):a]).lstrip(),
                                    "achado": _limpar(texto[a:b]),
                                    "depois": _limpar(texto[b:b + TRECHO]).rstrip()})
    return achados

