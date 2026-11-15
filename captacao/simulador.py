"""Simulador de custos e retorno de um imóvel de leilão. Regra fixa, sem IA.

Todas as premissas são visíveis e editáveis. Os valores padrão são EXEMPLOS a
confirmar com quem opera (Ruan), não verdade: percentuais comuns de mercado onde
existe referência, e zero onde o valor depende do imóvel (débitos, reforma...).
O valor de venda não tem padrão: a avaliação da Caixa não é valor de mercado.
"""
import math
from typing import Dict, Optional

# chave: (rótulo, unidade, padrão, explicação, grupo)
PREMISSAS = {
    "lance": ("Lance / preço de compra", "R$", None,
              "Começa no preço da Caixa; no leilão o lance final pode ser maior.", "compra"),
    "comissao_leiloeiro_pct": ("Comissão do leiloeiro", "%", 5.0,
              "Comum em leilão com leiloeiro (5% sobre o lance). Em venda direta costuma não haver.", "compra"),
    "itbi_pct": ("ITBI", "%", 3.0,
              "3% na cidade de São Paulo; cada cidade tem alíquota própria. Calculado sobre o lance "
              "(a prefeitura pode usar o valor venal, se maior).", "compra"),
    "registro_pct": ("Escritura e registro", "%", 1.5,
              "Estimativa genérica; o custo real segue a tabela do cartório do estado.", "compra"),
    "debitos": ("Débitos que ficam com o comprador", "R$", 0.0,
              "IPTU e condomínio atrasados, conforme o edital. Preencher depois da investigação.", "custos"),
    "desocupacao": ("Desocupação", "R$", 0.0,
              "Advogado ou acordo, se o imóvel estiver ocupado.", "custos"),
    "reforma_m2": ("Reforma por m²", "R$/m²", 0.0, "Preencher conforme o estado do imóvel.", "custos"),
    "area_reforma": ("Área a reformar", "m²", None,
              "Começa na área privativa (ou total) informada pela Caixa.", "custos"),
    "custo_mensal": ("Custo mensal até vender", "R$/mês", 0.0,
              "IPTU, condomínio e contas enquanto o imóvel não é vendido.", "custos"),
    "prazo_meses": ("Prazo até a venda", "meses", 12.0,
              "Da arrematação até receber o valor da venda.", "venda"),
    "valor_venda": ("Valor de venda estimado", "R$", None,
              "Sem padrão: a avaliação da Caixa não é valor de mercado. Use pesquisa de mercado.", "venda"),
    "corretagem_pct": ("Corretagem na venda", "%", 6.0,
              "Referência comum de comissão de corretor; negociável.", "venda"),
    "ir_pct": ("Imposto sobre o ganho", "%", 15.0,
              "Ganho de capital de pessoa física, simplificado (sem isenções nem deduções). "
              "Confirmar com contador.", "venda"),
    "meta_roi_pct": ("Retorno mínimo desejado", "%", None,
              "Opcional. Com ele o simulador calcula o lance máximo que ainda atinge esse retorno.", "venda"),
}
PERCENTUAIS = {k for k, v in PREMISSAS.items() if v[1] == "%" and k != "meta_roi_pct"}
LIMITE = 1e10


class PremissaInvalida(ValueError):
    pass


def padrao_para(imovel: dict) -> Dict[str, Optional[float]]:
    """Premissas padrão preenchidas com o que a fonte informa sobre o imóvel."""
    p = {k: v[2] for k, v in PREMISSAS.items()}
    p["lance"] = imovel.get("preco")
    p["area_reforma"] = imovel.get("area_privativa") or imovel.get("area_total")
    return p


def validar(premissas) -> Dict[str, Optional[float]]:
    if not isinstance(premissas, dict):
        raise PremissaInvalida("premissas devem ser um objeto")
    extras = set(premissas) - set(PREMISSAS)
    if extras:
        raise PremissaInvalida("premissa desconhecida: " + ", ".join(sorted(extras)))
    p = {}
    for k, (rotulo, unidade, padrao, _, _) in PREMISSAS.items():
        v = premissas.get(k, padrao)
        if v is None or v == "":
            p[k] = None
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise PremissaInvalida(f"{rotulo}: deve ser um número")
        v = float(v)
        if not math.isfinite(v) or v < 0 or v > LIMITE:
            raise PremissaInvalida(f"{rotulo}: fora do intervalo aceito")
        if k in PERCENTUAIS and v > 100:
            raise PremissaInvalida(f"{rotulo}: percentual acima de 100")
        if k == "meta_roi_pct" and v > 1000:
            raise PremissaInvalida(f"{rotulo}: acima de 1000%")
        p[k] = v
    if p["prazo_meses"] is None or not 1 <= p["prazo_meses"] <= 120:
        raise PremissaInvalida("Prazo até a venda: entre 1 e 120 meses")
    for k in PREMISSAS:
        if PREMISSAS[k][2] is not None and p[k] is None:
            raise PremissaInvalida(f"{PREMISSAS[k][0]}: informe um valor")
    return p


def _conta(p: dict, lance: float) -> dict:
    pct = lambda k: (p[k] or 0) / 100
    leiloeiro = lance * pct("comissao_leiloeiro_pct")
    itbi = lance * pct("itbi_pct")
    registro = lance * pct("registro_pct")
    reforma = (p["reforma_m2"] or 0) * (p["area_reforma"] or 0)
    manutencao = (p["custo_mensal"] or 0) * p["prazo_meses"]
    investimento = lance + leiloeiro + itbi + registro + p["debitos"] + p["desocupacao"] + reforma + manutencao
    r = {"leiloeiro": leiloeiro, "itbi": itbi, "registro": registro, "reforma": reforma,
         "manutencao": manutencao, "investimento": investimento}
    if p["valor_venda"] is not None:
        corretagem = p["valor_venda"] * pct("corretagem_pct")
        lucro_antes_ir = p["valor_venda"] - corretagem - investimento
        ir = max(0.0, lucro_antes_ir) * pct("ir_pct")
        lucro = lucro_antes_ir - ir
        roi = lucro / investimento if investimento > 0 else None
        r.update(corretagem=corretagem, lucro_antes_ir=lucro_antes_ir, ir=ir, lucro=lucro, roi=roi)
    return r


def _lance_maximo(p: dict) -> Optional[float]:
    """Maior lance cujo retorno ainda atinge a meta (o retorno cai quando o lance sobe)."""
    meta = p["meta_roi_pct"] / 100
    def atinge(lance):
        roi = _conta(p, lance).get("roi")
        return roi is not None and roi >= meta
    # parte de R$ 1, não de zero: com lance zero e sem outros custos o investimento
    # seria zero e o retorno ficaria indefinido
    if not atinge(1.0):
        return None
    lo, hi = 1.0, p["valor_venda"]
    for _ in range(80):
        meio = (lo + hi) / 2
        lo, hi = (meio, hi) if atinge(meio) else (lo, meio)
    return math.floor(lo)


def simular(premissas) -> dict:
    p = validar(premissas)
    avisos = []
    if p["lance"] is None:
        raise PremissaInvalida("Lance / preço de compra: informe um valor")
    c = _conta(p, p["lance"])
    linhas = [
        ("Lance / preço de compra", p["lance"]),
        ("Comissão do leiloeiro", c["leiloeiro"]),
        ("ITBI", c["itbi"]),
        ("Escritura e registro", c["registro"]),
        ("Débitos que ficam com o comprador", p["debitos"]),
        ("Desocupação", p["desocupacao"]),
        ("Reforma", c["reforma"]),
        ("Custo mensal × prazo", c["manutencao"]),
    ]
    r = {"premissas": p, "custos": [{"rotulo": a, "valor": round(b, 2)} for a, b in linhas],
         "investimento": round(c["investimento"], 2), "venda": None, "lance_maximo": None}
    if p["valor_venda"] is None:
        avisos.append("Informe o valor de venda estimado para calcular lucro e retorno.")
    else:
        roi = c["roi"]
        roi_mes = (1 + roi) ** (1 / p["prazo_meses"]) - 1 if roi is not None and roi > -1 else None
        r["venda"] = {"valor_venda": p["valor_venda"], "corretagem": round(c["corretagem"], 2),
                      "lucro_antes_ir": round(c["lucro_antes_ir"], 2), "ir": round(c["ir"], 2),
                      "lucro": round(c["lucro"], 2),
                      "roi_pct": None if roi is None else round(roi * 100, 2),
                      "roi_mes_pct": None if roi_mes is None else round(roi_mes * 100, 2)}
        if p["meta_roi_pct"] is not None:
            r["lance_maximo"] = _lance_maximo(p)
            if r["lance_maximo"] is None:
                avisos.append("Nem com lance zero a meta de retorno é atingida com essas premissas.")
    if (p["reforma_m2"] or 0) > 0 and not p["area_reforma"]:
        avisos.append("Reforma por m² informada, mas a área a reformar está vazia.")
    r["avisos"] = avisos
    return r


def descricao_premissas() -> list:
    return [{"chave": k, "rotulo": v[0], "unidade": v[1], "padrao": v[2], "explicacao": v[3], "grupo": v[4]}
            for k, v in PREMISSAS.items()]
