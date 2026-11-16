"""Parecer preliminar da investigação: formato, proteção de dados e conferência das citações.

Regras (combinadas com o Mateus):
- a IA só SUGERE a situação de cada item; quem marca é a pessoa;
- toda afirmação vem com documento, página e trecho copiado do texto;
- o trecho é conferido aqui, por regra fixa: se não estiver no documento, a afirmação
  aparece como "não confirmada";
- CPF e RG são mascarados antes de qualquer envio para fora.
"""
import re
import unicodedata
from typing import Dict, List

from .analise import ITENS_CHAVES

SITUACOES = ("ok", "atencao", "impeditivo", "sem_informacao")
NIVEIS_RISCO = ("alto", "medio", "baixo")

_CITACAO = {
    "type": "object",
    "properties": {
        "afirmacao": {"type": "string", "description": "o fato, em uma frase curta"},
        "documento": {"type": "string", "description": "código do documento, ex.: DESCRICAO ou A12"},
        "pagina": {"type": "integer"},
        "trecho": {"type": "string", "description": "cópia literal do texto do documento, até 300 caracteres"},
    },
    "required": ["afirmacao", "documento", "pagina", "trecho"],
    "additionalProperties": False,
}

# Contrato da porta AnalisadorDeDocumentos (também usado como formato de saída estruturada).
ESQUEMA_PARECER = {
    "type": "object",
    "properties": {
        "resumo_geral": {"type": "string"},
        "itens": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item": {"type": "string", "enum": list(ITENS_CHAVES)},
                    "situacao_sugerida": {"type": "string", "enum": list(SITUACOES)},
                    "resumo": {"type": "string"},
                    "fatos": {"type": "array", "items": _CITACAO},
                },
                "required": ["item", "situacao_sugerida", "resumo", "fatos"],
                "additionalProperties": False,
            },
        },
        "riscos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "titulo": {"type": "string"},
                    "nivel": {"type": "string", "enum": list(NIVEIS_RISCO)},
                    "explicacao": {"type": "string"},
                    "citacoes": {"type": "array", "items": _CITACAO},
                },
                "required": ["titulo", "nivel", "explicacao", "citacoes"],
                "additionalProperties": False,
            },
        },
        "perguntas": {"type": "array", "items": {"type": "string"},
                      "description": "o que os documentos não respondem e precisa ser apurado"},
    },
    "required": ["resumo_geral", "itens", "riscos", "perguntas"],
    "additionalProperties": False,
}


# Regras gerais de um edital que vale para muitos imóveis (lido uma vez, reaproveitado).
TEMAS_EDITAL = ("condominio", "iptu", "desocupacao", "estado_do_imovel", "venda_ad_corpus", "onus_e_acoes",
                "comissao", "pagamento", "fgts_financiamento", "prazos", "direito_de_preferencia",
                "desistencia_e_penalidades", "outros")
ESQUEMA_REGRAS_EDITAL = {
    "type": "object",
    "properties": {
        "regras": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tema": {"type": "string", "enum": list(TEMAS_EDITAL)},
                    "regra": {"type": "string", "description": "o que o edital determina, em uma ou duas frases"},
                    "citacoes": {"type": "array", "items": _CITACAO},
                },
                "required": ["tema", "regra", "citacoes"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["regras"],
    "additionalProperties": False,
}


# ------------------------------------------------------------------ proteção de dados
_CPF = re.compile(r"(?<!\d)\d{3}\.?\d{3}\.?\d{3}\s?-?\s?\d{2}(?!\d)")
_RG = re.compile(r"(\b(?:RG|R\.G\.|C[ée]dula de Identidade)\s*(?:n[º°o.]*\s*)?:?\s*)([\dXx][\d.\-Xx/ ]{4,16}[\dXx])", re.I)


def mascarar_dados_pessoais(texto: str) -> str:
    """Troca CPF e número de RG por marcadores. Nomes ficam (são necessários para entender partes e penhoras)."""
    texto = _RG.sub(lambda m: m.group(1) + "[RG]", texto or "")
    return _CPF.sub("[CPF]", texto)


# ------------------------------------------------------------------ conferência das citações
def _normalizar(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r"-\s*\n\s*", "", t)                      # palavra hifenizada na quebra de linha
    t = re.sub(r"[“”\"'`´]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def trecho_existe(trecho: str, texto_pagina: str) -> bool:
    """O trecho (pode ter '...' no meio) aparece na página? Comparação sem acento, caixa e espaços."""
    alvo = _normalizar(texto_pagina)
    partes = [p.strip(" .,;:") for p in re.split(r"\.\.\.|…", _normalizar(trecho))]
    partes = [p for p in partes if len(p) >= 8]
    return bool(partes) and all(p in alvo for p in partes)


def conferir(parecer: dict, fontes: Dict[str, List[str]]) -> dict:
    """Marca cada citação com 'confirmada' (True/False) olhando o texto que foi enviado.
    `fontes`: código do documento -> lista de textos por página (página 1 = índice 0)."""
    def marca(c):
        paginas = fontes.get(c.get("documento", ""), [])
        p = c.get("pagina") or 0
        candidatas = [paginas[p - 1]] if 1 <= p <= len(paginas) else []
        c["confirmada"] = any(trecho_existe(c.get("trecho", ""), t) for t in candidatas)
        if not c["confirmada"] and paginas:              # página errada mas trecho certo: confirma e corrige
            for i, t in enumerate(paginas, start=1):
                if trecho_existe(c.get("trecho", ""), t):
                    c["confirmada"], c["pagina"] = True, i
                    break
        return c
    for it in parecer.get("itens", []):
        it["fatos"] = [marca(c) for c in it.get("fatos", [])]
    for r in parecer.get("riscos", []):
        r["citacoes"] = [marca(c) for c in r.get("citacoes", [])]
    validos = [it for it in parecer.get("itens", []) if it.get("item") in ITENS_CHAVES]
    parecer["itens"] = validos
    total = [c for it in validos for c in it["fatos"]] + [c for r in parecer.get("riscos", []) for c in r["citacoes"]]
    parecer["citacoes_total"] = len(total)
    parecer["citacoes_confirmadas"] = sum(1 for c in total if c["confirmada"])
    return parecer


def conferir_regras(regras: dict, paginas: List[str], codigo: str = "EDITAL") -> dict:
    """Confere as citações das regras do edital contra o texto do edital (todas as páginas)."""
    marca = conferir({"itens": [], "riscos": [{"citacoes": r.get("citacoes", [])} for r in regras.get("regras", [])]},
                     {codigo: paginas})
    for r, conf in zip(regras.get("regras", []), marca["riscos"]):
        r["citacoes"] = conf["citacoes"]
    regras["citacoes_total"], regras["citacoes_confirmadas"] = marca["citacoes_total"], marca["citacoes_confirmadas"]
    return regras
