"""Parecer preliminar com IA: máscara de dados, conferência de citações, caso de uso e adaptador (sem rede)."""
import json, os, sys, unittest
from types import SimpleNamespace
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from captacao.adaptadores.ia.claude import AnalisadorClaude, ESQUEMA_PARECER, MODELO
from captacao.aplicacao import ficha
from captacao.adaptadores.persistencia.sqlite import RepositorioSQLite
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
        self.assertIn("=== DOCUMENTO DESCRICAO, página 1 ===\nCasa", ctx)          # a descrição vai junto, com texto


def cliente_falso(resp, chamadas):
    """Imita client.beta.messages.stream(...) com get_final_message()."""
    class Fluxo:
        def __enter__(s): return s
        def __exit__(s, *a): pass
        def get_final_message(s): return resp
    def stream(**kw):
        chamadas.append(kw); return Fluxo()
    return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=stream)))


class Adaptador(unittest.TestCase):
    def cliente(self, stop="end_turn", texto=None):
        self.chamadas = []
        resp = SimpleNamespace(stop_reason=stop, model=MODELO,
                               content=[SimpleNamespace(type="text", text=texto if texto is not None else json.dumps(parecer_exemplo("A1", "A2")))],
                               usage=SimpleNamespace(input_tokens=20000, output_tokens=3000))
        return cliente_falso(resp, self.chamadas)

    def test_envia_formato_e_calcula_custo(self):
        r = AnalisadorClaude(cliente=self.cliente()).analisar("material")
        kw = self.chamadas[0]
        self.assertEqual((kw["model"], kw["fallbacks"], kw["output_config"]["format"]["schema"]), (MODELO, "default", ESQUEMA_PARECER))
        self.assertIn("server-side-fallback-2026-07-01", kw["betas"])
        self.assertEqual(kw["messages"], [{"role": "user", "content": "material"}])
        self.assertIn("Use só o que está escrito", kw["system"])
        self.assertEqual(r["uso"]["custo_usd"], 0.07)                                     # Sonnet: 20k x $2/M + 3k x $10/M
        self.assertEqual(r["parecer"]["itens"][0]["item"], "ocupacao")

    def test_recusa_corte_e_json_invalido(self):
        for stop, texto in (("refusal", None), ("max_tokens", None), ("end_turn", "{não é json")):
            with self.subTest(stop=stop), self.assertRaises(ErroDeAnalise):
                AnalisadorClaude(cliente=self.cliente(stop, texto)).analisar("x")


class TranscritorFalso:
    modelo = "falso"

    def __init__(self):
        self.recebidos = []

    def disponivel(self):
        return None

    def transcrever_pdf(self, dados):
        self.recebidos.append(dados)
        return {"paginas": MATRICULA, "uso": {"entrada": 3000, "saida": 800, "custo_usd": 0.028}}


class Transcricao(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.repo = base_teste(); self.addCleanup(self.repo.close)
        self.iid = self.repo.con.execute("SELECT id FROM imoveis LIMIT 1").fetchone()[0]
        self.pasta = tempfile.mkdtemp()
        r = ficha.anexar(self.repo, self.pasta, self.iid, "matricula", "matricula-scan.pdf", b"%PDF-1.4\n%%EOF\n")
        self.aid = r["anexos"][0]["id"]

    def test_transcreve_escaneado_e_mascara(self):
        self.assertIn(self.repo.anexos(self.iid)[0]["leitura"], ("sem_texto", "erro", "desligada"))
        t = TranscritorFalso()
        r = ficha.transcrever_anexo(self.repo, self.pasta, t, self.aid)
        self.assertEqual(t.recebidos, [b"%PDF-1.4\n%%EOF\n"])                         # o PDF original vai para a IA
        self.assertEqual((r["paginas"], r["anexos"][0]["leitura"]), (2, "transcrito_ia"))
        textos = self.repo.textos_lidos(self.iid)[0]
        self.assertTrue(textos["transcrito_ia"])
        self.assertNotIn("123.456.789-09", " ".join(textos["paginas"]))                # guardado mascarado
        self.assertIn("matricula", r["achados"])                                        # busca de trechos funciona
        ctx, _, docs = montar_contexto(self.repo, self.iid)
        self.assertIn("transcrição por IA", docs[1]["nome"])
        with self.assertRaises(Exception):                                             # já tem texto: não repete
            ficha.transcrever_anexo(self.repo, self.pasta, t, self.aid)

    def test_antes_do_parecer_le_os_escaneados(self):
        ctx, _, _ = montar_contexto(self.repo, self.iid)
        self.assertIn("SEM TEXTO LEGÍVEL", ctx)                                         # a IA sabe que existe, mas sem texto
        self.assertIn("matricula-scan.pdf", ctx)
        r = ficha.transcrever_pendentes(self.repo, self.pasta, TranscritorFalso(), self.iid)
        self.assertEqual((len(r["transcritos"]), r["custo_usd"], r["erros"]), (1, 0.028, []))
        ctx, _, _ = montar_contexto(self.repo, self.iid)
        self.assertNotIn("SEM TEXTO LEGÍVEL", ctx)
        self.assertEqual(ficha.transcrever_pendentes(self.repo, self.pasta, TranscritorFalso(), self.iid)["transcritos"], [])

    def test_sem_transcritor(self):
        with self.assertRaises(ErroDeAnalise):
            ficha.transcrever_anexo(self.repo, self.pasta, None, self.aid)


class AdaptadorTranscricao(unittest.TestCase):
    def test_envia_pdf_e_le_paginas(self):
        chamadas = []
        resp = SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(
            {"paginas": [{"numero": 2, "texto": "pág 2"}, {"numero": 1, "texto": "pág 1"}]}))],
            usage=SimpleNamespace(input_tokens=10000, output_tokens=2000))
        class Fluxo:
            def __enter__(s): return s
            def __exit__(s, *a): pass
            def get_final_message(s): return resp
        def stream(**kw):
            chamadas.append(kw); return Fluxo()
        cliente = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=stream)))
        r = AnalisadorClaude(cliente=cliente).transcrever_pdf(b"%PDF-teste")
        self.assertEqual(r["paginas"], ["pág 1", "pág 2"])                              # ordenado pelo número
        doc = chamadas[0]["messages"][0]["content"][0]
        self.assertEqual((doc["type"], doc["source"]["media_type"]), ("document", "application/pdf"))
        self.assertEqual(chamadas[0]["model"], "claude-haiku-5-5")                     # transcrever: modelo barato
        self.assertNotIn("fallbacks", chamadas[0])                                      # Haiku não tem fallback no servidor
        self.assertEqual(r["uso"]["custo_usd"], 0.002)                                  # 10k x $0,10/M + 2k x $0,50/M


class EditalComVariosImoveis(unittest.TestCase):
    def test_omite_paginas_so_com_outros_imoveis(self):
        from captacao.aplicacao.parecer import paginas_de_outros_imoveis
        paginas = ["19.4.1 Débitos de condomínio ficam com o adquirente.",
                   "560 RUA X 8444425522289 134.264,38 / 561 RUA Y 8444411111111 99.000,00",
                   "562 RUA Z 8787700000001 50.000,00 / 563 RUA W 8787700000002 60.000,00",
                   "Anexo: modelo de proposta"]
        self.assertEqual(paginas_de_outros_imoveis(paginas, "8444425522289"), {2})
        self.assertEqual(paginas_de_outros_imoveis(paginas, "8444425522289-x"), {2})
        self.assertEqual(paginas_de_outros_imoveis(paginas, "gabrieltorres.com.br:73187"), set())   # sem número: não omite


class RegrasDoEditalUmaVez(unittest.TestCase):
    CLAUSULA = "19.4.1 Eventuais débitos de condomínio e IPTU devem ser quitados exclusivamente pelo adquirente."

    def setUp(self):
        import tempfile
        from captacao.dominio.modelo import ImovelCaptado
        sys.path.insert(0, os.path.dirname(__file__))
        from test_documentos import pdf_com_texto
        self.repo = RepositorioSQLite(":memory:"); self.addCleanup(self.repo.close)
        base = dict(fonte="caixa", uf="SP", cidade="SOROCABA", bairro="", endereco="", preco=1.0, valor_avaliacao=1.0,
                    desconto_pct=0.0, modalidade="Leilão SFI", tipo="casa", area_privativa=None, area_terreno=None,
                    area_total=None, descricao="Casa", link="", data_fonte="", categoria="casa")
        self.repo.gravar_coleta("caixa", "SP", "t", [ImovelCaptado(id_fonte="8444425522289", **base),
                                                       ImovelCaptado(id_fonte="8787715548453", **base)])
        self.a, self.b = [r[0] for r in self.repo.con.execute("SELECT id FROM imoveis ORDER BY id_fonte")]
        enche = " | texto complementar desta pagina de teste para ter o tamanho de uma pagina real lida"
        edital = pdf_com_texto([self.CLAUSULA + enche, "560 RUA X 8444425522289 134.264,38 / 561 8444411111111 9,00" + enche,
                                "562 8787715548453 50,00 / 563 8787700000002 60,00" + enche, "564 8787700000003 1,00 / 565 8787700000004 2,00" + enche])
        pasta = tempfile.mkdtemp()
        for i in (self.a, self.b):
            ficha.anexar(self.repo, pasta, i, "edital", "edital.pdf", edital)

    class IA(AnalisadorFalso):
        modelo_edital = "falso-edital"
        def __init__(s):
            super().__init__(); s.editais, s.contextos = [], []
        def extrair_regras_edital(s, texto):
            s.editais.append(texto)
            return {"regras": {"regras": [{"tema": "condominio", "regra": "Débitos de condomínio e IPTU ficam com o comprador.",
                     "citacoes": [{"afirmacao": "x", "documento": "EDITAL", "pagina": 1, "trecho": "débitos de condomínio e IPTU devem ser quitados exclusivamente pelo adquirente"}]},
                    {"tema": "comissao", "regra": "inventada", "citacoes": [{"afirmacao": "x", "documento": "EDITAL", "pagina": 1, "trecho": "comissão de 5% sobre o valor"}]}]},
                    "uso": {"custo_usd": 0.3}}
        def analisar(s, contexto):
            s.contextos.append(contexto)
            return {"parecer": {"resumo_geral": "r", "itens": [], "riscos": [], "perguntas": []}, "uso": {"custo_usd": 0.05}}

    def test_le_uma_vez_e_envia_so_o_necessario(self):
        ia = self.IA()
        r1 = gerar_parecer(self.repo, ia, self.a)
        r2 = gerar_parecer(self.repo, ia, self.b)
        self.assertEqual(len(ia.editais), 1)                                   # 2º imóvel reaproveita as regras
        self.assertNotIn("8444411111111", ia.editais[0])                      # tabela de imóveis não vai para a leitura do edital
        self.assertEqual((r1["uso"]["custo_usd"], r1["uso"]["custo_edital_usd"], r2["uso"]["custo_usd"]), (0.35, 0.3, 0.05))
        ctx = ia.contextos[0]
        self.assertIn("Débitos de condomínio e IPTU ficam com o comprador", ctx)
        self.assertNotIn("inventada", ctx)                                    # regra com trecho não conferido fica fora
        self.assertIn("8444425522289 134.264,38", ctx)                        # a linha do imóvel vai
        self.assertNotIn("8787700000003", ctx)                                # páginas só de outros imóveis não
        self.assertNotIn(self.CLAUSULA[:20], ctx.split("REGRAS GERAIS")[0])   # cláusulas vão pelas regras, não a página inteira
        self.assertIn("8787715548453 50,00", ia.contextos[1])
        self.assertNotIn("8444425522289 134.264,38", ia.contextos[1])


if __name__ == "__main__":
    unittest.main()
