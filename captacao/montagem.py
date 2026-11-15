"""Ponto único que liga as peças: quais fontes existem e qual banco é usado.

É o único módulo que conhece os adaptadores concretos. Para registrar uma fonte nova,
acrescente-a em FONTES.
"""
import os
import sys
from typing import Dict

from .adaptadores.fontes.caixa import FonteCaixa
from .adaptadores.fontes.megaleiloes import FonteMegaLeiloes
from .adaptadores.fontes.soleon import FonteSoleon
from .adaptadores.persistencia.sqlite import RepositorioSQLite
from .adaptadores.web import ClienteWeb
from .aplicacao.portas import ErroDeFonte, FonteDeImoveis

# Cópia local das páginas lidas (evita pedir de novo a mesma página no mesmo dia).
CLIENTE_WEB = ClienteWeb(pasta_cache=os.environ.get("CAPTACAO_CACHE_WEB", "cache_web"))


def _relatar(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


FONTES: Dict[str, FonteDeImoveis] = {f.nome: f for f in (
    FonteCaixa(),
    FonteMegaLeiloes(CLIENTE_WEB, relatar=_relatar),
    FonteSoleon(CLIENTE_WEB, relatar=_relatar),
)}


def fonte(nome: str) -> FonteDeImoveis:
    try:
        return FONTES[nome]
    except KeyError:
        raise ErroDeFonte(f"fonte desconhecida: {nome}. Disponíveis: " + ", ".join(sorted(FONTES)))


def repositorio(caminho_base: str, migrar: bool = True) -> RepositorioSQLite:
    """Abre a base (migrando o esquema, com cópia, se preciso). Use com `with`."""
    return RepositorioSQLite(caminho_base, migrar)
