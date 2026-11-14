import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from captacao import repositorio
from captacao.fontes import caixa
from captacao.normaliza import numero_br, chave_endereco

AQUI = os.path.dirname(__file__)


def ler():
    with open(os.path.join(AQUI, "exemplo_caixa.csv"), "rb") as f:
        return caixa.interpretar(caixa.decodificar(f.read()))


class Normaliza(unittest.TestCase):
    def test_numero(self):
        self.assertEqual(numero_br("1.234.567,89"), 1234567.89)
        self.assertEqual(numero_br("150000.00"), 150000.0)
        self.assertEqual(numero_br("R$ 90.000,00"), 90000.0)
        self.assertIsNone(numero_br(""))

    def test_endereco(self):
        self.assertEqual(chave_endereco("SP", "Campinas", "RUA DAS FLORES, N. 100"),
                         chave_endereco("sp", "CAMPINAS", "R DAS FLORES, 100"))


class Caixa(unittest.TestCase):
    def test_interpreta(self):
        ims, avisos = ler()
        self.assertEqual(len(ims), 3)
        self.assertEqual(len(avisos), 1)
        a = ims[0]
        self.assertEqual((a.id_fonte, a.cidade, a.preco, a.valor_avaliacao, a.desconto_pct),
                         ("1111111111111", "CAMPINAS", 150000.0, 200000.0, 25.0))
        self.assertEqual((a.tipo, a.area_privativa, a.area_terreno, a.data_fonte),
                         ("casa", 80.5, 250.0, "14/11/2026"))
        self.assertIsNone(ims[1].area_terreno)
        self.assertEqual(ims[2].tipo, "terreno")

    def test_cabecalho_invalido(self):
        with self.assertRaises(caixa.FormatoInesperado):
            caixa.interpretar("a;b;c\n1;2;3\n")


class Base(unittest.TestCase):
    def test_ciclo(self):
        con = repositorio.conectar(":memory:")
        ims, _ = ler()
        r1 = repositorio.gravar_coleta(con, "caixa", "SP", "teste", ims)
        self.assertEqual((r1["novos"], r1["alterados"], r1["saidos"]), (3, 0, 0))
        # segunda coleta: preço do 1º muda, 2º some
        ims2, _ = ler(); ims2[0].preco = 140000.0; del ims2[1]
        r2 = repositorio.gravar_coleta(con, "caixa", "SP", "teste", ims2)
        self.assertEqual((r2["novos"], r2["alterados"], r2["saidos"]), (0, 1, 1))
        h = con.execute("SELECT campo, valor_antigo, valor_novo FROM historico WHERE evento='alterado'").fetchone()
        self.assertEqual(tuple(h), ("preco", "150000.0", "140000.0"))
        # terceira: o 2º volta; coleta vazia não derruba nada
        ims3, _ = ler()
        r3 = repositorio.gravar_coleta(con, "caixa", "SP", "teste", ims3)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM historico WHERE evento='voltou'").fetchone()[0], 1)
        r4 = repositorio.gravar_coleta(con, "caixa", "SP", "teste", [])
        self.assertEqual(r4["saidos"], 0)
        self.assertEqual(len(repositorio.possiveis_duplicados(con)), 1)


if __name__ == "__main__":
    unittest.main()
