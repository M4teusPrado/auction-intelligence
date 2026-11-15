"""Portas: o que a aplicação precisa do mundo de fora, sem saber como é feito.

Cada porta é um Protocol: qualquer classe com esses métodos serve, sem herança.
Os adaptadores (adaptadores/) implementam; montagem.py liga as peças.
"""
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Protocol, runtime_checkable

from ..dominio.modelo import ImovelCaptado


class ErroDeFonte(Exception):
    """A fonte não entregou dados utilizáveis: fora do ar, bloqueio, formato inesperado."""


@dataclass
class Coleta:
    """O que uma fonte devolve a cada coleta."""
    imoveis: List[ImovelCaptado]
    recorte: str                  # parte da fonte que foi coletada (ex.: "SP"). Só imóveis
                                  # deste recorte podem ser marcados como "saiu da lista".
    origem: str                   # de onde veio: URL, nome do arquivo...
    avisos: List[str] = field(default_factory=list)   # linhas com problema; nunca viram dado


@runtime_checkable
class FonteDeImoveis(Protocol):
    """Uma origem de imóveis: banco, site de leiloeiro, tribunal...

    Para criar uma fonte nova: um arquivo em adaptadores/fontes/, uma linha em
    montagem.FONTES e uma amostra em tests/test_contrato_fontes.py.
    """
    nome: str                     # identificador curto e estável, gravado em cada imóvel ("caixa")
    descricao: str                # texto para pessoas

    def recortes(self) -> List[str]:
        """Partes em que a fonte se divide (ex.: UFs). Lista vazia = um recorte só, ''."""

    def coletar(self, recorte: str, arquivo: Optional[bytes] = None, nome_arquivo: str = "") -> Coleta:
        """Busca os imóveis do recorte. Com `arquivo`, lê o conteúdo dado em vez de buscar
        (ex.: lista baixada pelo navegador). Problemas de acesso ou formato: ErroDeFonte."""

    def descrever_modalidade(self, modalidade: str) -> Optional[str]:
        """Explicação curta da modalidade de venda desta fonte, como hipótese, ou None."""


class RepositorioDeImoveis(Protocol):
    """Guarda os imóveis captados e o histórico entre coletas."""

    def gravar_coleta(self, fonte: str, recorte: str, origem: str, imoveis: Iterable[ImovelCaptado],
                      n_avisos: int = 0, agora: Optional[str] = None) -> dict:
        """Compara com o que já existe e registra novos, alterados, saídos e voltas."""
