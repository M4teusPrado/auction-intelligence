"""Contrato que TODA fonte registrada em montagem.FONTES precisa cumprir.

Para uma fonte nova: acrescente em AMOSTRAS um recorte e um conteúdo de exemplo
(arquivo salvo em tests/), lido sem acessar a rede.
"""
import os, re, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from captacao import montagem
from captacao.aplicacao.portas import Coleta, ErroDeFonte, FonteDeImoveis
from captacao.dominio.modelo import ImovelCaptado

AQUI = os.path.dirname(__file__)


def _ler(nome):
    with open(os.path.join(AQUI, nome), "rb") as f:
        return f.read()


AMOSTRAS = {   # nome da fonte: (recorte, conteúdo de exemplo)
    "caixa": ("SP", _ler("exemplo_caixa.csv")),
    "megaleiloes": ("SP", _ler("amostras/megaleiloes_extrajudicial_x131551.html")),
    "soleon": ("bestleiloes.com.br", _ler("amostras/soleon_item_aberto_best.html")),
}


class ContratoDeFonte(unittest.TestCase):
    def test_toda_fonte_registrada_tem_amostra(self):
        faltando = set(montagem.FONTES) - set(AMOSTRAS)
        self.assertFalse(faltando, f"fontes sem amostra de teste: {faltando}")

    def test_contrato(self):
        for nome, fonte in montagem.FONTES.items():
            with self.subTest(fonte=nome):
                self.assertIsInstance(fonte, FonteDeImoveis)
                self.assertEqual(fonte.nome, nome)
                self.assertRegex(nome, r"^[a-z][a-z0-9_]*$")
                self.assertTrue(fonte.descricao.strip())
                self.assertTrue(0 < len(fonte.rotulo) <= 30)
                recortes = fonte.recortes()
                self.assertTrue(all(isinstance(r, str) and r for r in recortes))
                recorte, conteudo = AMOSTRAS[nome]
                if recortes:
                    self.assertIn(recorte, recortes)
                c = fonte.coletar(recorte, conteudo, "amostra")
                self.assertIsInstance(c, Coleta)
                self.assertEqual(c.recorte, recorte)
                self.assertTrue(c.origem)
                self.assertTrue(c.imoveis, "a amostra deve gerar pelo menos um imóvel")
                self.assertTrue(all(isinstance(a, str) for a in c.avisos))
                ids = [im.id_fonte for im in c.imoveis]
                self.assertEqual(len(ids), len(set(ids)), "id_fonte repetido na mesma coleta")
                for im in c.imoveis:
                    self.assertIsInstance(im, ImovelCaptado)
                    self.assertEqual(im.fonte, nome)
                    self.assertTrue(im.id_fonte and im.cidade and im.uf)
                    self.assertTrue(im.preco is None or im.preco >= 0)
                desc = fonte.descrever_modalidade(c.imoveis[0].modalidade)
                self.assertTrue(desc is None or isinstance(desc, str))
                self.assertIsNone(fonte.descrever_modalidade("modalidade que não existe"))

    def test_conteudo_invalido_vira_erro_de_fonte(self):
        for nome, fonte in montagem.FONTES.items():
            recorte = AMOSTRAS[nome][0]
            for lixo in (b"", b"<html><body>bloqueado</body></html>", b"a;b;c\n1;2;3\n", bytes(range(256))):
                with self.subTest(fonte=nome, lixo=lixo[:20]), self.assertRaises(ErroDeFonte):
                    fonte.coletar(recorte, lixo, "lixo")


class Caixa(unittest.TestCase):
    def test_descrever_modalidade(self):
        f = montagem.fonte("caixa")
        self.assertIn("9.514", f.descrever_modalidade("Leilão SFI - Edital Único"))
        self.assertIn("Venda direta", f.descrever_modalidade("Venda Direta Online"))

    def test_download_usa_funcao_injetada(self):
        from captacao.adaptadores.fontes.caixa import FonteCaixa
        pedidos = []
        f = FonteCaixa(baixar_lista=lambda uf: pedidos.append(uf) or AMOSTRAS["caixa"][1])
        c = f.coletar("SP")
        self.assertEqual(pedidos, ["SP"])
        self.assertIn("Lista_imoveis_SP.csv", c.origem)

    def test_fonte_desconhecida(self):
        with self.assertRaises(ErroDeFonte):
            montagem.fonte("nao_existe")


if __name__ == "__main__":
    unittest.main()
