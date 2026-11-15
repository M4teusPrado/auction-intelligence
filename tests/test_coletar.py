"""Caso de uso Coletar, com fontes falsas: vale para qualquer fonte."""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from captacao.adaptadores.persistencia.sqlite import RepositorioSQLite
from captacao.aplicacao.coletar import coletar
from captacao.aplicacao.portas import Coleta, ErroDeFonte
from captacao.dominio.modelo import ImovelCaptado


def imovel(fonte, id_fonte, cidade="CAMPINAS", tipo="casa", preco=100000.0):
    return ImovelCaptado(fonte=fonte, id_fonte=id_fonte, uf="SP", cidade=cidade, bairro="", endereco=f"RUA {id_fonte}",
                         preco=preco, valor_avaliacao=None, desconto_pct=None, modalidade="Leilão", tipo=tipo,
                         area_privativa=50.0, area_terreno=100.0, area_total=None, descricao="", link="", data_fonte="")


class FonteFalsa:
    def __init__(self, nome, imoveis, recortes=("SP", "RJ"), avisos=()):
        self.nome, self.descricao, self._imoveis, self._recortes, self._avisos = nome, "falsa", imoveis, list(recortes), list(avisos)
        self.pedidos = []

    def recortes(self):
        return self._recortes

    def coletar(self, recorte, arquivo=None, nome_arquivo=""):
        self.pedidos.append((recorte, arquivo, nome_arquivo))
        return Coleta(imoveis=list(self._imoveis), recorte=recorte, origem=f"falsa:{recorte}", avisos=self._avisos)

    def descrever_modalidade(self, modalidade):
        return None


class RepoFalso:
    def __init__(self):
        self.chamadas = []

    def gravar_coleta(self, fonte, recorte, origem, imoveis, n_avisos=0, agora=None):
        imoveis = list(imoveis)
        self.chamadas.append((fonte, recorte, origem, imoveis, n_avisos))
        return {"coleta": 1, "total": len(imoveis), "novos": len(imoveis), "alterados": 0, "saidos": 0, "avisos": n_avisos}


class Coletar(unittest.TestCase):
    def test_fluxo(self):
        f = FonteFalsa("banco_x", [imovel("banco_x", "1"), imovel("banco_x", "2", tipo="chacara")], avisos=["linha 9: sem preço"])
        repo = RepoFalso()
        r = coletar(f, repo, "SP", b"conteudo", "lista.csv")
        self.assertEqual(f.pedidos, [("SP", b"conteudo", "lista.csv")])
        fonte, recorte, origem, ims, n_avisos = repo.chamadas[0]
        self.assertEqual((fonte, recorte, origem), ("banco_x", "SP", "falsa:SP"))
        self.assertEqual([i.categoria for i in ims], ["casa", "outros"])        # classificação do domínio
        self.assertEqual(n_avisos, 2)                                           # aviso da fonte + tipo novo
        self.assertEqual(r["lista_avisos"][0], "linha 9: sem preço")

    def test_recorte_invalido(self):
        with self.assertRaises(ErroDeFonte):
            coletar(FonteFalsa("banco_x", []), RepoFalso(), "XX")
        with self.assertRaises(ErroDeFonte):
            coletar(FonteFalsa("site_y", [], recortes=()), RepoFalso(), "SP")
        coletar(FonteFalsa("site_y", [imovel("site_y", "1")], recortes=()), RepoFalso(), "")   # fonte sem recortes

    def test_fonte_nao_grava_em_nome_de_outra(self):
        repo = RepoFalso()
        with self.assertRaises(ErroDeFonte):
            coletar(FonteFalsa("banco_x", [imovel("caixa", "1")]), repo, "SP")
        self.assertEqual(repo.chamadas, [])


class VariasFontes(unittest.TestCase):
    def test_uma_fonte_nao_marca_saida_na_outra(self):
        with RepositorioSQLite(":memory:") as repo:
            coletar(FonteFalsa("caixa", [imovel("caixa", "c1"), imovel("caixa", "c2")]), repo, "SP")
            coletar(FonteFalsa("banco_x", [imovel("banco_x", "b1")]), repo, "SP")
            r = coletar(FonteFalsa("banco_x", [imovel("banco_x", "b2")]), repo, "SP")     # b1 sai; caixa intacta
            self.assertEqual(r["saidos"], 1)
            situacao = dict(repo.con.execute("SELECT fonte || ':' || id_fonte, situacao FROM imoveis").fetchall())
            self.assertEqual(situacao, {"caixa:c1": "ativo", "caixa:c2": "ativo",
                                        "banco_x:b1": "saiu_da_lista", "banco_x:b2": "ativo"})

    def test_recortes_diferentes_da_mesma_fonte_sao_independentes(self):
        with RepositorioSQLite(":memory:") as repo:
            coletar(FonteFalsa("banco_x", [imovel("banco_x", "1")]), repo, "SP")
            r = coletar(FonteFalsa("banco_x", [imovel("banco_x", "2")]), repo, "RJ")
            self.assertEqual(r["saidos"], 0)


if __name__ == "__main__":
    unittest.main()
