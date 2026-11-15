"""Adaptador da porta AnalisadorDeDocumentos usando o Claude (API da Anthropic).

Aprovado pelo Mateus em 15/11/2026: roda só quando a pessoa clica, CPF/RG mascarados antes
do envio (feito no caso de uso), a IA só sugere. Credencial: ANTHROPIC_API_KEY ou
`ant auth login` (o SDK encontra sozinho). Sem credencial, a tela mostra o motivo.
"""
import json
import os
from typing import Optional

from ...aplicacao.portas import ErroDeAnalise
from ...dominio.parecer import ESQUEMA_PARECER

try:
    import anthropic
except ImportError:            # SDK não instalado: análise desligada
    anthropic = None

MODELO = "claude-opus-5-5"
PRECO_POR_MILHAO = (4.0, 20.0)  # US$ entrada / saída (tabela da Anthropic, nov/2026)

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
    modelo = MODELO

    def __init__(self, cliente=None, esforco: str = "high"):
        self._cliente = cliente          # trocável nos testes
        self.esforco = esforco

    def disponivel(self) -> Optional[str]:
        if self._cliente is not None:
            return None
        if anthropic is None:
            return "o pacote anthropic não está instalado (rode: .venv/bin/python -m pip install -r requirements.txt)"
        if not _tem_credencial():
            return "falta a credencial da Anthropic neste computador (defina ANTHROPIC_API_KEY ou rode ant auth login)"
        return None

    def analisar(self, contexto: str) -> dict:
        motivo = self.disponivel()
        if motivo:
            raise ErroDeAnalise(motivo)
        cliente = self._cliente or anthropic.Anthropic()
        erros = anthropic if anthropic is not None else None
        try:
            resp = cliente.beta.messages.create(
                model=self.modelo,
                max_tokens=16000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",                  # se o modelo recusar, outro modelo continua
                output_config={"effort": self.esforco,
                               "format": {"type": "json_schema", "schema": ESQUEMA_PARECER}},
                system=INSTRUCOES,
                messages=[{"role": "user", "content": contexto}],
            )
        except Exception as e:                    # erros do SDK viram mensagem clara para a tela
            if erros is not None:
                if isinstance(e, erros.AuthenticationError):
                    raise ErroDeAnalise("a credencial da Anthropic foi recusada (confira ANTHROPIC_API_KEY)")
                if isinstance(e, erros.RateLimitError):
                    raise ErroDeAnalise("limite de uso da API atingido; tente de novo em alguns minutos")
                if isinstance(e, erros.APIConnectionError):
                    raise ErroDeAnalise("sem conexão com a API da Anthropic")
                if isinstance(e, erros.APIStatusError):
                    raise ErroDeAnalise(f"a API respondeu {e.status_code}: {getattr(e, 'message', e)}")
            raise
        if resp.stop_reason == "refusal":
            raise ErroDeAnalise("a IA não quis analisar este material")
        if resp.stop_reason == "max_tokens":
            raise ErroDeAnalise("a resposta da IA ficou longa demais e foi cortada; tente de novo")
        texto = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            parecer = json.loads(texto)
        except ValueError:
            raise ErroDeAnalise("a IA devolveu um parecer em formato inválido")
        u = resp.usage
        entrada, saida = getattr(u, "input_tokens", 0) or 0, getattr(u, "output_tokens", 0) or 0
        custo = round(entrada / 1e6 * PRECO_POR_MILHAO[0] + saida / 1e6 * PRECO_POR_MILHAO[1], 4)
        return {"parecer": parecer, "uso": {"entrada": entrada, "saida": saida, "custo_usd": custo,
                                            "modelo_resposta": getattr(resp, "model", self.modelo)}}


    def transcrever_pdf(self, dados: bytes) -> dict:
        import base64
        motivo = self.disponivel()
        if motivo:
            raise ErroDeAnalise(motivo)
        cliente = self._cliente or anthropic.Anthropic()
        conteudo = [{"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                    "data": base64.standard_b64encode(dados).decode("ascii")}},
                    {"type": "text", "text": "Transcreva o documento acima, página por página."}]
        try:
            with cliente.beta.messages.stream(               # streaming: a transcrição pode ser longa
                model=self.modelo,
                max_tokens=64000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": ESQUEMA_TRANSCRICAO}},
                system=INSTRUCOES_TRANSCRICAO,
                messages=[{"role": "user", "content": conteudo}],
            ) as fluxo:
                resp = fluxo.get_final_message()
        except Exception as e:
            if anthropic is not None:
                if isinstance(e, anthropic.AuthenticationError):
                    raise ErroDeAnalise("a credencial da Anthropic foi recusada")
                if isinstance(e, anthropic.RateLimitError):
                    raise ErroDeAnalise("limite de uso da API atingido; tente de novo em alguns minutos")
                if isinstance(e, anthropic.APIConnectionError):
                    raise ErroDeAnalise("sem conexão com a API da Anthropic")
                if isinstance(e, anthropic.APIStatusError):
                    raise ErroDeAnalise(f"a API respondeu {e.status_code}: {getattr(e, 'message', e)}")
            raise
        if resp.stop_reason == "refusal":
            raise ErroDeAnalise("a IA não quis transcrever este documento")
        if resp.stop_reason == "max_tokens":
            raise ErroDeAnalise("o documento é longo demais para transcrever de uma vez")
        texto = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            paginas = sorted(json.loads(texto)["paginas"], key=lambda p: p["numero"])
        except (ValueError, KeyError, TypeError):
            raise ErroDeAnalise("a IA devolveu a transcrição em formato inválido")
        u = resp.usage
        entrada, saida = getattr(u, "input_tokens", 0) or 0, getattr(u, "output_tokens", 0) or 0
        custo = round(entrada / 1e6 * PRECO_POR_MILHAO[0] + saida / 1e6 * PRECO_POR_MILHAO[1], 4)
        return {"paginas": [p["texto"] for p in paginas], "uso": {"entrada": entrada, "saida": saida, "custo_usd": custo}}


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

