"""Classificação derivada, igual para toda fonte. Nunca altera o valor da fonte:
o `tipo` continua como veio; `categoria` agrupa tipos parecidos."""
from collections import Counter
from typing import List

from .modelo import ImovelCaptado

CATEGORIAS = {
    "casa": "casa", "sobrado": "casa",
    "apartamento": "apartamento",
    "terreno": "terreno", "gleba": "terreno", "gleba urbana": "terreno",
    "comercial": "comercial", "loja": "comercial", "sala": "comercial",
    "galpao": "comercial", "predio": "comercial",
    "imovel rural": "rural",
}


def categoria(tipo: str) -> str:
    return CATEGORIAS.get(tipo or "", "outros")


def classificar(imoveis: List[ImovelCaptado]) -> List[str]:
    """Preenche os campos derivados de cada imóvel e devolve avisos (ex.: tipo novo)."""
    desconhecidos = Counter()
    for im in imoveis:
        im.categoria = categoria(im.tipo)
        if im.tipo not in CATEGORIAS:
            desconhecidos[im.tipo] += 1
    return [f"tipo fora da lista de categorias: '{t}' ({n} imóveis), classificado como outros"
            for t, n in desconhecidos.most_common()]
