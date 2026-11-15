import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from captacao import simulador
from captacao.simulador import PremissaInvalida

# Exemplo feito à mão:
# lance 100.000; leiloeiro 5% = 5.000; ITBI 3% = 3.000; registro 1,5% = 1.500;
# débitos 2.000; reforma 200 x 50 m² = 10.000; custo mensal 500 x 12 = 6.000
# investimento = 127.500
# venda 180.000; corretagem 6% = 10.800; lucro antes do IR = 41.700; IR 15% = 6.255
# lucro = 35.445; retorno = 35.445 / 127.500 = 27,80%
EXEMPLO = dict(lance=100000, comissao_leiloeiro_pct=5, itbi_pct=3, registro_pct=1.5, debitos=2000,
               desocupacao=0, reforma_m2=200, area_reforma=50, custo_mensal=500, prazo_meses=12,
               valor_venda=180000, corretagem_pct=6, ir_pct=15)


class Conta(unittest.TestCase):
    def test_exemplo_a_mao(self):
        r = simulador.simular(EXEMPLO)
        self.assertEqual(r["investimento"], 127500.0)
        custos = {c["rotulo"]: c["valor"] for c in r["custos"]}
        self.assertEqual((custos["Comissão do leiloeiro"], custos["ITBI"], custos["Escritura e registro"],
                          custos["Reforma"], custos["Custo mensal × prazo"]), (5000, 3000, 1500, 10000, 6000))
        v = r["venda"]
        self.assertEqual((v["corretagem"], v["lucro_antes_ir"], v["ir"], v["lucro"]), (10800, 41700, 6255, 35445))
        self.assertEqual(v["roi_pct"], 27.8)
        self.assertAlmostEqual(v["roi_mes_pct"], ((1 + 35445 / 127500) ** (1 / 12) - 1) * 100, places=2)
        self.assertEqual(r["avisos"], [])

    def test_prejuizo_nao_gera_imposto(self):
        r = simulador.simular({**EXEMPLO, "valor_venda": 120000})
        self.assertEqual(r["venda"]["ir"], 0)
        self.assertLess(r["venda"]["lucro"], 0)

    def test_sem_valor_de_venda_nao_calcula_retorno(self):
        p = dict(EXEMPLO); del p["valor_venda"]
        r = simulador.simular(p)
        self.assertIsNone(r["venda"])
        self.assertEqual(r["investimento"], 127500.0)
        self.assertIn("valor de venda", r["avisos"][0])

    def test_lance_maximo(self):
        # 0,85 x (151.200 - 1,095 L) = 0,20 x (1,095 L + 18.000)  =>  L = 108.649,7
        r = simulador.simular({**EXEMPLO, "meta_roi_pct": 20})
        self.assertAlmostEqual(r["lance_maximo"], 108649, delta=1)
        no_limite = simulador.simular({**EXEMPLO, "lance": r["lance_maximo"]})
        self.assertGreaterEqual(no_limite["venda"]["roi_pct"], 19.99)

    def test_meta_impossivel(self):
        r = simulador.simular({**EXEMPLO, "meta_roi_pct": 900})
        self.assertIsNone(r["lance_maximo"])
        self.assertTrue(any("meta" in a for a in r["avisos"]))

    def test_padrao_usa_dados_da_fonte_e_nao_a_avaliacao(self):
        p = simulador.padrao_para({"preco": 98000.0, "area_privativa": None, "area_total": 70.0,
                                   "valor_avaliacao": 200000.0})
        self.assertEqual((p["lance"], p["area_reforma"], p["valor_venda"]), (98000.0, 70.0, None))
        self.assertEqual(p["itbi_pct"], 3.0)


class Validacao(unittest.TestCase):
    def test_invalidos(self):
        for extra in ({"itbi_pct": 101}, {"lance": -1}, {"lance": "100"}, {"lance": True},
                      {"lance": float("nan")}, {"lance": float("inf")}, {"prazo_meses": 0},
                      {"prazo_meses": 121}, {"foo": 1}, {"lance": None}, {"itbi_pct": None},
                      {"meta_roi_pct": 5000}):
            with self.subTest(extra=extra), self.assertRaises(PremissaInvalida):
                simulador.simular({**EXEMPLO, **extra})
        with self.assertRaises(PremissaInvalida):
            simulador.simular([1, 2])

    def test_vazio_vira_padrao_ou_nulo(self):
        r = simulador.simular({"lance": 100000})
        self.assertEqual(r["premissas"]["itbi_pct"], 3.0)
        self.assertIsNone(r["premissas"]["valor_venda"])


if __name__ == "__main__":
    unittest.main()
