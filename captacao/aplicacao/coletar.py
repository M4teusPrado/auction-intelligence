"""Caso de uso: coletar imóveis de uma fonte e atualizar a base. Igual para toda fonte."""
from typing import Optional

from ..dominio import classifica
from .portas import ErroDeFonte, FonteDeImoveis, RepositorioDeImoveis


def coletar(fonte: FonteDeImoveis, repo: RepositorioDeImoveis, recorte: str = "",
            arquivo: Optional[bytes] = None, nome_arquivo: str = "", agora: Optional[str] = None) -> dict:
    recorte = (recorte or "").strip()
    validos = fonte.recortes()
    if validos and recorte not in validos:
        raise ErroDeFonte(f"recorte '{recorte}' não existe na fonte {fonte.nome}: use " + ", ".join(validos))
    if not validos and recorte:
        raise ErroDeFonte(f"a fonte {fonte.nome} não se divide em recortes")
    c = fonte.coletar(recorte, arquivo, nome_arquivo)
    outros = {im.fonte for im in c.imoveis} - {fonte.nome}
    if outros:   # proteção do contrato: uma fonte não grava imóveis em nome de outra
        raise ErroDeFonte(f"a fonte {fonte.nome} devolveu imóveis marcados como {', '.join(sorted(outros))}")
    avisos = list(c.avisos) + classifica.classificar(c.imoveis)
    r = repo.gravar_coleta(fonte.nome, c.recorte, c.origem, c.imoveis, len(avisos), agora)
    r["lista_avisos"] = avisos
    r["recorte"] = c.recorte
    return r
