"""Fonte: lista pública de imóveis da Caixa, um CSV por estado.

O formato do arquivo pode mudar. Por isso o cabeçalho é localizado pelo nome das
colunas, e uma coluna obrigatória ausente gera erro claro em vez de dado errado.
"""
import csv
import io
import re
import urllib.request
from typing import List, Tuple

from ..modelo import ImovelCaptado
from ..normaliza import chave, numero_br

FONTE = "caixa"
URL = "https://venda-imoveis.caixa.gov.br/listaweb/Lista_imoveis_{uf}.csv"

# nome interno -> trechos que identificam a coluna no cabeçalho (já normalizado)
COLUNAS = {
    "id_fonte": ["n do imovel", "numero do imovel"],
    "uf": ["uf"],
    "cidade": ["cidade"],
    "bairro": ["bairro"],
    "endereco": ["endereco"],
    "preco": ["preco"],
    "valor_avaliacao": ["valor de avaliacao"],
    "desconto_pct": ["desconto"],
    "descricao": ["descricao"],
    "modalidade": ["modalidade de venda", "modalidade"],
    "link": ["link de acesso", "link"],
}
OBRIGATORIAS = ("id_fonte", "uf", "cidade", "endereco", "preco")


class FormatoInesperado(Exception):
    pass


def baixar(uf: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(URL.format(uf=uf.upper()),
                                 headers={"User-Agent": "Mozilla/5.0 (captacao-imoveis)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        dados = resp.read()
    if dados.lstrip()[:1] == b"<":
        raise FormatoInesperado(
            "A Caixa devolveu uma página em vez do CSV (provável bloqueio de acesso automático). "
            "Baixe o arquivo pelo navegador e use --arquivo.")
    return dados


def decodificar(dados: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return dados.decode(enc)
        except UnicodeDecodeError:
            continue
    raise FormatoInesperado("Não foi possível ler a codificação do arquivo.")


def _mapear_cabecalho(celulas: List[str]) -> dict:
    norm = [chave(c) for c in celulas]
    mapa = {}
    for campo, trechos in COLUNAS.items():
        for i, c in enumerate(norm):
            if any(c == t or c.startswith(t) for t in trechos) and i not in mapa.values():
                mapa[campo] = i
                break
    return mapa


def tipo_e_areas(descricao: str) -> Tuple[str, float, float, float]:
    """Devolve (tipo, área privativa, área do terreno, área total) a partir da descrição."""
    tipo = chave(descricao.split(",")[0]) if descricao else ""
    def area(rotulo):
        m = re.search(r"([\d.,]+)\s*de\s*[áa]rea\s*" + rotulo, descricao or "", re.I)
        v = numero_br(m.group(1)) if m else None
        return v if v else None          # 0.00 na fonte significa "não informado"
    return tipo, area("privativa"), area("do terreno"), area("total")


def interpretar(texto: str) -> Tuple[List[ImovelCaptado], List[str]]:
    """Devolve (imóveis, avisos). Linhas com problema viram aviso, não imóvel."""
    linhas = list(csv.reader(io.StringIO(texto), delimiter=";"))
    data_fonte, mapa, inicio = "", None, 0
    for i, linha in enumerate(linhas[:15]):
        junto = " ".join(linha)
        m = re.search(r"(\d{2}/\d{2}/\d{4})", junto)
        if m and not data_fonte:
            data_fonte = m.group(1)
        candidato = _mapear_cabecalho(linha)
        if all(c in candidato for c in OBRIGATORIAS):
            mapa, inicio = candidato, i + 1
            break
    if mapa is None:
        raise FormatoInesperado(
            "Cabeçalho não encontrado. Colunas obrigatórias: " + ", ".join(OBRIGATORIAS))

    imoveis, avisos = [], []
    for n, linha in enumerate(linhas[inicio:], start=inicio + 1):
        if not any(c.strip() for c in linha):
            continue
        def col(campo):
            i = mapa.get(campo)
            return linha[i].strip() if i is not None and i < len(linha) else ""
        id_fonte = re.sub(r"\D", "", col("id_fonte"))
        if not id_fonte:
            avisos.append(f"linha {n}: sem número do imóvel, ignorada")
            continue
        preco = numero_br(col("preco"))
        if preco is None:
            avisos.append(f"linha {n}: imóvel {id_fonte} sem preço legível")
        tipo, a_priv, a_terr, a_total = tipo_e_areas(col("descricao"))
        imoveis.append(ImovelCaptado(
            fonte=FONTE, id_fonte=id_fonte, uf=col("uf").upper(), cidade=col("cidade"),
            bairro=col("bairro"), endereco=col("endereco"), preco=preco,
            valor_avaliacao=numero_br(col("valor_avaliacao")),
            desconto_pct=numero_br(col("desconto_pct")), modalidade=col("modalidade"),
            tipo=tipo, area_privativa=a_priv, area_terreno=a_terr,
            area_total=a_total,
            descricao=col("descricao"), link=col("link"), data_fonte=data_fonte))
    return imoveis, avisos
