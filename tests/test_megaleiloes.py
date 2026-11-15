"""Fonte Mega Leilões e cliente web, sem acessar a rede (páginas reais salvas em tests/amostras/)."""
import os, sys, tempfile, unittest, urllib.error
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from captacao.adaptadores.fontes import megaleiloes as mega
from captacao.adaptadores.persistencia.sqlite import RepositorioSQLite
from captacao.adaptadores.web import ClienteWeb
from captacao.aplicacao.coletar import coletar, importar_link
from captacao.aplicacao.ficha import baixar_documentos_fonte
from captacao.aplicacao.portas import EntradaInvalida, ErroDeFonte

AQUI = os.path.join(os.path.dirname(__file__), "amostras")
URL_X = "https://www.megaleiloes.com.br/imoveis/apartamentos/sp/indaiatuba/apartamento-55-m2-unid-12-professor-doutor-carlos-aldrovandi-indaiatuba-sp-x131551"
URL_J = "https://www.megaleiloes.com.br/imoveis/apartamentos/sp/votorantim/direitos-sobre-apartamento-49-m2-01-vaga-jardim-tatiana-votorantim-sp-j129393"


def ler(nome):
    with open(os.path.join(AQUI, nome), "rb") as f:
        return f.read()


class ClienteFalso:
    """Faz o papel do ClienteWeb: devolve páginas salvas e registra os pedidos."""
    def __init__(self, paginas):
        self.paginas, self.pedidos = paginas, []

    def baixar(self, url, usar_cache=True):
        self.pedidos.append(url)
        for chave, conteudo in self.paginas.items():
            if url.split("?")[0] == chave or url == chave:
                return conteudo
        raise ErroDeFonte(f"o site respondeu 404 para {url}")


class Leitor(unittest.TestCase):
    def test_extrajudicial_praca_unica(self):
        im = mega.interpretar_oferta(ler("megaleiloes_extrajudicial_x131551.html").decode(), URL_X, hoje="15/11/2026")
        self.assertEqual((im.fonte, im.id_fonte, im.uf, im.cidade, im.tipo), ("megaleiloes", "X131551", "SP", "INDAIATUBA", "apartamento"))
        self.assertEqual((im.preco, im.valor_avaliacao, im.area_privativa, im.modalidade), (157300.0, None, 55.26, "Extrajudicial"))
        lei = im.leilao
        self.assertEqual((lei.comitente, lei.ocupacao, lei.matricula, lei.leilao, lei.lote, lei.incremento),
                         ("BANCO SANTANDER S.A.", "ocupado", "132.841", "ML35144", "Lote 192", 5000.0))
        self.assertEqual([(p.numero, p.data, p.valor) for p in lei.pracas], [(1, "2026-11-17T13:11", 157300.0)])
        self.assertEqual([d.tipo for d in lei.documentos], ["edital", "matricula"])
        self.assertEqual(im.link, URL_X)
        self.assertNotIn("id=", im.descricao[:200])

    def test_area_do_titulo_quando_descricao_nao_traz(self):
        pagina = ler("megaleiloes_extrajudicial_x131551.html").decode().replace("55,26 m² de área privativa", "")
        pagina = pagina.replace("55,26 m² de área construída", "")
        im = mega.interpretar_oferta(pagina, URL_X)
        self.assertEqual((im.area_privativa, im.area_total), (None, 55.0))

    def test_judicial_duas_pracas(self):
        im = mega.interpretar_oferta(ler("megaleiloes_judicial_j129393.html").decode(), URL_J)
        lei = im.leilao
        self.assertEqual([(p.numero, p.valor) for p in lei.pracas], [(1, 170073.59), (2, 85036.79)])
        self.assertEqual((im.preco, im.valor_avaliacao, im.desconto_pct), (85036.79, 170073.59, 50.0))
        self.assertEqual((lei.tipo_venda, lei.comissao_pct, lei.processo), ("Judicial", 5.0, "1003014-52.2025.8.26.0663"))
        self.assertIn("Votorantim", lei.vara)
        self.assertEqual(sorted(d.tipo for d in lei.documentos), ["edital", "laudo", "matricula"])   # sem "modelo de proposta"

    def test_listagem(self):
        links, tem_proxima = mega.links_da_listagem(ler("megaleiloes_lista_apartamentos_sp.html").decode())
        self.assertEqual(len(links), 48)
        self.assertTrue(tem_proxima)
        self.assertTrue(all(mega.RE_LOTE.match(l.replace("https://www.megaleiloes.com.br", "")) for l in links))

    def test_pagina_sem_campos_vira_erro(self):
        for lixo in ("", "<html><h1 class='x'>oi</h1></html>"):
            with self.assertRaises(ErroDeFonte):
                mega.interpretar_oferta(lixo, URL_X)

    def test_aceita_url(self):
        f = mega.FonteMegaLeiloes(ClienteFalso({}))
        self.assertTrue(f.aceita_url(URL_X + "?utm_source=x"))
        for url in ("https://www.megaleiloes.com.br/imoveis/apartamentos/sp", "http://www.megaleiloes.com.br/imoveis/a/sp/b/c-x1",
                    "https://evil.com/imoveis/a/sp/b/c-x1", "https://www.sold.com.br/oferta/abc"):
            self.assertFalse(f.aceita_url(url), url)


class Coleta(unittest.TestCase):
    def site(self):
        imoveis = '<a href="https://www.megaleiloes.com.br/imoveis/apartamentos">A</a><a href="https://www.megaleiloes.com.br/imoveis/casas">C</a>'
        lista = ler("megaleiloes_lista_apartamentos_sp.html")
        links, _ = mega.links_da_listagem(lista.decode())
        paginas = {f"{mega.BASE}/imoveis": imoveis.encode(), f"{mega.BASE}/imoveis/apartamentos/sp": lista,
                   links[0]: ler("megaleiloes_extrajudicial_x131551.html"), links[1]: ler("megaleiloes_judicial_j129393.html")}
        return ClienteFalso(paginas), links

    def test_coleta_diaria_com_limite(self):
        cliente, links = self.site()
        f = mega.FonteMegaLeiloes(cliente)
        c = f.coletar("SP", limite=3)
        self.assertEqual(sorted(im.id_fonte for im in c.imoveis), ["J129393", "X131551"])
        self.assertTrue(any(links[2] in a for a in c.avisos))                       # lote que falhou vira aviso
        self.assertNotIn(f"{mega.BASE}/imoveis/casas/sp", cliente.pedidos)          # parou ao atingir o limite
        self.assertFalse(c.completa)
        with RepositorioSQLite(":memory:") as repo:
            r = coletar(mega.FonteMegaLeiloes(self.site()[0]), repo, "SP", limite=3)
            self.assertEqual((r["novos"], r["completa"]), (2, False))
            ids = [x[0] for x in repo.con.execute("SELECT id FROM imoveis ORDER BY id")]
            self.assertEqual(repo.buscar_imovel(ids[1])["leilao"]["vara"][:9], "1ª Vara C")
        cliente2, _ = self.site()
        completo = mega.FonteMegaLeiloes(cliente2).coletar("SP")
        self.assertFalse(any("casas/SP" in a for a in completo.avisos))             # categoria vazia (404) é normal
        self.assertEqual(len(completo.imoveis), 2)
        self.assertFalse(completo.completa)                                         # 46 lotes não lidos

    def test_pagina_repetida_encerra_a_paginacao(self):
        cliente, links = self.site()
        lista = cliente.paginas[f"{mega.BASE}/imoveis/apartamentos/sp"]
        cliente.paginas = {k: v for k, v in cliente.paginas.items()}
        original = cliente.baixar
        def baixar(url, usar_cache=True):     # toda página da listagem devolve a mesma lista, como o site faz
            if url.split("?")[0] == f"{mega.BASE}/imoveis/apartamentos/sp":
                cliente.pedidos.append(url); return lista
            return original(url, usar_cache)
        cliente.baixar = baixar
        mega.FonteMegaLeiloes(cliente).coletar("SP", limite=1)
        paginas = [u for u in cliente.pedidos if u.split("?")[0] == f"{mega.BASE}/imoveis/apartamentos/sp"]
        self.assertEqual(paginas, [f"{mega.BASE}/imoveis/apartamentos/sp", f"{mega.BASE}/imoveis/apartamentos/sp?pagina=2"])

    def test_erro_na_listagem_deixa_coleta_incompleta(self):
        cliente, _ = self.site()
        original = cliente.baixar
        def baixar(url, usar_cache=True):
            if "/imoveis/casas/sp" in url:
                raise ErroDeFonte(f"o site respondeu 500 para {url}")
            return original(url, usar_cache)
        cliente.baixar = baixar
        c = mega.FonteMegaLeiloes(cliente).coletar("SP")
        self.assertTrue(any("casas/SP" in a and "500" in a for a in c.avisos))
        self.assertFalse(c.completa)

    def test_importar_link_e_baixar_documentos(self):
        pdf = b"%PDF-1.4\n%%EOF\n"
        cliente = ClienteFalso({URL_X: ler("megaleiloes_extrajudicial_x131551.html"),
                                "https://cdn1.megaleiloes.com.br/auctions/35144/megaleiloes_edital_ML35144_261107-212335.pdf": pdf,
                                "https://cdn1.megaleiloes.com.br/batches/131551/megaleiloes_matricula_X131551_261112-115013.pdf": pdf + b"m"})
        fontes = {"megaleiloes": mega.FonteMegaLeiloes(cliente)}
        with RepositorioSQLite(":memory:") as repo:
            r = importar_link(fontes, repo, URL_X + "?utm_source=megaleiloes")
            self.assertEqual((r["fonte"], r["id_fonte"]), ("megaleiloes", "X131551"))
            self.assertEqual(cliente.pedidos[-1], URL_X)                                # sem os parâmetros de rastreio
            d = baixar_documentos_fonte(repo, tempfile.mkdtemp(), r["id"], cliente)
            self.assertEqual(sorted(x["tipo"] for x in d["baixados"]), ["edital", "matricula"])
            self.assertEqual(d["erros"], [])
            for url in ("http://x", "https://www.sold.com.br/oferta/abc", 5):
                with self.assertRaises(EntradaInvalida):
                    importar_link(fontes, repo, url)


class Web(unittest.TestCase):
    def cliente(self, respostas, **k):
        self.pedidos, self.esperas, self.t = [], [], [0.0]
        class Resp:
            def __init__(s, dados): s.dados = dados
            def read(s, n=-1): return s.dados
            def __enter__(s): return s
            def __exit__(s, *a): pass
        def abrir(req, timeout):
            self.pedidos.append(req.full_url)
            r = respostas.get(req.full_url, 404)
            if isinstance(r, int):
                raise urllib.error.HTTPError(req.full_url, r, "erro", {}, None)
            return Resp(r)
        def dormir(s): self.esperas.append(round(s, 2)); self.t[0] += s
        return ClienteWeb(abrir=abrir, dormir=dormir, relogio=lambda: self.t[0], **k)

    def test_respeita_robots_e_intervalo(self):
        c = self.cliente({"https://s.test/robots.txt": b"User-agent: *\nDisallow: /privado\n",
                          "https://s.test/a": b"A", "https://s.test/b": b"B"}, intervalo=3)
        self.assertEqual(c.baixar("https://s.test/a"), b"A")
        self.assertEqual(c.baixar("https://s.test/b"), b"B")
        with self.assertRaises(ErroDeFonte):
            c.baixar("https://s.test/privado/x")
        self.assertEqual(self.pedidos, ["https://s.test/robots.txt", "https://s.test/a", "https://s.test/b"])
        self.assertEqual(self.esperas, [3.0, 3.0])            # 3 s entre pedidos ao mesmo site

    def test_crawl_delay_maior_vale(self):
        c = self.cliente({"https://s.test/robots.txt": b"User-agent: *\nCrawl-delay: 10\n", "https://s.test/a": b"A"}, intervalo=3)
        c.baixar("https://s.test/a")
        self.assertEqual(self.esperas, [10.0])

    def test_sem_robots_permite_e_robots_inacessivel_bloqueia(self):
        c = self.cliente({"https://s.test/a": b"A"})
        self.assertEqual(c.baixar("https://s.test/a"), b"A")         # robots.txt 404 = sem restrições
        c2 = self.cliente({"https://t.test/robots.txt": 500, "https://t.test/a": b"A"})
        with self.assertRaises(ErroDeFonte):
            c2.baixar("https://t.test/a")

    def test_cache_e_erros(self):
        pasta = tempfile.mkdtemp()
        c = self.cliente({"https://s.test/a": b"A"}, pasta_cache=pasta)
        c.baixar("https://s.test/a"); c.baixar("https://s.test/a")
        self.assertEqual(self.pedidos.count("https://s.test/a"), 1)
        with self.assertRaises(ErroDeFonte):
            c.baixar("https://s.test/nao-existe")
        with self.assertRaises(ErroDeFonte):
            c.baixar("ftp://s.test/a")


if __name__ == "__main__":
    unittest.main()
