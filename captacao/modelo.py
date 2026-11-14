"""Estrutura comum de um imóvel captado, igual para qualquer fonte."""
from dataclasses import dataclass, asdict
from typing import Optional


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
    descricao: str
    link: str
    data_fonte: str            # data de geração informada pela fonte, se houver

    def como_dict(self) -> dict:
        return asdict(self)

    # Campos cuja mudança entre coletas é registrada no histórico.
    CAMPOS_MONITORADOS = ("preco", "valor_avaliacao", "desconto_pct", "modalidade")
