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
    completa: bool = True         # False = parte do recorte não foi lida (limite, página com erro).
                                  # Coleta incompleta não marca ninguém como "saiu da lista".


@runtime_checkable
class FonteDeImoveis(Protocol):
    """Uma origem de imóveis: banco, site de leiloeiro, tribunal...

    Para criar uma fonte nova: um arquivo em adaptadores/fontes/, uma linha em
    montagem.FONTES e uma amostra em tests/test_contrato_fontes.py.
    """
    nome: str                     # identificador curto e estável, gravado em cada imóvel ("caixa")
    rotulo: str                   # nome curto para a tela ("Caixa", "Mega Leilões")
    descricao: str                # texto para pessoas

    def recortes(self) -> List[str]:
        """Partes em que a fonte se divide (ex.: UFs). Lista vazia = um recorte só, ''."""

    def coletar(self, recorte: str, arquivo: Optional[bytes] = None, nome_arquivo: str = "",
                limite: Optional[int] = None) -> Coleta:
        """Busca os imóveis do recorte. Com `arquivo`, lê o conteúdo dado em vez de buscar
        (ex.: lista baixada pelo navegador). `limite` corta o número de imóveis (testes).
        Problemas de acesso ou formato: ErroDeFonte."""

    def descrever_modalidade(self, modalidade: str) -> Optional[str]:
        """Explicação curta da modalidade de venda desta fonte, como hipótese, ou None."""


@runtime_checkable
class ImportadorDeLink(Protocol):
    """Capacidade opcional de uma fonte: ler um imóvel a partir do link de uma oferta."""

    def aceita_url(self, url: str) -> bool: ...
    def importar_url(self, url: str) -> ImovelCaptado: ...


class BaixadorWeb(Protocol):
    """Acesso educado à web (robots.txt, intervalo entre pedidos). Falha: ErroDeFonte."""

    def baixar(self, url: str, usar_cache: bool = True) -> bytes: ...


class RepositorioDeImoveis(Protocol):
    """Guarda os imóveis captados e o histórico entre coletas."""

    def gravar_coleta(self, fonte: str, recorte: str, origem: str, imoveis: Iterable[ImovelCaptado],
                      n_avisos: int = 0, agora: Optional[str] = None, marcar_saidos: bool = True) -> dict:
        """Compara com o que já existe e registra novos, alterados, saídos e voltas."""

    def gravar_avulso(self, imovel: ImovelCaptado, origem: str, agora: Optional[str] = None) -> int:
        """Grava um imóvel importado por link (sem marcar outros como saídos). Devolve o id."""


# ---------------------------------------------------------------------- análise

class EntradaInvalida(ValueError):
    """Parâmetro ou corpo inválido vindo de quem usa o sistema (HTTP 400)."""


class NaoEncontrado(LookupError):
    """Imóvel ou anexo inexistente (HTTP 404)."""


@dataclass
class FiltroImoveis:
    """Filtro já validado para listar imóveis ativos."""
    estagio: Optional[str] = None
    fontes: List[str] = field(default_factory=list)
    uf: Optional[str] = None
    modalidades: List[str] = field(default_factory=list)
    categorias: List[str] = field(default_factory=list)
    cidade: Optional[str] = None          # trecho do nome, sem diferença de acento ou maiúscula
    tipo: Optional[str] = None            # trecho do tipo da fonte
    preco_min: Optional[float] = None
    preco_max: Optional[float] = None
    desconto_min: Optional[float] = None
    area_terreno_min: Optional[float] = None
    sem_alertas: bool = False
    ordem: str = "desconto"               # uma de dominio.analise.ORDENACOES
    limite: int = 50
    deslocamento: int = 0


class RepositorioDeAnalise(Protocol):
    """Consulta de imóveis e tudo o que as pessoas registram sobre eles. Nada é apagado."""

    def listar_imoveis(self, filtro: FiltroImoveis) -> tuple: ...          # (total, [imóvel])
    def buscar_imovel(self, imovel_id: int) -> Optional[dict]: ...
    def contar_por_estagio(self) -> dict: ...
    def ultima_coleta(self) -> Optional[dict]: ...
    def eventos_da_coleta(self, coleta_id: int, limite: int) -> List[dict]: ...
    def opcoes(self) -> dict: ...
    def historico(self, imovel_id: int) -> List[dict]: ...
    def triagens(self, imovel_id: int) -> List[dict]: ...
    def ultima_triagem(self, imovel_id: int) -> Optional[dict]: ...
    def registrar_triagem(self, imovel_id: int, de: str, para: str, nota: Optional[str], quando: str) -> int: ...
    def investigacao_atual(self, imovel_id: int) -> dict: ...
    def registrar_investigacao(self, imovel_id: int, item: str, status: str, nota: Optional[str], quando: str) -> None: ...
    def anexos(self, imovel_id: int) -> List[dict]: ...
    def anexo_por_conteudo(self, imovel_id: int, sha256: str) -> Optional[int]: ...
    def inserir_anexo(self, imovel_id: int, tipo: str, nome: str, arquivo: str, tamanho: int, sha256: str, quando: str) -> int: ...
    def anexo(self, anexo_id: int) -> Optional[dict]: ...
    def anexos_sem_leitura(self, imovel_id: int) -> List[dict]: ...
    def gravar_leitura(self, anexo_id: int, situacao: str, paginas: Optional[List[str]] = None) -> None: ...
    def textos_lidos(self, imovel_id: int) -> List[dict]: ...
    def ultima_simulacao(self, imovel_id: int) -> Optional[dict]: ...
    def salvar_simulacao(self, imovel_id: int, premissas: dict, resultado: dict, quando: str) -> None: ...
