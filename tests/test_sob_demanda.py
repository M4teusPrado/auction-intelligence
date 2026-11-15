"""Download sob demanda (imóvel em 'Para analisar'), inclusive a matrícula da Caixa. Sem rede."""
import os, sys, tempfile, unittest, urllib.error
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from captacao.adaptadores.fontes.caixa import FonteCaixa
from captacao.adaptadores.persistencia.sqlite import RepositorioSQLite
from captacao.adaptadores.web import ClienteWeb
from captacao.aplicacao import ficha, triagem
from captacao.aplicacao.portas import ErroDeFonte
from captacao.dominio.modelo import ImovelCaptado

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


if __name__ == "__main__":
    unittest.main()
