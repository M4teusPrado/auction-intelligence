"""Vocabulário da análise de um imóvel: estágios da triagem, itens da investigação,
situações possíveis e tipos de anexo. Regras fixas, sem banco nem tela."""

ESTAGIOS = ("identificado", "analisar", "depois", "descartado")

ORDENACOES = ("desconto", "preco", "area_terreno", "recente", "leilao")

ITENS_INVESTIGACAO = [  # (chave, rótulo, o que conferir)
    ("leilao", "Tipo de leilão", "Extrajudicial ou judicial, praça, data e regras de pagamento."),
    ("edital", "Edital lido", "Quem paga débitos, prazo de pagamento, condições de venda."),
    ("matricula", "Matrícula", "Proprietário, ônus, penhoras, averbações e a consolidação da propriedade."),
    ("ocupacao", "Ocupação", "Ocupado ou desocupado; por quem (ex-mutuário, inquilino)."),
    ("iptu", "Débitos de IPTU", "Valor em aberto e quem assume, segundo o edital."),
    ("condominio", "Débitos de condomínio", "Valor em aberto e quem assume, segundo o edital."),
    ("vistoria", "Localização e vistoria externa", "Rua, vizinhança, estado aparente, acesso."),
]
ITENS_CHAVES = [i[0] for i in ITENS_INVESTIGACAO]

STATUS_INVESTIGACAO = {"pendente": "Pendente", "ok": "OK", "atencao": "Atenção",
                       "impeditivo": "Impeditivo", "nao_se_aplica": "Não se aplica"}

TIPOS_ANEXO = {"matricula": "Matrícula", "edital": "Edital", "laudo": "Laudo", "foto": "Foto", "outro": "Outro"}


def checklist(atuais: dict) -> list:
    """Lista completa de itens com a situação atual (pendente quando nunca foi marcado)."""
    return [{"item": k, "rotulo": rot, "ajuda": ajuda,
             "status": atuais.get(k, {}).get("status", "pendente"),
             "nota": atuais.get(k, {}).get("nota"),
             "quando": atuais.get(k, {}).get("quando")} for k, rot, ajuda in ITENS_INVESTIGACAO]
