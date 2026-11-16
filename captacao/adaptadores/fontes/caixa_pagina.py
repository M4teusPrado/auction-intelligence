"""Leitura da página de um imóvel no site da Caixa, capturada pela extensão do navegador.

O sistema não acessa o site da Caixa (ele bloqueia robôs). Quem abre a página é a pessoa, no
navegador dela; a extensão (extensao-chrome/) envia o texto da página e os PDFs que a página
oferece (matrícula, edital). Este módulo só interpreta o texto recebido.

Formato de referência: tests/amostras/caixa_pagina_sorocaba.txt (página real, nov/2026).
"""
import re
from datetime import datetime
from typing import Optional, Tuple

from ...aplicacao.portas import ErroDeFonte
from ...dominio.modelo import DadosLeilao, ImovelCaptado, Praca
from ...dominio.normaliza import chave, numero_br, sem_acento
from .caixa import FONTE

ESTADOS = {"acre": "AC", "alagoas": "AL", "amapa": "AP", "amazonas": "AM", "bahia": "BA", "ceara": "CE",
           "distrito federal": "DF", "espirito santo": "ES", "goias": "GO", "maranhao": "MA", "mato grosso": "MT",
           "mato grosso do sul": "MS", "minas gerais": "MG", "para": "PA", "paraiba": "PB", "parana": "PR",
           "pernambuco": "PE", "piaui": "PI", "rio de janeiro": "RJ", "rio grande do norte": "RN",
           "rio grande do sul": "RS", "rondonia": "RO", "roraima": "RR", "santa catarina": "SC", "sao paulo": "SP",
           "sergipe": "SE", "tocantins": "TO"}


def _campo(texto: str, rotulo: str) -> str:
    m = re.search(r"^\s*" + rotulo + r"\s*:\s*(.+?)\s*$", texto, re.I | re.M)
    return m.group(1).strip() if m else ""


def _dinheiro(t: str) -> Optional[float]:
    m = re.search(r"R\$\s*([\d.]+,\d{2})", t or "")
    return numero_br(m.group(1)) if m else None


def numero_do_imovel(texto: str, url: str = "") -> str:
    """'878771554845-3' -> '8787715548453' (mesmo identificador da lista CSV)."""
    m = re.search(r"N[úu]mero do im[óo]vel\s*:\s*([\d.\-]+)", texto, re.I) or re.search(r"hdnimovel=(\d+)", url or "", re.I)
    return re.sub(r"\D", "", m.group(1)) if m else ""


def regras_de_despesas(texto: str) -> dict:
    """Quem paga condomínio e tributos, segundo a página (texto da Caixa, sem interpretação)."""
    return {"condominio": _campo(texto, "Condom[íi]nio"), "tributos": _campo(texto, "Tributos")}


def interpretar_pagina(texto: str, url: str = "", hoje: Optional[str] = None) -> Tuple[ImovelCaptado, dict]:
    """(imóvel no formato comum, extras: regras de despesas e formas de pagamento). Formato estranho: ErroDeFonte."""
    numero = numero_do_imovel(texto, url)
    if not numero:
        raise ErroDeFonte("a página não traz o número do imóvel da Caixa (é a página de detalhe de um imóvel?)")
    m_end = re.search(r"Endere[çc]o\s*:\s*\n?\s*(.+)", texto, re.I)
    endereco_completo = m_end.group(1).strip() if m_end else ""
    m_local = re.search(r",\s*([^,]+?)\s*-\s*([A-Za-zÀ-ú ]+)\s*$", endereco_completo)
    cidade = sem_acento(m_local.group(1)).upper() if m_local else ""
    uf = ESTADOS.get(chave(m_local.group(2)), "") if m_local else ""
    if not uf:
        m_com = re.search(r"Comarca\s*:\s*([^\n]+?)-([A-Z]{2})\b", texto)
        uf = m_com.group(2) if m_com else ""
        cidade = cidade or (sem_acento(m_com.group(1)).upper() if m_com else "")
    endereco = re.split(r",\s*[^,]*-\s*CEP", endereco_completo)[0].strip() if endereco_completo else ""
    bairro_m = re.search(r",\s*([^,]+?)\s*-\s*CEP", endereco_completo)
    pracas = []
    for n in (1, 2):
        data = re.search(rf"Data do {n}º Leil[ãa]o\s*-\s*(\d{{2}})/(\d{{2}})/(\d{{4}})\s*-\s*(\d{{1,2}})h(\d{{2}})", texto, re.I)
        valor = _dinheiro(_campo(texto, rf"Valor m[íi]nimo de venda {n}º Leil[ãa]o"))
        if data or valor:
            d = f"{data.group(3)}-{data.group(2)}-{data.group(1)}T{int(data.group(4)):02d}:{data.group(5)}" if data else None
            pracas.append(Praca(numero=n, data=d, valor=valor))
    preco = _dinheiro(_campo(texto, "Valor m[íi]nimo de venda")) or (pracas[0].valor if pracas else None)
    avaliacao = _dinheiro(_campo(texto, "Valor de avalia[çc][ãa]o"))
    linhas = [l.strip() for l in texto.splitlines() if l.strip()]
    modalidade = next((l for l in linhas if re.fullmatch(r"(Leil[ãa]o SFI.*|Licita[çc][ãa]o Aberta.*|Venda Direta.*|Venda Online.*|Leil[ãa]o.*)", l)
                       and len(l) < 60), "")
    comarca, oficio = _campo(texto, "Comarca"), _campo(texto, "Of[íi]cio")
    area = lambda nome: numero_br((re.search(r"[ÁA]rea " + nome + r"\s*=\s*([\d.,]+)", texto, re.I) or [None, ""])[1])
    tipo = chave(_campo(texto, "Tipo de im[óo]vel")) or "imovel"
    descricao = re.search(r"Descri[çc][ãa]o\s*:\s*\n?(.+?)(?:\n\s*\n|$)", texto, re.I | re.S)
    lei = DadosLeilao(tipo_venda="Leilão SFI" if "sfi" in chave(modalidade) else modalidade,
                      leilao=_campo(texto, "Edital"), lote=_campo(texto, "N[úu]mero do item"),
                      comitente="Caixa Econômica Federal", leiloeiro=_campo(texto, r"Leiloeiro\(a\)") or _campo(texto, "Leiloeiro"),
                      matricula=_campo(texto, r"Matr[íi]cula\(s\)") or _campo(texto, "Matr[íi]cula"),
                      cartorio=f"{oficio}º Ofício de {comarca}" if comarca and oficio else comarca,
                      pracas=pracas)
    im = ImovelCaptado(
        fonte=FONTE, id_fonte=numero, uf=uf, cidade=cidade, bairro=bairro_m.group(1).strip() if bairro_m else "",
        endereco=endereco, preco=preco, valor_avaliacao=avaliacao,
        desconto_pct=round((1 - preco / avaliacao) * 100, 2) if preco and avaliacao and preco <= avaliacao else None,
        modalidade=modalidade or "Caixa", tipo=tipo, area_privativa=area("privativa"), area_terreno=area("do terreno"),
        area_total=area("total"), descricao=(descricao.group(1).strip() if descricao else "")[:4000],
        link=url or f"https://venda-imoveis.caixa.gov.br/sistema/detalhe-imovel.asp?hdnimovel={numero}",
        data_fonte=hoje or datetime.now().strftime("%d/%m/%Y"), leilao=lei)
    formas = re.search(r"FORMAS DE PAGAMENTO ACEITAS\s*:?\s*\n(.+?)(?:\n\s*\n|$)", texto, re.I | re.S)
    extras = {"despesas": regras_de_despesas(texto),
              "pagamento": [l.strip() for l in formas.group(1).splitlines() if l.strip()] if formas else []}
    return im, extras
