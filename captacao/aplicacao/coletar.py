"""Caso de uso: coletar imóveis de uma fonte e atualizar a base. Igual para toda fonte."""
from typing import Optional

from ..dominio import classifica
from .portas import EntradaInvalida, ErroDeFonte, FonteDeImoveis, ImportadorDeLink, RepositorioDeImoveis


def coletar(fonte: FonteDeImoveis, repo: RepositorioDeImoveis, recorte: str = "",
            arquivo: Optional[bytes] = None, nome_arquivo: str = "", agora: Optional[str] = None,
            limite: Optional[int] = None) -> dict:
    recorte = (recorte or "").strip()
    validos = fonte.recortes()
    if validos and recorte not in validos:
        raise ErroDeFonte(f"recorte '{recorte}' não existe na fonte {fonte.nome}: use " + ", ".join(validos))
    if not validos and recorte:
        raise ErroDeFonte(f"a fonte {fonte.nome} não se divide em recortes")
    c = fonte.coletar(recorte, arquivo, nome_arquivo, limite)
    outros = {im.fonte for im in c.imoveis} - {fonte.nome}
    if outros:   # proteção do contrato: uma fonte não grava imóveis em nome de outra
        raise ErroDeFonte(f"a fonte {fonte.nome} devolveu imóveis marcados como {', '.join(sorted(outros))}")
    avisos = list(c.avisos) + classifica.classificar(c.imoveis)
    completa = c.completa and not limite
    r = repo.gravar_coleta(fonte.nome, c.recorte, c.origem, c.imoveis, len(avisos), agora, marcar_saidos=completa)
    r["lista_avisos"] = avisos
    r["recorte"] = c.recorte
    r["completa"] = completa
    return r


def importar_link(fontes: dict, repo: RepositorioDeImoveis, url, agora: Optional[str] = None) -> dict:
    """Lê uma oferta pelo link, na fonte que reconhece o endereço, e grava como anúncio."""
    if not isinstance(url, str) or not url.strip().startswith("https://") or len(url) > 1000:
        raise EntradaInvalida("envie o link completo da oferta, começando com https://")
    url = url.strip()
    capazes = [f for f in fontes.values() if isinstance(f, ImportadorDeLink)]
    fonte = next((f for f in capazes if f.aceita_url(url)), None)
    if fonte is None:
        nomes = ", ".join(sorted(f.rotulo for f in capazes)) or "nenhum"
        raise EntradaInvalida(f"este site ainda não é suportado. Hoje: {nomes}.")
    im = fonte.importar_url(url)
    if im.fonte != fonte.nome:
        raise ErroDeFonte(f"a fonte {fonte.nome} devolveu um imóvel marcado como {im.fonte}")
    avisos = classifica.classificar([im])
    imovel_id = repo.gravar_avulso(im, url, agora)
    return {"id": imovel_id, "fonte": fonte.nome, "id_fonte": im.id_fonte, "avisos": avisos}
