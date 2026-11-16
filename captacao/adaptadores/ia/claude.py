"""Adaptador da porta AnalisadorDeDocumentos usando o Claude (API da Anthropic).

Aprovado pelo Mateus em 15/11/2026: roda só quando a pessoa clica, CPF/RG mascarados antes
do envio (feito no caso de uso), a IA só sugere. Credencial: ANTHROPIC_API_KEY ou
`ant auth login` (o SDK encontra sozinho). Sem credencial, a tela mostra o motivo.
"""
import json
import os
from typing import Optional

from ...aplicacao.portas import ErroDeAnalise
from ...dominio.parecer import ESQUEMA_PARECER, ESQUEMA_REGRAS_EDITAL

try:
    import anthropic
except ImportError:            # SDK não instalado: análise desligada
    anthropic = None

MODELO = "claude-opus-5-5"             # parecer do imóvel (definido pelo teste comparativo)
MODELO_EDITAL = "claude-opus-5-5"      # regras do edital: uma vez por edital, vale para todos os imóveis dele
MODELO_TRANSCRICAO = "claude-haiku-5-5"  # copiar texto de PDF escaneado: não exige raciocínio, ~40x mais barato

# US$ por milhão de tokens (entrada, saída), tabela da Anthropic de nov/2026.
PRECOS = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50)}
PRECOS_LONGOS = {"claude-haiku-5-5": (100_000, 0.50, 2.50)}   # acima de N tokens de entrada, outra faixa
PRECO_POR_MILHAO = PRECOS[MODELO]


def custo_usd(modelo: str, entrada: int, saida: int) -> float:
    pe, ps = PRECOS.get(modelo, PRECOS[MODELO])
    if modelo in PRECOS_LONGOS and entrada > PRECOS_LONGOS[modelo][0]:
        pe, ps = PRECOS_LONGOS[modelo][1:]
    return round(entrada / 1e6 * pe + saida / 1e6 * ps, 4)


INSTRUCOES = """Você ajuda um analista de imóveis de leilão no Brasil a investigar um imóvel antes de dar lance. \
Leia os dados, a descrição do lote e os documentos (edital, matrícula, laudo) e organize o que eles dizem.

Preencha os 7 itens da investigação, sempre todos: leilao, edital, matricula, ocupacao, iptu, condominio, vistoria.

Regras:
1. Use só o que está escrito no material recebido. Não use conhecimento externo sobre o imóvel, a região ou o mercado, \
e não estime valores de mercado, dívidas ou custos que não estejam escritos.
2. Cada fato precisa de citação: código do documento (DESCRICAO ou A<número>), página e um trecho copiado literalmente \
do texto (até 300 caracteres; use ... para juntar partes). Não reescreva o trecho com suas palavras.
3. situacao_sugerida de cada item: ok (o material indica que está resolvido), atencao (há algo a verificar ou um custo), \
impeditivo (algo que pode inviabilizar a compra, como ônus que não se extingue com o leilão, ação que discute a \
propriedade, venda de direitos ou fração sem clareza), sem_informacao (o material não trata do assunto). \
É uma sugestão; o analista decide.
4. Matrícula: liste ônus e averbações relevantes (penhora, indisponibilidade, hipoteca, alienação fiduciária, \
consolidação da propriedade) e diga se algum foi cancelado depois.
5. Ocupação: o que o material diz sobre moradores ou ocupantes e quem fica responsável pela desocupação.
6. IPTU e condomínio: valores e datas só se estiverem escritos; quem paga, segundo o edital.
7. riscos: pontos de atenção para a operação, cada um com nível (alto, medio, baixo), explicação curta e citações. \
Inclua só riscos que decorrem do texto (por exemplo: desocupação a cargo do comprador, venda "ad corpus", venda de \
direitos, venda condicional à aprovação do vendedor, débitos que ficam com o comprador, lance mínimo muito abaixo da \
avaliação em leilão judicial).
8. perguntas: o que o analista ainda precisa apurar porque o material não responde (inclua pedir edital ou matrícula \
se não foram anexados).
9. Dados pessoais aparecem como [CPF] e [RG]; não tente recuperá-los.

Escreva em português do Brasil, em frases curtas e diretas."""


def _tem_credencial() -> bool:
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    return os.path.isdir(os.path.expanduser("~/.config/anthropic"))   # perfil do `ant auth login`


class AnalisadorClaude:
    def __init__(self, cliente=None, esforco: str = "high", modelo: str = MODELO, modelo_edital: str = MODELO_EDITAL,
                 modelo_transcricao: str = MODELO_TRANSCRICAO, esforco_edital: str = "medium"):
        self._cliente = cliente          # trocável nos testes
        self.esforco, self.esforco_edital = esforco, esforco_edital
        self.modelo, self.modelo_edital, self.modelo_transcricao = modelo, modelo_edital, modelo_transcricao

    def disponivel(self) -> Optional[str]:
        if self._cliente is not None:
            return None
        if anthropic is None:
            return "o pacote anthropic não está instalado (rode: .venv/bin/python -m pip install -r requirements.txt)"
        if not _tem_credencial():
            return "falta a credencial da Anthropic neste computador (defina ANTHROPIC_API_KEY ou rode ant auth login)"
        return None

    def _chamar(self, modelo: str, sistema: str, conteudo, esquema: dict, esforco: str, max_tokens: int,
                o_que: str) -> tuple:
        """Uma chamada com saída JSON validada pelo esquema. Devolve (objeto, uso)."""
        motivo = self.disponivel()
        if motivo:
            raise ErroDeAnalise(motivo)
        cliente = self._cliente or anthropic.Anthropic()
        extra = {} if "haiku" in modelo else {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        try:
            with cliente.beta.messages.stream(           # streaming: respostas longas sem estourar o tempo
                model=modelo, max_tokens=max_tokens, system=sistema,
                output_config={"effort": esforco, "format": {"type": "json_schema", "schema": esquema}},
                messages=[{"role": "user", "content": conteudo}], **extra,
            ) as fluxo:
                resp = fluxo.get_final_message()
        except Exception as e:                    # erros do SDK viram mensagem clara para a tela
            if anthropic is not None:
                if isinstance(e, anthropic.AuthenticationError):
                    raise ErroDeAnalise("a credencial da Anthropic foi recusada (confira ANTHROPIC_API_KEY)")
                if isinstance(e, anthropic.RateLimitError):
                    raise ErroDeAnalise("limite de uso da API atingido; tente de novo em alguns minutos")
                if isinstance(e, anthropic.APIConnectionError):
                    raise ErroDeAnalise("sem conexão com a API da Anthropic")
                if isinstance(e, anthropic.APIStatusError):
                    raise ErroDeAnalise(f"a API respondeu {e.status_code}: {getattr(e, 'message', e)}")
            raise
        if resp.stop_reason == "refusal":
            raise ErroDeAnalise(f"a IA não quis {o_que}")
        if resp.stop_reason == "max_tokens":
            raise ErroDeAnalise(f"a resposta ficou longa demais ao {o_que}; tente de novo")
        texto = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            obj = json.loads(texto)
        except ValueError:
            raise ErroDeAnalise(f"a IA devolveu um formato inválido ao {o_que}")
        u = resp.usage
        entrada, saida = getattr(u, "input_tokens", 0) or 0, getattr(u, "output_tokens", 0) or 0
        usado = getattr(resp, "model", modelo) or modelo
        return obj, {"entrada": entrada, "saida": saida, "custo_usd": custo_usd(modelo, entrada, saida),
                     "modelo_resposta": usado}

    def analisar(self, contexto: str) -> dict:
        parecer, uso = self._chamar(self.modelo, INSTRUCOES, contexto, ESQUEMA_PARECER, self.esforco, 32000,
                                    "analisar este material")
        return {"parecer": parecer, "uso": uso}

    def extrair_regras_edital(self, contexto: str) -> dict:
        regras, uso = self._chamar(self.modelo_edital, INSTRUCOES_EDITAL, contexto, ESQUEMA_REGRAS_EDITAL,
                                   self.esforco_edital, 32000, "ler este edital")
        return {"regras": regras, "uso": uso}

    def transcrever_pdf(self, dados: bytes) -> dict:
        import base64
        conteudo = [{"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                    "data": base64.standard_b64encode(dados).decode("ascii")}},
                    {"type": "text", "text": "Transcreva o documento acima, página por página."}]
        obj, uso = self._chamar(self.modelo_transcricao, INSTRUCOES_TRANSCRICAO, conteudo, ESQUEMA_TRANSCRICAO,
                                "low", 64000, "transcrever este documento")
        try:
            paginas = sorted(obj["paginas"], key=lambda p: p["numero"])
        except (KeyError, TypeError):
            raise ErroDeAnalise("a IA devolveu a transcrição em formato inválido")
        return {"paginas": [p["texto"] for p in paginas], "uso": uso}


INSTRUCOES_TRANSCRICAO = """Transcreva fielmente o texto de cada página deste documento (matrícula de imóvel, edital \
de leilão ou laudo). Copie exatamente como está escrito: números, datas, valores, nomes, siglas e a numeração dos \
registros e averbações (R.1, AV.2...). Não resuma, não corrija e não interprete. Mantenha a ordem do texto. \
Onde algo não puder ser lido, escreva [ilegível]. Carimbos e anotações à mão: transcreva se legíveis, entre colchetes. \
Devolva uma entrada por página, na ordem do documento."""

ESQUEMA_TRANSCRICAO = {
    "type": "object",
    "properties": {"paginas": {"type": "array", "items": {
        "type": "object",
        "properties": {"numero": {"type": "integer"}, "texto": {"type": "string"}},
        "required": ["numero", "texto"], "additionalProperties": False}}},
    "required": ["paginas"],
    "additionalProperties": False,
}



INSTRUCOES_EDITAL = """Você lê o edital de um leilão de imóveis no Brasil para um analista de risco. O mesmo edital vale \
para muitos imóveis; extraia as REGRAS GERAIS que valem para todos eles (não trate de um imóvel específico).

Para cada tema, diga em uma ou duas frases o que o edital determina e cite o trecho:
condominio (quem paga débitos de condomínio), iptu (quem paga tributos e débitos de IPTU), desocupacao (quem desocupa \
e com que custo; estado de ocupação), estado_do_imovel (vistoria, vícios, venda no estado em que se encontra), \
venda_ad_corpus (venda ad corpus, diferenças de área), onus_e_acoes (ônus, gravames, ações judiciais, quem cancela), \
comissao (comissão do leiloeiro), pagamento (formas, prazos, sinal), fgts_financiamento (uso de FGTS e financiamento), \
prazos (escritura, registro, posse), direito_de_preferencia (ex-mutuário ou outros), desistencia_e_penalidades, outros.

Regras:
1. Use só o texto recebido. Não use conhecimento externo.
2. Cada regra precisa de citação: documento EDITAL, página e trecho copiado literalmente (até 300 caracteres).
3. Se o edital não trata de um tema, não invente: deixe o tema de fora.
4. Escreva em português do Brasil, em frases curtas e diretas."""
