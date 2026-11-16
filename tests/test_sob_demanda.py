"""Download sob demanda (imóvel em 'Para analisar'), inclusive a matrícula da Caixa. Sem rede."""
import os, sys, tempfile, unittest, urllib.error
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from captacao.adaptadores.fontes.caixa import FonteCaixa
from captacao.adaptadores.persistencia.sqlite import RepositorioSQLite
from captacao.adaptadores.web import ClienteWeb
from captacao.aplicacao import ficha, triagem
from captacao.aplicacao.portas import ErroDeFonte
from captacao.dominio.modelo import ImovelCaptado
from captacao.aplicacao.portas import EntradaInvalida
sys.path.insert(0, os.path.dirname(__file__))
from test_documentos import pdf_com_texto

PDF = b"%PDF-1.7\n%%EOF\n"


def imovel_caixa():
    return ImovelCaptado(fonte="caixa", id_fonte="8787715548453", uf="SP", cidade="SOROCABA", bairro="", endereco="",
                         preco=168000.0, valor_avaliacao=168000.0, desconto_pct=0.0, modalidade="Leilão SFI - Edital Único",
                         tipo="apartamento", area_privativa=45.5, area_terreno=None, area_total=50.52, descricao="Apartamento",
                         link="", data_fonte="", categoria="apartamento")


class BaixadorFalso:
    """Imita o ClienteWeb: recusa como o robots.txt recusaria, a menos que seja sob demanda."""
    def __init__(self, recusa_robots=True):
        self.pedidos, self.recusa = [], recusa_robots

    def baixar(self, url, usar_cache=True, sob_demanda=False):
        self.pedidos.append((url, sob_demanda))
        if self.recusa and not sob_demanda:
            raise ErroDeFonte("o robots.txt de x não permite acessar /y")
        return PDF


class Caixa(unittest.TestCase):
    def setUp(self):
        self.repo = RepositorioSQLite(":memory:"); self.addCleanup(self.repo.close)
        self.repo.gravar_coleta("caixa", "SP", "t", [imovel_caixa()])
        self.iid = self.repo.con.execute("SELECT id FROM imoveis").fetchone()[0]
        self.fontes = {"caixa": FonteCaixa()}

    def test_endereco_da_matricula(self):
        docs = ficha.documentos_da_fonte(self.repo.buscar_imovel(self.iid), self.fontes)
        self.assertEqual(docs, [{"tipo": "matricula", "rotulo": "Matrícula (Caixa)",
                                 "url": "https://venda-imoveis.caixa.gov.br/editais/matricula/SP/8787715548453.pdf"}])
        self.assertEqual(ficha.ficha(self.repo, self.iid, fontes=self.fontes)["documentos_fonte"], docs)

    def test_so_baixa_sob_demanda_em_para_analisar(self):
        b, pasta = BaixadorFalso(), tempfile.mkdtemp()
        r = ficha.baixar_documentos_fonte(self.repo, pasta, self.iid, b, fontes=self.fontes)
        self.assertEqual((r["baixados"], r["sob_demanda"], b.pedidos[0][1]), ([], False, False))   # fora da análise: respeita
        triagem.triar(self.repo, self.iid, {"para": "analisar"})
        self.assertTrue(ficha.documentos_pendentes(self.repo, self.iid, self.fontes))
        r = ficha.baixar_documentos_fonte(self.repo, pasta, self.iid, b, fontes=self.fontes)
        self.assertEqual(([x["tipo"] for x in r["baixados"]], r["sob_demanda"], b.pedidos[-1][1]), (["matricula"], True, True))
        self.assertEqual(r["anexos"][0]["tipo"], "matricula")
        self.assertFalse(ficha.documentos_pendentes(self.repo, self.iid, self.fontes))           # não baixa de novo


class Web(unittest.TestCase):
    def test_sob_demanda_ignora_robots_mas_mantem_ritmo(self):
        pedidos, esperas, t = [], [], [0.0]
        class Resp:
            def __init__(s, d): s.d = d
            def read(s, n=-1): return s.d
            def __enter__(s): return s
            def __exit__(s, *a): pass
        respostas = {"https://s.test/robots.txt": b"User-agent: *\nDisallow: /\n", "https://s.test/doc.pdf": PDF}
        def abrir(req, timeout):
            pedidos.append(req.full_url)
            if req.full_url not in respostas:
                raise urllib.error.HTTPError(req.full_url, 404, "x", {}, None)
            return Resp(respostas[req.full_url])
        c = ClienteWeb(abrir=abrir, dormir=lambda s: (esperas.append(s), t.__setitem__(0, t[0] + s)), relogio=lambda: t[0])
        with self.assertRaises(ErroDeFonte):
            c.baixar("https://s.test/doc.pdf")                       # varredura: robots.txt vale
        self.assertEqual(c.baixar("https://s.test/doc.pdf", sob_demanda=True), PDF)
        self.assertEqual(pedidos, ["https://s.test/robots.txt", "https://s.test/doc.pdf"])
        self.assertTrue(esperas and esperas[-1] >= 3.0)              # continua esperando entre pedidos


class EditalCaixa(unittest.TestCase):
    URL = "https://venda-imoveis.caixa.gov.br/editais/EL00610226CPARE.PDF"

    def setUp(self):
        self.repo = RepositorioSQLite(":memory:"); self.addCleanup(self.repo.close)
        outro = imovel_caixa(); outro.id_fonte = "8444425522289"
        fora = imovel_caixa(); fora.id_fonte = "1111111111111"
        self.repo.gravar_coleta("caixa", "SP", "t", [imovel_caixa(), outro, fora])
        ids = dict(self.repo.con.execute("SELECT id_fonte, id FROM imoveis").fetchall())
        self.dentro, self.analisar, self.fora = ids["8787715548453"], ids["8444425522289"], ids["1111111111111"]
        triagem.triar(self.repo, self.analisar, {"para": "analisar"})
        self.pdf = pdf_com_texto(["Edital de Leilao 0061/0226 item 1 878771554845-3 R$ 100", "item 2 8444425522289 R$ 200 9999999999999"])
        self.fontes = {"caixa": FonteCaixa()}

    def test_liga_a_todos_e_anexa_nos_em_analise(self):
        b = BaixadorFalso(recusa_robots=False)
        b.baixar = lambda url, usar_cache=True, sob_demanda=False: (b.pedidos.append(url), self.pdf if "editais/EL" in url else PDF)[1]
        r = ficha.indexar_edital_caixa(self.repo, tempfile.mkdtemp(), b, self.URL, self.fontes)
        self.assertEqual((r["edital"], r["imoveis_no_edital"], r["imoveis_na_base"]), ("Edital 0061/0226 (Caixa)", 3, 2))
        self.assertEqual(r["anexados_em_analise"], [self.analisar])
        tipos = lambda i: sorted(d["tipo"] for d in ficha.documentos_da_fonte(self.repo.buscar_imovel(i), self.fontes))
        self.assertEqual((tipos(self.dentro), tipos(self.fora)), (["edital", "matricula"], ["matricula"]))
        self.assertEqual(sorted(a["tipo"] for a in self.repo.anexos(self.analisar)), ["edital", "matricula"])
        self.assertEqual(self.repo.anexos(self.dentro), [])          # fora da análise: só fica ligado, sem baixar
        self.assertEqual(b.pedidos.count(self.URL), 2)               # 1 para indexar + 1 ao anexar (o cliente real usa cache)

    def test_so_aceita_link_de_edital_da_caixa(self):
        for url in ("https://exemplo.com/editais/EL1.PDF", "http://venda-imoveis.caixa.gov.br/editais/EL00610226CPARE.PDF",
                    "https://venda-imoveis.caixa.gov.br/sistema/detalhe-imovel.asp?hdnimovel=1"):
            with self.assertRaises(EntradaInvalida):
                ficha.indexar_edital_caixa(self.repo, tempfile.mkdtemp(), BaixadorFalso(), url, self.fontes)


class EditalPeloLeiloeiro(unittest.TestCase):
    def test_lote_do_leiloeiro_com_matricula_caixa_liga_o_edital(self):
        from captacao.dominio.modelo import DadosLeilao, DocumentoFonte
        repo = RepositorioSQLite(":memory:"); self.addCleanup(repo.close)
        repo.gravar_coleta("caixa", "SP", "t", [imovel_caixa()])
        lote = imovel_caixa(); lote.fonte, lote.id_fonte = "soleon", "3torresleiloes.com.br:73187"
        edital = "https://cdn.exemplo/leiloes/2606/edital.pdf"
        lote.leilao = DadosLeilao(comitente="Caixa", documentos=[
            DocumentoFonte(tipo="matricula", url="https://venda-imoveis.caixa.gov.br/editais/matricula/SP/8787715548453.pdf", rotulo="Matrícula"),
            DocumentoFonte(tipo="edital", url=edital, rotulo="EDITAL")])
        repo.gravar_coleta("soleon", "x", "t", [lote])
        self.assertEqual(repo.ligar_editais_de_leiloeiros(), 1)
        self.assertEqual(repo.ligar_editais_de_leiloeiros(), 0)                      # não duplica
        cid = repo.con.execute("SELECT id FROM imoveis WHERE fonte='caixa'").fetchone()[0]
        docs = ficha.documentos_da_fonte(repo.buscar_imovel(cid), {"caixa": FonteCaixa()})
        self.assertEqual(sorted((d["tipo"], d["url"]) for d in docs),
                         [("edital", edital), ("matricula", "https://venda-imoveis.caixa.gov.br/editais/matricula/SP/8787715548453.pdf")])


if __name__ == "__main__":
    unittest.main()
