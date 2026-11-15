import json, os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from captacao.aplicacao import ficha
from captacao.dominio.analise import ITENS_INVESTIGACAO
from captacao.aplicacao.portas import EntradaInvalida, NaoEncontrado
from test_triagem import base_teste

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20


class Ficha(unittest.TestCase):
    def setUp(self):
        self.con = base_teste(); self.addCleanup(self.con.close)
        self.id = self.con.con.execute("SELECT id FROM imoveis ORDER BY id LIMIT 1").fetchone()[0]
        self.pasta = tempfile.mkdtemp()

    def test_ficha_completa(self):
        f = ficha.ficha(self.con, self.id)
        self.assertEqual(f["imovel"]["id"], self.id)
        self.assertEqual([h["evento"] for h in f["historico"]], ["novo"])
        self.assertEqual(len(f["investigacao"]), len(ITENS_INVESTIGACAO))
        self.assertTrue(all(i["status"] == "pendente" for i in f["investigacao"]))
        self.assertEqual(f["premissas_padrao"]["lance"], f["imovel"]["preco"])
        self.assertIsNone(f["premissas_padrao"]["valor_venda"])
        self.assertIsNone(f["simulacao_salva"])
        with self.assertRaises(NaoEncontrado):
            ficha.ficha(self.con, 999999)

    def test_investigacao_guarda_historico(self):
        ficha.investigar(self.con, self.id, {"item": "ocupacao", "status": "atencao", "nota": " ocupado "})
        r = ficha.investigar(self.con, self.id, {"item": "ocupacao", "status": "ok", "nota": "desocupou"})
        oc = next(i for i in r["investigacao"] if i["item"] == "ocupacao")
        self.assertEqual((oc["status"], oc["nota"]), ("ok", "desocupou"))
        self.assertEqual(self.con.con.execute("SELECT COUNT(*) FROM investigacao").fetchone()[0], 2)
        for corpo in ({"item": "x", "status": "ok"}, {"item": "ocupacao", "status": "talvez"},
                      {"item": "ocupacao", "status": "ok", "nota": 3}, {"item": "ocupacao", "status": "ok", "y": 1},
                      {"item": "ocupacao", "status": "ok", "nota": "x" * 2001}, []):
            with self.subTest(corpo=corpo), self.assertRaises(EntradaInvalida):
                ficha.investigar(self.con, self.id, corpo)

    def test_anexo(self):
        r = ficha.anexar(self.con, self.pasta, self.id, "matricula", "../../etc/Matrícula 123.pdf", PDF)
        self.assertFalse(r["duplicado"])
        a = r["anexos"][0]
        self.assertEqual((a["tipo"], a["nome_original"], a["tamanho"]), ("matricula", "Matrícula 123.pdf", len(PDF)))
        caminho, nome, mime = ficha.arquivo_anexo(self.con, self.pasta, a["id"])
        self.assertTrue(caminho.startswith(os.path.realpath(self.pasta)))
        self.assertEqual(mime, "application/pdf")
        with open(caminho, "rb") as f:
            self.assertEqual(f.read(), PDF)
        self.assertTrue(ficha.anexar(self.con, self.pasta, self.id, "edital", "outro.pdf", PDF)["duplicado"])
        self.assertEqual(len(ficha.anexar(self.con, self.pasta, self.id, "foto", "f.png", PNG)["anexos"]), 2)

    def test_anexo_invalido(self):
        for tipo, dados in (("matricula", b""), ("matricula", b"<html>"), ("xpto", PDF),
                            ("matricula", b"MZ\x90\x00")):
            with self.subTest(tipo=tipo, dados=dados[:6]), self.assertRaises(EntradaInvalida):
                ficha.anexar(self.con, self.pasta, self.id, tipo, "a.pdf", dados)
        with self.assertRaises(NaoEncontrado):
            ficha.arquivo_anexo(self.con, self.pasta, 12345)

    def test_simulacao_salva_e_reabre(self):
        p = {"lance": 100000, "valor_venda": 150000}
        r = ficha.salvar_simulacao(self.con, self.id, {"premissas": p})
        self.assertIsNotNone(r["resultado"]["venda"])
        salva = ficha.ficha(self.con, self.id)["simulacao_salva"]
        self.assertEqual((salva["premissas"]["lance"], salva["premissas"]["itbi_pct"]), (100000.0, 3.0))
        with self.assertRaises(EntradaInvalida):
            ficha.salvar_simulacao(self.con, self.id, {"premissas": {"lance": -5}})
        with self.assertRaises(EntradaInvalida):
            ficha.simular({"outra": 1})
        self.assertEqual(self.con.con.execute("SELECT COUNT(*) FROM simulacoes").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
