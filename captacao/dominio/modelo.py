"""Estrutura comum de um imóvel captado, igual para qualquer fonte."""
from dataclasses import dataclass, asdict, field
from typing import List, Optional


@dataclass
class Praca:
    """Uma praça (rodada) do leilão: 1ª, 2ª ou única."""
    numero: int                        # 1, 2... (praça única = 1)
    data: Optional[str]                # "AAAA-MM-DDTHH:MM", horário informado pela fonte
    valor: Optional[float]             # lance mínimo desta praça


@dataclass
class DocumentoFonte:
    """Documento publicado pela fonte (edital, matrícula, laudo), ainda não baixado."""
    tipo: str                          # edital | matricula | laudo | outro
    url: str
    rotulo: str = ""


@dataclass
class DadosLeilao:
    """O que um leilão tem e uma lista de banco não tem. Tudo como informado pela fonte."""
    tipo_venda: str = ""               # Judicial | Extrajudicial | Venda direta...
    leilao: str = ""                   # código do leilão na fonte (ex.: ML35144)
    lote: str = ""
    comitente: str = ""                # quem vende (ex.: o banco)
    leiloeiro: str = ""
    ocupacao: str = ""                 # ocupado | desocupado | "" (não informado)
    matricula: str = ""
    cartorio: str = ""
    processo: str = ""
    vara: str = ""
    comissao_pct: Optional[float] = None
    incremento: Optional[float] = None
    pracas: List[Praca] = field(default_factory=list)
    documentos: List[DocumentoFonte] = field(default_factory=list)


@dataclass
class ImovelCaptado:
    fonte: str                 # ex.: "caixa"
    id_fonte: str              # identificador do imóvel na fonte
    uf: str
    cidade: str
    bairro: str
    endereco: str
    preco: Optional[float]             # valor mínimo de venda na fonte
    valor_avaliacao: Optional[float]   # avaliação informada pela fonte (não é valor de mercado)
    desconto_pct: Optional[float]
    modalidade: str
    tipo: str                  # casa, apartamento, terreno... (extraído da descrição, melhor esforço)
    area_privativa: Optional[float]
    area_terreno: Optional[float]
    area_total: Optional[float]        # área total da fonte; não substitui a privativa
    descricao: str
    link: str
    data_fonte: str            # data de geração informada pela fonte, se houver
    categoria: str = ""        # derivada do tipo (classifica.py); o tipo da fonte não muda
    alertas: str = ""          # códigos separados por vírgula (classifica.py); só marca, não corrige
    leilao: Optional[DadosLeilao] = None   # só fontes de leilão preenchem

    def como_dict(self) -> dict:
        return asdict(self)

    # Campos cuja mudança entre coletas é registrada no histórico.
    CAMPOS_MONITORADOS = ("preco", "valor_avaliacao", "desconto_pct", "modalidade")
