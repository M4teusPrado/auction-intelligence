"""Fonte Soleon (plataforma usada por dezenas de leiloeiros), sem acessar a rede."""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from captacao.adaptadores.fontes import soleon as so
from captacao.adaptadores.persistencia.sqlite import RepositorioSQLite
from captacao.aplicacao.coletar import coletar, importar_link
from captacao.aplicacao.portas import ErroDeFonte

AQUI = os.path.join(os.path.dirname(__file__), "amostras")
URL_GL = "https://www.glleiloes.com.br/item/5126/detalhes"
URL_BEST = "https://www.bestleiloes.com.br/item/15412/detalhes"


def ler(nome):
    with open(os.path.join(AQUI, nome), "rb") as f:
        return f.read()


class ClienteFalso:
    def __init__(self, paginas):
        self.paginas, self.pedidos = paginas, []

    def baixar(self, url, usar_cache=True):
        self.pedidos.append(url)
        if url in self.paginas:
            return self.paginas[url]
        raise ErroDeFonte(f"o site respondeu 404 para {url}")


class Leitor(unittest.TestCase):
    def test_lote_judicial_duas_pracas(self):
        im = so.interpretar_lote(ler("soleon_item_judicial_encerrado_gl.html").decode(), URL_GL, "glleiloes.com.br")
        self.assertEqual((im.fonte, im.id_fonte, im.uf, im.cidade, im.tipo), ("soleon", "glleiloes.com.br:5126", "SP", "TATUI", "casa"))
        self.assertEqual((im.preco, im.valor_avaliacao, im.area_total, im.area_terreno), (214303.16, 250000.0, 148.0, 180.0))
        lei = im.leilao
        self.assertEqual((lei.tipo_venda, lei.comitente, lei.leiloeiro, lei.matricula, lei.comissao_pct, lei.incremento),
                         ("Judicial", "Tribunal de Justiça de São Paulo - TJSP", "Maurício Gomes Leiteiro", "37.672", 5.0, 2844.0))
        self.assertEqual([(p.numero, p.data, p.valor) for p in lei.pracas],
                         [(1, "2026-09-04T10:00", 285737.55), (2, "2026-09-25T10:00", 214303.16)])
        self.assertEqual(sorted(d.tipo for d in lei.documentos), ["edital", "laudo", "matricula"])

    def test_lote_de_outro_estado_e_area_do_titulo(self):
        im = so.interpretar_lote(ler("soleon_item_aberto_best.html").decode(), URL_BEST, "bestleiloes.com.br")
        self.assertEqual((im.uf, im.cidade, im.tipo, im.area_terreno), ("SC", "BLUMENAU", "terreno", 40750.0))
        self.assertIsNone(im.desconto_pct)          # lance da 1ª praça acima da avaliação: sem "desconto negativo"
        self.assertEqual(im.leilao.comitente, "Tribunal De Justiça de Santa Catarina")

    def test_lote_que_nao_e_imovel(self):
        pagina = ler("soleon_item_aberto_best.html").decode().replace(
            'content="Lote 001 - Terreno', 'content="Lote 001 - Veículo VW Gol 2015').replace("<b>Matrícula:</b>", "<b>Placa:</b>")
        self.assertIsNone(so.interpretar_lote(pagina, URL_BEST, "bestleiloes.com.br"))

    def test_pagina_de_outra_plataforma(self):
        with self.assertRaises(ErroDeFonte):
            so.interpretar_lote(ler("megaleiloes_judicial_j129393.html").decode(), URL_BEST, "bestleiloes.com.br")

    def test_cartoes_de_leilao(self):
        c = so.leiloes_da_pagina(ler("soleon_leiloes_best.html").decode())
        self.assertEqual(len(c), 40)
        abertos = [x for x in c if not x["encerrado"] and so.pode_ter_imovel(x)]
        self.assertEqual(len(abertos), 6)
        self.assertFalse(any("Veículo" in x["titulo"] for x in abertos))

    def test_aceita_url(self):
        f = so.FonteSoleon(ClienteFalso({}))
        self.assertTrue(f.aceita_url(URL_GL) and f.aceita_url("https://glleiloes.com.br/item/1/detalhes"))
        for url in ("https://www.glleiloes.com.br/leilao/1/lotes", "https://www.desconhecido.com.br/item/1/detalhes",
                    "http://www.glleiloes.com.br/item/1/detalhes"):
            self.assertFalse(f.aceita_url(url), url)


class Coleta(unittest.TestCase):
    def site(self):
        lista = ler("soleon_leiloes_best.html")
        abertos = [x["url"] for x in so.leiloes_da_pagina(lista.decode()) if not x["encerrado"] and so.pode_ter_imovel(x)]
        paginas = {"https://www.bestleiloes.com.br/leiloes?page=1": lista,
                   "https://www.bestleiloes.com.br/leiloes?page=2": lista,          # site repete a lista: deve parar
                   f"{abertos[0]}?page=1": ler("soleon_lotes_best.html"),
                   f"{abertos[0]}?page=2": ler("soleon_lotes_best.html"),
                   URL_BEST: ler("soleon_item_aberto_best.html")}
        return ClienteFalso(paginas), abertos

    def test_coleta_de_um_site(self):
        cliente, abertos = self.site()
        c = so.FonteSoleon(cliente, sites=["bestleiloes.com.br"]).coletar("bestleiloes.com.br")
        self.assertEqual([im.id_fonte for im in c.imoveis], ["bestleiloes.com.br:15412"])
        self.assertEqual(c.recorte, "bestleiloes.com.br")
        self.assertFalse(c.completa)                          # 5 leilões abertos não responderam (404 no falso)
        self.assertEqual(len([a for a in c.avisos if "404" in a]), 5)
        self.assertNotIn("https://www.bestleiloes.com.br/leiloes?page=3", cliente.pedidos)
        with RepositorioSQLite(":memory:") as repo:
            r = coletar(so.FonteSoleon(self.site()[0], sites=["bestleiloes.com.br"]), repo, "bestleiloes.com.br")
            self.assertEqual((r["novos"], r["completa"], r["saidos"]), (1, False, 0))

    def test_importar_link(self):
        cliente = ClienteFalso({URL_BEST: ler("soleon_item_aberto_best.html")})
        with RepositorioSQLite(":memory:") as repo:
            r = importar_link({"soleon": so.FonteSoleon(cliente)}, repo, URL_BEST + "?page=1")
            self.assertEqual((r["fonte"], r["id_fonte"]), ("soleon", "bestleiloes.com.br:15412"))
            self.assertEqual(repo.buscar_imovel(r["id"])["leilao"]["pracas"][1]["valor"], 210000.0)


if __name__ == "__main__":
    unittest.main()
