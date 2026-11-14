import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from captacao import classifica, repositorio, triagem
from captacao.modelo import ImovelCaptado
from captacao.triagem import EntradaInvalida, NaoEncontrado

SFI = "Leilão SFI - Edital Único"


def imovel(i, **k):
    base = dict(fonte="caixa", id_fonte=str(1000 + i), uf="SP", cidade="CAMPINAS", bairro="CENTRO",
                endereco=f"RUA {i}", preco=100000.0 + i * 1000, valor_avaliacao=200000.0,
                desconto_pct=float(i % 60), modalidade=SFI, tipo="casa", area_privativa=60.0,
                area_terreno=200.0 + i, area_total=None, descricao="Casa", link=f"https://x.invalid/{i}",
                data_fonte="13/11/2026")
    base.update(k)
    return ImovelCaptado(**base)


def base_teste():
    """120 imóveis: 0-99 casas SFI em Campinas; 100-109 terrenos em São José do Rio Preto
    (Venda Direta Online); 110-119 apartamentos em Sorocaba, um com alerta."""
    ims = [imovel(i) for i in range(100)]
    ims += [imovel(i, tipo="terreno", cidade="SÃO JOSÉ DO RIO PRETO", modalidade="Venda Direta Online",
                   area_privativa=None, area_terreno=1000.0 + i) for i in range(100, 110)]
    ims += [imovel(i, tipo="apartamento", cidade="SOROCABA", area_terreno=None) for i in range(110, 120)]
    ims[115].area_terreno = 1.0                      # alerta area_terreno_suspeita
    classifica.classificar(ims)
    con = repositorio.conectar(":memory:")
    repositorio.gravar_coleta(con, "caixa", "SP", "teste", ims, agora="2026-11-14T10:00:00")
    return con


def q(**k):
    return {n: (v if isinstance(v, list) else [str(v)]) for n, v in k.items()}


class Listar(unittest.TestCase):
    def setUp(self):
        self.con = base_teste(); self.addCleanup(self.con.close)

    def test_paginacao(self):
        r = triagem.listar(self.con, q())
        self.assertEqual((r["total"], r["paginas"], len(r["itens"])), (120, 3, 50))
        ultima = triagem.listar(self.con, q(pagina=3))
        self.assertEqual(len(ultima["itens"]), 20)
        ids = [i["id"] for p in (1, 2, 3) for i in triagem.listar(self.con, q(pagina=p))["itens"]]
        self.assertEqual(len(set(ids)), 120)          # nenhuma repetição entre páginas
        self.assertEqual(triagem.listar(self.con, q(pagina=4))["itens"], [])

    def test_filtros(self):
        self.assertEqual(triagem.listar(self.con, q(modalidade=SFI))["total"], 110)
        self.assertEqual(triagem.listar(self.con, q(modalidade=[SFI, "Venda Direta Online"]))["total"], 120)
        self.assertEqual(triagem.listar(self.con, q(categoria=["terreno", "apartamento"]))["total"], 20)
        self.assertEqual(triagem.listar(self.con, q(cidade="sao jose"))["total"], 10)   # sem acento
        self.assertEqual(triagem.listar(self.con, q(cidade="  "))["total"], 120)
        self.assertEqual(triagem.listar(self.con, q(preco_min=150000, preco_max=160000))["total"], 11)
        self.assertEqual(triagem.listar(self.con, q(desconto_min=55))["total"], 10)
        self.assertEqual(triagem.listar(self.con, q(area_terreno_min=1000))["total"], 10)
        self.assertEqual(triagem.listar(self.con, q(sem_alertas=1))["total"], 119)
        self.assertEqual(triagem.listar(self.con, q(estagio="analisar"))["total"], 0)

    def test_ordem(self):
        self.assertEqual(triagem.listar(self.con, q(ordem="preco"))["itens"][0]["id_fonte"], "1000")
        self.assertEqual(triagem.listar(self.con, q(ordem="area_terreno"))["itens"][0]["id_fonte"], "1109")
        d = [i["desconto_pct"] for i in triagem.listar(self.con, q(ordem="desconto"))["itens"]]
        self.assertEqual(d, sorted(d, reverse=True))
        ult = triagem.listar(self.con, q(ordem="area_terreno", pagina=3))["itens"]
        self.assertIsNone(ult[-1]["area_terreno"])     # vazios no fim

    def test_item_tem_campos_da_tela(self):
        it = triagem.listar(self.con, q(sem_alertas=0, ordem="recente"))["itens"][0]
        for campo in ("categoria", "tipo", "cidade", "bairro", "endereco", "preco", "valor_avaliacao",
                      "desconto_pct", "area_privativa", "area_terreno", "area_total", "modalidade",
                      "alertas", "primeira_vez", "link", "estagio", "nota"):
            self.assertIn(campo, it)
        alerta = triagem.listar(self.con, q(categoria="apartamento", area_terreno_min=0))["itens"]
        self.assertEqual(alerta[0]["alertas"], ["area_terreno_suspeita"])

    def test_validacao(self):
        for params in (q(estagio="xpto"), q(categoria="castelo"), q(ordem="nome"), q(pagina=0),
                       q(pagina="abc"), q(preco_min="caro"), q(preco_min=-1), q(desconto_min="nan"),
                       q(preco_max="inf"), q(sem_alertas="talvez"), q(foo=1),
                       {"estagio": ["analisar", "depois"]}, q(cidade="x" * 81),
                       q(modalidade="' OR 1=1 --")):
            with self.subTest(params=params):
                if params == q(modalidade="' OR 1=1 --"):   # aceito, mas como texto literal
                    self.assertEqual(triagem.listar(self.con, params)["total"], 0)
                else:
                    with self.assertRaises(EntradaInvalida):
                        triagem.listar(self.con, params)


class Resumo(unittest.TestCase):
    def test_resumo_e_opcoes(self):
        con = base_teste(); self.addCleanup(con.close)
        ims = [imovel(i) for i in range(100)]          # segunda coleta: 2 quedas, 1 alta, 20 saem
        ims[0].preco = 50000.0; ims[1].preco = 60000.0; ims[2].preco = 999999.0
        classifica.classificar(ims)
        repositorio.gravar_coleta(con, "caixa", "SP", "teste", ims, agora="2026-11-15T10:00:00")
        r = triagem.resumo(con)
        self.assertEqual(r["total_ativo"], 100)
        self.assertEqual(r["por_estagio"], {"identificado": 100, "analisar": 0, "depois": 0, "descartado": 0})
        c = r["ultima_coleta"]
        self.assertEqual((c["novos"], c["quedas_preco"], c["saidos"], c["data_fonte"], c["quando"]),
                         (0, 2, 20, "13/11/2026", "2026-11-15T10:00:00"))
        con2 = base_teste(); self.addCleanup(con2.close)
        o = triagem.opcoes(con2)
        self.assertEqual(o["modalidades"][0], {"valor": SFI, "n": 110})
        self.assertEqual({c["valor"] for c in o["categorias"]}, {"casa", "terreno", "apartamento"})
        self.assertEqual([c["valor"] for c in o["cidades"]], ["CAMPINAS", "SOROCABA", "SÃO JOSÉ DO RIO PRETO"])

    def test_base_vazia(self):
        con = repositorio.conectar(":memory:"); self.addCleanup(con.close)
        r = triagem.resumo(con)
        self.assertEqual((r["total_ativo"], r["ultima_coleta"]), (0, None))


class Triar(unittest.TestCase):
    def setUp(self):
        self.con = base_teste(); self.addCleanup(self.con.close)
        self.id = triagem.listar(self.con, q(ordem="preco"))["itens"][0]["id"]

    def linhas(self):
        return [tuple(r) for r in self.con.execute(
            "SELECT de, para, nota FROM triagens WHERE imovel_id=? ORDER BY id", (self.id,))]

    def test_triagem_e_desfazer(self):
        im = triagem.triar(self.con, self.id, {"para": "analisar", "nota": "  ver matrícula  "})
        self.assertEqual((im["estagio"], im["nota"], im["triagem"]["de"]), ("analisar", "ver matrícula", "identificado"))
        self.assertEqual(triagem.listar(self.con, q(estagio="identificado"))["total"], 119)
        self.assertEqual(triagem.resumo(self.con)["por_estagio"]["analisar"], 1)
        im = triagem.triar(self.con, self.id, {"desfazer": True})
        self.assertEqual((im["estagio"], im["nota"]), ("identificado", None))
        self.assertEqual(self.linhas(), [("identificado", "analisar", "ver matrícula"),
                                         ("analisar", "identificado", None)])   # nada apagado

    def test_voltar_para_fila(self):
        triagem.triar(self.con, self.id, {"para": "descartado"})
        triagem.triar(self.con, self.id, {"para": "identificado"})
        self.assertEqual(len(self.linhas()), 2)

    def test_validacao(self):
        for corpo in ([], "analisar", {}, {"para": "vendido"}, {"para": "identificado"},
                      {"para": "analisar", "nota": 5}, {"para": "analisar", "nota": "x" * 1001},
                      {"para": "analisar", "extra": 1}, {"desfazer": True},
                      {"desfazer": "sim"}, {"desfazer": True, "para": "depois"}):
            with self.subTest(corpo=corpo), self.assertRaises(EntradaInvalida):
                triagem.triar(self.con, self.id, corpo)
        with self.assertRaises(NaoEncontrado):
            triagem.triar(self.con, 999999, {"para": "analisar"})
        self.assertEqual(self.linhas(), [])           # nada gravado nas tentativas inválidas

    def test_nota_vazia_vira_nula(self):
        im = triagem.triar(self.con, self.id, {"para": "depois", "nota": "   "})
        self.assertIsNone(im["nota"])


if __name__ == "__main__":
    unittest.main()
