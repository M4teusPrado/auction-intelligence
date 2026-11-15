import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from captacao.dominio import classifica
from captacao.adaptadores.persistencia import sqlite as repositorio
from captacao.adaptadores.fontes import caixa
from captacao.dominio.modelo import ImovelCaptado
from captacao.dominio.normaliza import numero_br, chave_endereco

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
        self.assertEqual(a.area_total, None)          # "0.00 de área total" vira vazio
        self.assertIsNone(ims[1].area_terreno)
        self.assertEqual(ims[2].tipo, "terreno")

    def test_cabecalho_invalido(self):
        with self.assertRaises(caixa.FormatoInesperado):
            caixa.interpretar("a;b;c\n1;2;3\n")


class Base(unittest.TestCase):
    def test_ciclo(self):
        con = repositorio.conectar(":memory:")
        ims, _ = ler()
        r1 = repositorio._gravar_coleta(con, "caixa", "SP", "teste", ims)
        self.assertEqual((r1["novos"], r1["alterados"], r1["saidos"]), (3, 0, 0))
        # segunda coleta: preço do 1º muda, 2º some
        ims2, _ = ler(); ims2[0].preco = 140000.0; del ims2[1]
        r2 = repositorio._gravar_coleta(con, "caixa", "SP", "teste", ims2)
        self.assertEqual((r2["novos"], r2["alterados"], r2["saidos"]), (0, 1, 1))
        h = con.execute("SELECT campo, valor_antigo, valor_novo FROM historico WHERE evento='alterado'").fetchone()
        self.assertEqual(tuple(h), ("preco", "150000.0", "140000.0"))
        # terceira: o 2º volta; coleta vazia não derruba nada
        ims3, _ = ler()
        r3 = repositorio._gravar_coleta(con, "caixa", "SP", "teste", ims3)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM historico WHERE evento='voltou'").fetchone()[0], 1)
        r4 = repositorio._gravar_coleta(con, "caixa", "SP", "teste", [])
        self.assertEqual(r4["saidos"], 0)
        self.assertEqual(len(repositorio._possiveis_duplicados(con)), 1)


class AreaTotal(unittest.TestCase):
    def test_extrai_area_total(self):
        d = "Terreno, 45.00 de área total, 0.00 de área privativa, 160.00 de área do terreno,  1 qto(s)"
        self.assertEqual(caixa.tipo_e_areas(d), ("terreno", None, 160.0, 45.0))

    def test_migra_base_antiga(self):
        import sqlite3, tempfile, glob
        pasta = tempfile.mkdtemp()
        caminho = os.path.join(pasta, "antiga.db")
        velha = sqlite3.connect(caminho)       # esquema da primeira versão, sem area_total
        velha.executescript(repositorio.ESQUEMA.replace(" area_total REAL,", ""))
        velha.execute("INSERT INTO imoveis (fonte, id_fonte, primeira_vez, ultima_vez) "
                      "VALUES ('caixa', '1', 'x', 'x')")
        velha.commit(); velha.close()
        con = repositorio.conectar(caminho)
        cols = {r["name"] for r in con.execute("PRAGMA table_info(imoveis)")}
        self.assertIn("area_total", cols)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM imoveis").fetchone()[0], 1)
        self.assertEqual(len(glob.glob(caminho + ".antes_migracao_*")), 1)
        con.close()
        repositorio.conectar(caminho).close()  # segunda abertura não migra nem copia de novo
        self.assertEqual(len(glob.glob(caminho + ".antes_migracao_*")), 1)

    def test_migra_tabela_triagens(self):
        import sqlite3, tempfile, glob
        caminho = os.path.join(tempfile.mkdtemp(), "sem_triagens.db")
        con = repositorio.conectar(caminho); con.execute("DROP TABLE triagens"); con.commit(); con.close()
        con = repositorio.conectar(caminho)
        nomes = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("triagens", nomes)
        self.assertEqual(len(glob.glob(caminho + ".antes_migracao_*")), 1)

    def test_base_nova_nao_gera_copia(self):
        import tempfile, glob
        caminho = os.path.join(tempfile.mkdtemp(), "nova.db")
        repositorio.conectar(caminho).close()
        self.assertEqual(glob.glob(caminho + ".antes_migracao_*"), [])


class Categoria(unittest.TestCase):
    def test_mapa(self):
        for tipo, cat in [("sobrado", "casa"), ("gleba urbana", "terreno"), ("galpao", "comercial"),
                          ("predio", "comercial"), ("imovel rural", "rural"),
                          ("apartamento", "apartamento"), ("chacara", "outros"), ("", "outros")]:
            self.assertEqual(classifica.categoria(tipo), cat, tipo)

    def test_tipo_novo_gera_aviso_e_mantem_tipo(self):
        ims, _ = ler()
        ims[0].tipo = "chacara"; ims[1].tipo = "chacara"
        avisos = classifica.classificar(ims)
        self.assertEqual(len(avisos), 1)
        self.assertIn("chacara", avisos[0]); self.assertIn("2 imóveis", avisos[0])
        self.assertEqual((ims[0].tipo, ims[0].categoria), ("chacara", "outros"))
        self.assertEqual(ims[2].categoria, "terreno")

    def test_grava_categoria(self):
        con = repositorio.conectar(":memory:")
        ims, _ = ler(); classifica.classificar(ims)
        repositorio._gravar_coleta(con, "caixa", "SP", "teste", ims)
        self.assertEqual([r[0] for r in con.execute("SELECT categoria FROM imoveis ORDER BY id")],
                         ["casa", "apartamento", "terreno"])


class Alertas(unittest.TestCase):
    def im(self, **k):
        base = dict(fonte="caixa", id_fonte="1", uf="SP", cidade="X", bairro="", endereco="",
                    preco=100.0, valor_avaliacao=None, desconto_pct=None, modalidade="",
                    tipo="casa", area_privativa=50.0, area_terreno=100.0, area_total=None,
                    descricao="", link="", data_fonte="")
        base.update(k)
        return ImovelCaptado(**base)

    def test_sem_alerta(self):
        self.assertEqual(classifica.alertas(self.im()), "")

    def test_area_terreno_suspeita(self):
        self.assertEqual(classifica.alertas(self.im(area_terreno=1.0)), "area_terreno_suspeita")
        self.assertEqual(classifica.alertas(self.im(area_terreno=0.01)), "area_terreno_suspeita")
        self.assertEqual(classifica.alertas(self.im(area_terreno=1.5)), "")

    def test_terreno_com_construcao(self):
        t = dict(tipo="terreno", area_privativa=None)
        self.assertEqual(classifica.alertas(self.im(**t)), "")
        self.assertEqual(classifica.alertas(self.im(area_total=45.0, **t)), "terreno_com_construcao")
        self.assertEqual(classifica.alertas(self.im(descricao="Terreno, ..., 1 qto(s)", **t)),
                         "terreno_com_construcao")
        self.assertEqual(classifica.alertas(self.im(tipo="gleba", area_privativa=None, area_total=5.0)),
                         "terreno_com_construcao")
        # casa com área total não é alerta
        self.assertEqual(classifica.alertas(self.im(area_total=80.0, descricao="2 qto(s)")), "")

    def test_sem_area_e_preco_ausente(self):
        self.assertEqual(classifica.alertas(self.im(area_privativa=None, area_terreno=None, preco=None)),
                         "sem_area,preco_ausente")

    def test_valor_da_fonte_nao_muda(self):
        im = self.im(area_terreno=1.0)
        classifica.classificar([im])
        self.assertEqual((im.area_terreno, im.alertas), (1.0, "area_terreno_suspeita"))

    def test_listar_sem_alertas(self):
        import io, contextlib, tempfile
        caminho = os.path.join(tempfile.mkdtemp(), "b.db")
        con = repositorio.conectar(caminho)
        ims, _ = ler(); ims[0].area_terreno = 1.0; classifica.classificar(ims)
        repositorio._gravar_coleta(con, "caixa", "SP", "teste", ims); con.close()
        from captacao import cli
        def rodar(*args):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                cli.main(["--base", caminho, "listar", *args])
            return out.getvalue()
        tudo = rodar()
        self.assertRegex(tudo, r"(?m)^!\s+1111111111111 ")
        self.assertIn("alertas: area_terreno_suspeita", tudo)
        self.assertNotIn("1111111111111", rodar("--sem-alertas"))
        self.assertIn("1 imóveis", rodar("--categoria", "terreno"))


if __name__ == "__main__":
    unittest.main()
