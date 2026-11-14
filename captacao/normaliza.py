"""Funções puras de limpeza de texto e números."""
import re
import unicodedata
from typing import Optional


def sem_acento(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def chave(texto: str) -> str:
    """Texto comparável: sem acento, minúsculo, só letras e números."""
    return re.sub(r"[^a-z0-9]+", " ", sem_acento(texto).lower()).strip()


def numero_br(texto: str) -> Optional[float]:
    """Converte '1.234.567,89', '150000.00' ou 'R$ 90.000,00' em float. Vazio vira None."""
    t = re.sub(r"[^\d,.\-]", "", texto or "")
    if not t:
        return None
    if "," in t:                       # formato brasileiro: ponto é milhar
        t = t.replace(".", "").replace(",", ".")
    elif t.count(".") > 1:             # 1.234.567 sem decimais
        t = t.replace(".", "")
    try:
        return float(t)
    except ValueError:
        return None


_ABREV = {"r": "rua", "av": "avenida", "avn": "avenida", "al": "alameda", "trav": "travessa",
          "tv": "travessa", "rod": "rodovia", "estr": "estrada", "pc": "praca", "pca": "praca",
          "n": "", "no": "", "num": "", "numero": ""}


def chave_endereco(uf: str, cidade: str, endereco: str) -> str:
    """Chave para sugerir o mesmo imóvel vindo de fontes diferentes.
    É só uma sugestão: endereços variam muito e uma pessoa precisa confirmar."""
    palavras = [_ABREV.get(p, p) for p in chave(endereco).split()]
    return "|".join([chave(uf), chave(cidade), " ".join(p for p in palavras if p)])
