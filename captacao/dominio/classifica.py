"""Classificação derivada, igual para toda fonte. Nunca altera o valor da fonte:
o `tipo` continua como veio; `categoria` agrupa tipos parecidos."""
import re
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
    "salao": "comercial",
    "vaga de garagem": "outros", "outros": "outros",      # tipos conhecidos sem categoria própria
}


# Itens de construção que a Caixa lista depois das áreas, ex.: "2 qto(s), WC, cozinha".
COMODOS = re.compile(r"\bqto\(s\)|\bsala\(s\)|\bwc\b|\bcozinha\b|\ba\.serv\b|\bvaga\(s\)",
                     re.I)


def categoria(tipo: str) -> str:
    return CATEGORIAS.get(tipo or "", "outros")


def alertas(im: ImovelCaptado) -> str:
    """Códigos separados por vírgula ("" se nenhum). Só marca; não corrige a fonte."""
    cods = []
    if im.area_terreno is not None and im.area_terreno <= 1.0:
        cods.append("area_terreno_suspeita")
    if categoria(im.tipo) == "terreno" and (
            (im.area_total or 0) > 0 or COMODOS.search(im.descricao or "")):
        cods.append("terreno_com_construcao")
    if im.area_privativa is None and im.area_terreno is None and im.area_total is None:
        cods.append("sem_area")
    if im.preco is None:
        cods.append("preco_ausente")
    return ",".join(cods)


def classificar(imoveis: List[ImovelCaptado]) -> List[str]:
    """Preenche os campos derivados de cada imóvel e devolve avisos (ex.: tipo novo)."""
    desconhecidos = Counter()
    for im in imoveis:
        im.categoria = categoria(im.tipo)
        im.alertas = alertas(im)
        if im.tipo not in CATEGORIAS:
            desconhecidos[im.tipo] += 1
    return [f"tipo fora da lista de categorias: '{t}' ({n} imóveis), classificado como outros"
            for t, n in desconhecidos.most_common()]
