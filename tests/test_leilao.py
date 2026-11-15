"""Modelo de leilão: praças, comitente, documentos da fonte, ordem por leilão mais próximo."""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from captacao.adaptadores.persistencia.sqlite import RepositorioSQLite
from captacao.aplicacao import triagem
from captacao.dominio import simulador
from captacao.dominio.modelo import DadosLeilao, DocumentoFonte, ImovelCaptado, Praca


def lote(id_fonte, pracas, fonte="leiloeiro_x", preco=100000.0, **lei):
    return ImovelCaptado(
        fonte=fonte, id_fonte=id_fonte, uf="SP", cidade="SOROCABA", bairro="CENTRO", endereco=f"RUA {id_fonte}",
        preco=preco, valor_avaliacao=200000.0, desconto_pct=50.0, modalidade="Judicial", tipo="apartamento",
        area_privativa=50.0, area_terreno=None, area_total=None, descricao="", link=f"https://x.invalid/{id_fonte}",
        data_fonte="15/11/2026", categoria="apartamento",
        leilao=DadosLeilao(tipo_venda="Judicial", leilao="L1", lote="Lote 1", comitente="BANCO X", leiloeiro="Fulano",
                           ocupacao="ocupado", matricula="16.627", processo="000123", vara="1ª Vara Cível",
                           pracas=[Praca(n, d, v) for n, d, v in pracas],
                           documentos=[DocumentoFonte("edital", f"https://x.invalid/{id_fonte}/edital.pdf", "Edital")],
                           **lei))


def q(**k):
    return {n: (v if isinstance(v, list) else [str(v)]) for n, v in k.items()}


class Leilao(unittest.TestCase):
    def setUp(self):
        self.repo = RepositorioSQLite(":memory:"); self.addCleanup(self.repo.close)
        self.repo.gravar_coleta("leiloeiro_x", "SP", "teste", [
            lote("A", [(1, "2099-01-10T10:00", 200000.0), (2, "2099-02-10T10:00", 100000.0)]),
            lote("B", [(1, "2099-01-05T10:00", 150000.0)]),
            lote("C", [(1, "2000-01-01T10:00", 90000.0)]),          # leilão já passou
        ])

    def id_de(self, id_fonte):
        return self.repo.con.execute("SELECT id FROM imoveis WHERE id_fonte=?", (id_fonte,)).fetchone()[0]

    def test_detalhe_do_leilao(self):
        im = self.repo.buscar_imovel(self.id_de("A"))
        lei = im["leilao"]
        self.assertEqual((lei["tipo_venda"], lei["comitente"], lei["ocupacao"], lei["vara"]),
                         ("Judicial", "BANCO X", "ocupado", "1ª Vara Cível"))
        self.assertEqual([(p["numero"], p["valor"]) for p in lei["pracas"]], [(1, 200000.0), (2, 100000.0)])
        self.assertEqual(lei["documentos"][0]["tipo"], "edital")
        self.assertEqual((im["proxima_praca"], im["proxima_praca_valor"]), ("2099-01-10T10:00", 200000.0))
        self.assertIsNone(self.repo.buscar_imovel(self.id_de("C"))["proxima_praca"])

    def test_ordem_por_leilao_mais_proximo_e_filtro_de_fonte(self):
        r = triagem.listar(self.repo, q(ordem="leilao"))
        self.assertEqual([i["id_fonte"] for i in r["itens"]], ["B", "A", "C"])      # sem praça futura vai para o fim
        self.assertEqual(triagem.listar(self.repo, q(fonte="leiloeiro_x"))["total"], 3)
        self.assertEqual(triagem.listar(self.repo, q(fonte="caixa"))["total"], 0)
        self.assertEqual(triagem.opcoes(self.repo)["fontes"], [{"valor": "leiloeiro_x", "n": 3}])

    def test_nova_coleta_substitui_pracas(self):
        self.repo.gravar_coleta("leiloeiro_x", "SP", "teste", [lote("A", [(1, "2099-03-01T10:00", 180000.0)])])
        lei = self.repo.buscar_imovel(self.id_de("A"))["leilao"]
        self.assertEqual([(p["numero"], p["valor"]) for p in lei["pracas"]], [(1, 180000.0)])

    def test_importar_avulso_nao_marca_saidos(self):
        iid = self.repo.gravar_avulso(lote("D", [(1, "2099-05-01T10:00", 50000.0)]), "https://x.invalid/D")
        self.assertEqual(self.repo.buscar_imovel(iid)["id_fonte"], "D")
        situ = dict(self.repo.con.execute("SELECT id_fonte, situacao FROM imoveis").fetchall())
        self.assertEqual(set(situ.values()), {"ativo"})

    def test_caixa_sem_leilao_continua_igual(self):
        caixa = lote("Z", [], fonte="caixa"); caixa.leilao = None
        self.repo.gravar_coleta("caixa", "SP", "teste", [caixa])
        im = self.repo.buscar_imovel(self.id_de("Z"))
        self.assertIsNone(im["leilao"]); self.assertIsNone(im["proxima_praca"])

    def test_simulador_usa_comissao_da_fonte(self):
        self.repo.gravar_coleta("leiloeiro_y", "SP", "t", [lote("E", [(1, "2099-01-01T10:00", 80000.0)],
                                                                fonte="leiloeiro_y", preco=80000.0, comissao_pct=2.5)])
        im = self.repo.buscar_imovel(self.id_de("E"))
        p = simulador.padrao_para(im)
        self.assertEqual((p["lance"], p["comissao_leiloeiro_pct"]), (80000.0, 2.5))
        self.assertEqual(simulador.padrao_para(self.repo.buscar_imovel(self.id_de("A")))["comissao_leiloeiro_pct"], 5.0)


if __name__ == "__main__":
    unittest.main()
