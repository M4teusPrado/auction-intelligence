"""Parecer preliminar com IA: máscara de dados, conferência de citações, caso de uso e adaptador (sem rede)."""
import json, os, sys, unittest
from types import SimpleNamespace
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from captacao.adaptadores.ia.claude import AnalisadorClaude, ESQUEMA_PARECER, MODELO
from captacao.aplicacao import ficha
from captacao.aplicacao.parecer import gerar_parecer, montar_contexto
from captacao.aplicacao.portas import ErroDeAnalise
from captacao.dominio.parecer import conferir, mascarar_dados_pessoais, trecho_existe
from test_triagem import base_teste

EDITAL = ["EDITAL DE LEILÃO. O imóvel encontra-se OCUPADO, cabendo ao arrematante a desocupação.",
          "Os débitos de condomínio até a data do leilão, no valor de R$ 12.345,67, serão pagos pelo vendedor."]
MATRICULA = ["R.4 PENHORA em favor de Banco X, devedor Fulano de Tal, CPF 123.456.789-09, RG nº 12.345.678-9.",
             "AV.5 Cancelamento da penhora objeto do R.4."]


def parecer_exemplo(doc_edital, doc_mat):
    fato = lambda a, d, p, t: {"afirmacao": a, "documento": d, "pagina": p, "trecho": t}
    return {"resumo_geral": "Imóvel ocupado; condomínio pago pelo vendedor.",
            "itens": [
                {"item": "ocupacao", "situacao_sugerida": "atencao", "resumo": "Ocupado; desocupação pelo arrematante.",
                 "fatos": [fato("Está ocupado", doc_edital, 1, "O imóvel encontra-se OCUPADO, cabendo ao arrematante a desocupação")]},
                {"item": "condominio", "situacao_sugerida": "ok", "resumo": "Débitos pagos pelo vendedor.",
                 "fatos": [fato("Valor", doc_edital, 1, "débitos de condomínio até a data do leilão, no valor de R$ 12.345,67")]},  # página errada
                {"item": "matricula", "situacao_sugerida": "atencao", "resumo": "Penhora cancelada.",
                 "fatos": [fato("Penhora", doc_mat, 1, "R.4 PENHORA em favor de Banco X"),
                           fato("Inventado", doc_mat, 2, "AV.6 indisponibilidade de bens decretada")]},           # não existe
                {"item": "xpto", "situacao_sugerida": "ok", "resumo": "item inválido", "fatos": []}],
            "riscos": [{"titulo": "Desocupação", "nivel": "alto", "explicacao": "Custo e prazo com o comprador.",
                        "citacoes": [fato("x", doc_edital, 1, "cabendo ao arrematante a desocupação")]}],
            "perguntas": ["Qual o valor mensal do condomínio?"]}


class Dominio(unittest.TestCase):
    def test_mascara_cpf_e_rg_e_mantem_nomes(self):
        t = mascarar_dados_pessoais(MATRICULA[0] + " Outro CPF 98765432100 e R.G. 11.222.333-X.")
        self.assertNotIn("123.456.789-09", t); self.assertNotIn("98765432100", t); self.assertNotIn("12.345.678-9", t)
        self.assertNotIn("11.222.333-X", t)
        self.assertIn("Fulano de Tal", t); self.assertIn("[CPF]", t); self.assertIn("RG nº [RG]", t)
        self.assertIn("R$ 12.345,67", mascarar_dados_pessoais(EDITAL[1]))          # dinheiro não é CPF

    def test_trecho_existe(self):
        self.assertTrue(trecho_existe("o imovel encontra-se ocupado", EDITAL[0]))       # sem acento e caixa
        self.assertTrue(trecho_existe("O imóvel encontra-se OCUPADO ... arrematante a desocupação", EDITAL[0]))
        self.assertFalse(trecho_existe("o imóvel está desocupado", EDITAL[0]))
        self.assertFalse(trecho_existe("OCUPADO", EDITAL[0]))                           # curto demais para confirmar

    def test_conferir(self):
        p = conferir(parecer_exemplo("A1", "A2"), {"A1": EDITAL, "A2": MATRICULA})
        self.assertEqual([i["item"] for i in p["itens"]], ["ocupacao", "condominio", "matricula"])   # inválido sai
        cond = p["itens"][1]["fatos"][0]
        self.assertEqual((cond["confirmada"], cond["pagina"]), (True, 2))                # página corrigida
        self.assertEqual([f["confirmada"] for f in p["itens"][2]["fatos"]], [True, False])
        self.assertEqual((p["citacoes_total"], p["citacoes_confirmadas"]), (5, 4))


class AnalisadorFalso:
    modelo = "falso"

    def __init__(self, motivo=None):
        self.motivo, self.contextos = motivo, []

    def disponivel(self):
        return self.motivo

    def analisar(self, contexto):
        self.contextos.append(contexto)
        codigos = [l.split("=")[0].strip() for l in contexto.split("DOCUMENTOS DISPONÍVEIS: ")[1].split("\n")[0].split(";")]
        return {"parecer": parecer_exemplo(codigos[1], codigos[2]), "uso": {"entrada": 1000, "saida": 200, "custo_usd": 0.008}}


class CasoDeUso(unittest.TestCase):
    def setUp(self):
        self.repo = base_teste(); self.addCleanup(self.repo.close)
        self.iid = self.repo.con.execute("SELECT id FROM imoveis LIMIT 1").fetchone()[0]
        for nome, paginas in (("edital.pdf", EDITAL), ("matricula.pdf", MATRICULA)):
            aid = self.repo.inserir_anexo(self.iid, "edital" if "edital" in nome else "matricula", nome, nome, 10, nome, "t")
            self.repo.gravar_leitura(aid, "lido", paginas)

    def test_gera_confere_e_guarda(self):
        a = AnalisadorFalso()
        r = gerar_parecer(self.repo, a, self.iid, agora="2026-11-15T10:00:00")
        ctx = a.contextos[0]
        self.assertNotIn("123.456.789-09", ctx); self.assertIn("[CPF]", ctx)              # nada de CPF enviado
        self.assertIn("página 2 ===", ctx); self.assertIn("edital.pdf", ctx)
        self.assertEqual((r["parecer"]["citacoes_total"], r["parecer"]["citacoes_confirmadas"]), (5, 4))
        f = ficha.ficha(self.repo, self.iid, analisador=a)
        self.assertEqual(f["parecer"]["quando"], "2026-11-15T10:00:00")
        self.assertTrue(f["ia"]["disponivel"])
        self.assertEqual(f["investigacao"][0]["status"], "pendente")                       # nada marcado sozinho

    def test_indisponivel(self):
        for a in (None, AnalisadorFalso("sem credencial")):
            with self.assertRaises(ErroDeAnalise):
                gerar_parecer(self.repo, a, self.iid)
        self.assertFalse(ficha.ficha(self.repo, self.iid, analisador=AnalisadorFalso("sem credencial"))["ia"]["disponivel"])
        self.assertIsNone(self.repo.ultimo_parecer(self.iid))

    def test_sem_documentos_usa_descricao(self):
        outro = self.repo.con.execute("SELECT id FROM imoveis ORDER BY id DESC LIMIT 1").fetchone()[0]
        ctx, fontes, docs = montar_contexto(self.repo, outro)
        self.assertEqual([d["codigo"] for d in docs], ["DESCRICAO"])
        self.assertIn("ainda não foram anexados", ctx)


class Adaptador(unittest.TestCase):
    def cliente(self, stop="end_turn", texto=None):
        self.chamadas = []
        resp = SimpleNamespace(stop_reason=stop, model=MODELO,
                               content=[SimpleNamespace(type="text", text=texto if texto is not None else json.dumps(parecer_exemplo("A1", "A2")))],
                               usage=SimpleNamespace(input_tokens=20000, output_tokens=3000))
        def create(**kw):
            self.chamadas.append(kw); return resp
        return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))

    def test_envia_formato_e_calcula_custo(self):
        r = AnalisadorClaude(cliente=self.cliente()).analisar("material")
        kw = self.chamadas[0]
        self.assertEqual((kw["model"], kw["fallbacks"], kw["output_config"]["format"]["schema"]), (MODELO, "default", ESQUEMA_PARECER))
        self.assertIn("server-side-fallback-2026-07-01", kw["betas"])
        self.assertEqual(kw["messages"], [{"role": "user", "content": "material"}])
        self.assertIn("Use só o que está escrito", kw["system"])
        self.assertEqual(r["uso"]["custo_usd"], 0.14)                                     # 20k x $4/M + 3k x $20/M
        self.assertEqual(r["parecer"]["itens"][0]["item"], "ocupacao")

    def test_recusa_corte_e_json_invalido(self):
        for stop, texto in (("refusal", None), ("max_tokens", None), ("end_turn", "{não é json")):
            with self.subTest(stop=stop), self.assertRaises(ErroDeAnalise):
                AnalisadorClaude(cliente=self.cliente(stop, texto)).analisar("x")


if __name__ == "__main__":
    unittest.main()
