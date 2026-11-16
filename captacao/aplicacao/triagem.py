"""Casos de uso da triagem: listar, resumo, opções e mudar o estágio de um imóvel.

Recebem um RepositorioDeAnalise e parâmetros já lidos (dicionário de listas, como
devolve urllib.parse.parse_qs). Validam toda entrada e devolvem dicts prontos para JSON.
Não sabem de SQL nem de HTTP.
"""
import math
from datetime import datetime
from typing import Dict, List, Optional

from ..dominio.analise import ESTAGIOS, ORDENACOES
from ..dominio.classifica import CATEGORIAS
from ..dominio.normaliza import chave
from .portas import EntradaInvalida, FiltroImoveis, NaoEncontrado, RepositorioDeAnalise

POR_PAGINA = 50
CATEGORIAS_VALIDAS = sorted(set(CATEGORIAS.values()) | {"outros"})
PARAMS_LISTA = {"estagio", "fonte", "modalidade", "categoria", "cidade", "preco_min", "preco_max",
                "desconto_min", "area_terreno_min", "sem_alertas", "ordem", "pagina"}
MULTIPLOS = {"fonte", "modalidade", "categoria", "cidade"}
NOTA_MAX = 1000

__all__ = ["listar", "resumo", "opcoes", "triar", "EntradaInvalida", "NaoEncontrado"]


# ---------- validação ----------

def _um(params: Dict[str, List[str]], nome: str) -> Optional[str]:
    vals = params.get(nome) or []
    if len(vals) > 1:
        raise EntradaInvalida(f"'{nome}' aceita um só valor")
    v = vals[0].strip() if vals else ""
    return v or None


def _numero(params, nome: str) -> Optional[float]:
    v = _um(params, nome)
    if v is None:
        return None
    try:
        n = float(v.replace(",", "."))
    except ValueError:
        raise EntradaInvalida(f"'{nome}' deve ser um número")
    if not math.isfinite(n) or n < 0 or n > 1e10:
        raise EntradaInvalida(f"'{nome}' fora do intervalo aceito")
    return n


def _booleano(params, nome: str) -> bool:
    v = _um(params, nome)
    if v is None or v.lower() in ("0", "false", "nao", "não"):
        return False
    if v.lower() in ("1", "true", "sim"):
        return True
    raise EntradaInvalida(f"'{nome}' deve ser 1 ou 0")


def _texto(valor: str, nome: str, maximo: int) -> str:
    if len(valor) > maximo:
        raise EntradaInvalida(f"'{nome}' muito longo (máximo {maximo} caracteres)")
    return valor


def filtro_da_tela(params: Dict[str, List[str]]) -> FiltroImoveis:
    """Valida os parâmetros da tela e monta o filtro. Erro de entrada: EntradaInvalida."""
    desconhecidos = set(params) - PARAMS_LISTA
    if desconhecidos:
        raise EntradaInvalida("parâmetro desconhecido: " + ", ".join(sorted(desconhecidos)))
    for nome in set(params) - MULTIPLOS:
        _um(params, nome)                     # rejeita repetição em parâmetro simples
    f = FiltroImoveis()
    f.estagio = _um(params, "estagio")
    if f.estagio is not None and f.estagio not in ESTAGIOS:
        raise EntradaInvalida("estágio inválido: use " + ", ".join(ESTAGIOS))
    f.fontes = [_texto(x.strip(), "fonte", 40) for x in params.get("fonte", []) if x.strip()]
    f.modalidades = [_texto(m.strip(), "modalidade", 120) for m in params.get("modalidade", []) if m.strip()]
    if len(f.modalidades) > 30:
        raise EntradaInvalida("modalidades demais")
    f.categorias = [c.strip().lower() for c in params.get("categoria", []) if c.strip()]
    for c in f.categorias:
        if c not in CATEGORIAS_VALIDAS:
            raise EntradaInvalida("categoria inválida: use " + ", ".join(CATEGORIAS_VALIDAS))
    f.cidades = [c for c in (_texto(x, "cidade", 80) for x in params.get("cidade", [])) if chave(c)]
    if len(f.cidades) > 30:
        raise EntradaInvalida("cidades demais (máximo 30)")
    f.preco_min, f.preco_max = _numero(params, "preco_min"), _numero(params, "preco_max")
    f.desconto_min, f.area_terreno_min = _numero(params, "desconto_min"), _numero(params, "area_terreno_min")
    f.sem_alertas = _booleano(params, "sem_alertas")
    f.ordem = _um(params, "ordem") or "desconto"
    if f.ordem not in ORDENACOES:
        raise EntradaInvalida("ordem inválida: use " + ", ".join(ORDENACOES))
    pagina_txt = _um(params, "pagina") or "1"
    if not pagina_txt.isdigit() or not 1 <= int(pagina_txt) <= 100000:
        raise EntradaInvalida("'pagina' deve ser um inteiro a partir de 1")
    f.limite, f.deslocamento = POR_PAGINA, (int(pagina_txt) - 1) * POR_PAGINA
    return f


# ---------- casos de uso ----------

def listar(repo: RepositorioDeAnalise, params: Dict[str, List[str]]) -> dict:
    f = filtro_da_tela(params)
    total, itens = repo.listar_imoveis(f)
    return {"total": total, "pagina": f.deslocamento // POR_PAGINA + 1, "por_pagina": POR_PAGINA,
            "paginas": max(1, math.ceil(total / POR_PAGINA)), "ordem": f.ordem, "itens": itens}


def resumo(repo: RepositorioDeAnalise) -> dict:
    contagem = repo.contar_por_estagio()
    por_estagio = {e: contagem.get(e, 0) for e in ESTAGIOS}
    ult = repo.ultima_coleta()
    coleta = None if not ult else {
        k: ult[k] for k in ("id", "quando", "fonte", "recorte", "data_fonte", "total", "novos", "quedas_preco", "saidos")}
    return {"total_ativo": sum(por_estagio.values()), "por_estagio": por_estagio, "ultima_coleta": coleta}


def opcoes(repo: RepositorioDeAnalise) -> dict:
    return {**repo.opcoes(), "estagios": list(ESTAGIOS), "ordens": list(ORDENACOES)}


def triar(repo: RepositorioDeAnalise, imovel_id: int, corpo, agora: str = None) -> dict:
    """Muda o estágio e registra a mudança. {"desfazer": true} volta ao estágio anterior
    à última triagem, com uma linha nova (nada é apagado)."""
    if not isinstance(corpo, dict):
        raise EntradaInvalida("o corpo deve ser um objeto JSON")
    extras = set(corpo) - {"para", "nota", "desfazer"}
    if extras:
        raise EntradaInvalida("campo desconhecido: " + ", ".join(sorted(extras)))
    atual = repo.buscar_imovel(imovel_id)
    if atual is None:
        raise NaoEncontrado(f"imóvel {imovel_id} não encontrado")

    if corpo.get("desfazer") is not None:
        if corpo["desfazer"] is not True or "para" in corpo or "nota" in corpo:
            raise EntradaInvalida("desfazer: envie só {\"desfazer\": true}")
        ultima = repo.ultima_triagem(imovel_id)
        if ultima is None:
            raise EntradaInvalida("não há triagem para desfazer")
        if ultima["para"] != atual["estagio"]:
            raise EntradaInvalida("o estágio mudou desde a última triagem; recarregue a lista")
        para, nota = ultima["de"], None
    else:
        para = corpo.get("para")
        if para not in ESTAGIOS:
            raise EntradaInvalida("'para' deve ser um de: " + ", ".join(ESTAGIOS))
        if para == atual["estagio"]:
            raise EntradaInvalida(f"o imóvel já está em '{para}'")
        nota = corpo.get("nota")
        if nota is not None:
            if not isinstance(nota, str):
                raise EntradaInvalida("'nota' deve ser texto")
            nota = _texto(nota.strip(), "nota", NOTA_MAX) or None

    agora = agora or datetime.now().isoformat(timespec="seconds")
    triagem_id = repo.registrar_triagem(imovel_id, atual["estagio"], para, nota, agora)
    im = repo.buscar_imovel(imovel_id)
    im["triagem"] = {"id": triagem_id, "de": atual["estagio"], "para": para}
    return im
