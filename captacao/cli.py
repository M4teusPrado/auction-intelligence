"""Uso:
  python -m captacao fontes                          lista as fontes e seus recortes
  python -m captacao coletar --uf SP                 baixa a lista da Caixa e atualiza a base
  python -m captacao coletar --uf SP --arquivo x.csv usa um arquivo baixado pelo navegador
  python -m captacao coletar --fonte caixa --recorte SP   forma geral, para qualquer fonte
  python -m captacao coletar --fonte megaleiloes --recorte SP   coleta diária da Mega Leilões
  python -m captacao importar <link da oferta>      importa um imóvel avulso (sites suportados)
  python -m captacao listar --uf SP --cidade campinas --tipo terreno --desconto-min 30
  python -m captacao listar --categoria terreno       tipo agrupado (terreno inclui gleba)
  python -m captacao novidades                       o que mudou na última coleta
  python -m captacao duplicados                      possíveis imóveis repetidos
  python -m captacao exportar imoveis.csv
  python -m captacao tela [--porta 8765]             abre a tela de triagem no navegador
"""
import argparse
import csv
import sys

from . import montagem
from .aplicacao.coletar import coletar, importar_link
from .aplicacao.portas import EntradaInvalida, ErroDeFonte, FiltroImoveis


def _brl(v):
    return "-" if v is None else f"R$ {v:,.0f}".replace(",", ".")


def cmd_fontes(a, repo):
    for f in montagem.FONTES.values():
        rec = f.recortes()
        print(f"{f.nome:<12} {f.descricao}")
        print(f"{'':<12} recortes: {', '.join(rec) if rec else '(um só)'}")


def cmd_coletar(a, repo):
    f = montagem.fonte(a.fonte)
    recorte = a.recorte if a.recorte is not None else (a.uf or "")
    if f.nome == "caixa":
        recorte = recorte.upper()
    arquivo = None
    if a.arquivo:
        with open(a.arquivo, "rb") as arq:
            arquivo = arq.read()
    r = coletar(f, repo, recorte, arquivo, a.arquivo or "", limite=a.limite)
    rotulo = f"{f.nome} {r['recorte']}".strip()
    print(f"Coleta {r['coleta']} ({rotulo}): {r['total']} imóveis lidos, {r['novos']} novos, "
          f"{r['alterados']} alterados, {r['saidos']} saíram da lista, {r['avisos']} avisos.")
    for av in r["lista_avisos"][:10]:
        print("  aviso:", av)


def cmd_importar(a, repo):
    r = importar_link(montagem.FONTES, repo, a.url)
    im = repo.buscar_imovel(r["id"])
    lei = im.get("leilao") or {}
    print(f"Importado: {im['fonte']} {im['id_fonte']} | {im['cidade']} | {im['tipo']} | {_brl(im['preco'])} | "
          f"{lei.get('tipo_venda') or im['modalidade']} | próxima praça {im.get('proxima_praca') or '-'}")
    for av in r["avisos"]:
        print("  aviso:", av)


def cmd_listar(a, repo):
    f = FiltroImoveis(uf=a.uf.upper() if a.uf else None, categorias=[a.categoria.lower()] if a.categoria else [],
                      cidade=a.cidade, tipo=a.tipo, desconto_min=a.desconto_min, preco_max=a.preco_max,
                      sem_alertas=a.sem_alertas, ordem="desconto", limite=a.limite)
    total, linhas = repo.listar_imoveis(f)
    for r in linhas:
        alertas = ",".join(r["alertas"])
        marca = "!" if alertas else " "
        print(f"{marca}{r['id_fonte']:>15} | {r['cidade'][:22]:<22} | {(r['tipo'] or '?')[:12]:<12} | "
              f"{_brl(r['preco']):>14} | aval. {_brl(r['valor_avaliacao']):>14} | "
              f"{(r['desconto_pct'] or 0):5.1f}% | {r['modalidade'][:24]}"
              + (f" | alertas: {alertas}" if alertas else ""))
    print(f"{total} imóveis (mostrando até {a.limite}). '!' = imóvel com alerta.")


def cmd_novidades(a, repo):
    ult = repo.ultima_coleta()
    if not ult:
        print("Nenhuma coleta registrada."); return
    print(f"Coleta {ult['id']} em {ult['quando']} ({ult['fonte']} {ult['recorte']}): "
          f"{ult['novos']} novos, {ult['alterados']} alterados, {ult['saidos']} saíram.")
    for h in repo.eventos_da_coleta(ult["id"], a.limite):
        det = f" {h['campo']}: {h['valor_antigo']} -> {h['valor_novo']}" if h["campo"] else ""
        print(f"  {h['evento']:<14} {h['id_fonte']} ({h['cidade']}){det}")


def cmd_duplicados(a, repo):
    grupos = repo.possiveis_duplicados()
    for g in grupos:
        print("Possível mesmo imóvel (confirmar manualmente):")
        for r in g:
            print(f"  {r['fonte']} {r['id_fonte']} | {r['cidade']} | {r['endereco']} | {_brl(r['preco'])}")
    print(f"{len(grupos)} grupos.")


def cmd_exportar(a, repo):
    colunas, linhas = repo.exportar()
    with open(a.destino, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(colunas)
        n = 0
        for r in linhas:
            w.writerow(list(r)); n += 1
    print(f"{n} imóveis exportados para {a.destino}.")


def cmd_tela(a):
    from . import tela
    return tela.rodar(a.base, a.porta, not a.sem_navegador)


def main(argv=None):
    p = argparse.ArgumentParser(prog="captacao", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base", default="captacao.db", help="arquivo da base (padrão: captacao.db)")
    s = p.add_subparsers(dest="cmd", required=True)
    s.add_parser("fontes").set_defaults(f=cmd_fontes)
    c = s.add_parser("coletar"); c.add_argument("--fonte", default="caixa")
    c.add_argument("--recorte", help="parte da fonte (ex.: UF)"); c.add_argument("--uf", help="o mesmo que --recorte")
    c.add_argument("--arquivo"); c.add_argument("--limite", type=int, help="no máximo N imóveis (para testar)")
    c.set_defaults(f=cmd_coletar)
    imp = s.add_parser("importar"); imp.add_argument("url"); imp.set_defaults(f=cmd_importar)
    l = s.add_parser("listar"); l.add_argument("--uf"); l.add_argument("--cidade"); l.add_argument("--tipo")
    l.add_argument("--categoria", help="casa, apartamento, terreno, comercial, rural, outros")
    l.add_argument("--desconto-min", type=float); l.add_argument("--preco-max", type=float)
    l.add_argument("--sem-alertas", action="store_true", help="esconde imóveis com alerta")
    l.add_argument("--limite", type=int, default=30); l.set_defaults(f=cmd_listar)
    n = s.add_parser("novidades"); n.add_argument("--limite", type=int, default=50); n.set_defaults(f=cmd_novidades)
    s.add_parser("duplicados").set_defaults(f=cmd_duplicados)
    e = s.add_parser("exportar"); e.add_argument("destino"); e.set_defaults(f=cmd_exportar)
    t = s.add_parser("tela"); t.add_argument("--porta", type=int, default=8765)
    t.add_argument("--sem-navegador", action="store_true", help="não abre o navegador")
    t.set_defaults(f=cmd_tela)
    a = p.parse_args(argv)
    if a.cmd == "tela":                  # não cria base vazia se o caminho estiver errado
        return cmd_tela(a)
    if a.cmd == "fontes":
        return cmd_fontes(a, None) or 0
    with montagem.repositorio(a.base) as repo:
        try:
            return a.f(a, repo) or 0
        except (ErroDeFonte, EntradaInvalida, OSError) as erro:
            print("Erro:", erro, file=sys.stderr); return 1


if __name__ == "__main__":
    sys.exit(main())
