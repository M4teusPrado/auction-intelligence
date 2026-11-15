"""Ponto único que liga as peças: quais fontes existem e qual banco é usado.

É o único módulo que conhece os adaptadores concretos. Para registrar uma fonte nova,
acrescente-a em FONTES.
"""
from typing import Dict

from .adaptadores.fontes.caixa import FonteCaixa
from .adaptadores.persistencia.sqlite import RepositorioSQLite
from .aplicacao.portas import ErroDeFonte, FonteDeImoveis

FONTES: Dict[str, FonteDeImoveis] = {f.nome: f for f in (FonteCaixa(),)}


def fonte(nome: str) -> FonteDeImoveis:
    try:
        return FONTES[nome]
    except KeyError:
        raise ErroDeFonte(f"fonte desconhecida: {nome}. Disponíveis: " + ", ".join(sorted(FONTES)))


def repositorio(caminho_base: str) -> RepositorioSQLite:
    """Abre a base (migrando o esquema, com cópia, se preciso). Use com `with`."""
    return RepositorioSQLite(caminho_base)
