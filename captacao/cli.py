"""Uso:
  python -m captacao fontes                          lista as fontes e seus recortes
  python -m captacao coletar --uf SP                 baixa a lista da Caixa e atualiza a base
  python -m captacao coletar --uf SP --arquivo x.csv usa um arquivo baixado pelo navegador
  python -m captacao coletar --fonte caixa --recorte SP   forma geral, para qualquer fonte
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
from .aplicacao.coletar import coletar
from .aplicacao.portas import ErroDeFonte
from .dominio.normaliza import chave


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
    r = coletar(f, repo, recorte, arquivo, a.arquivo or "")
    rotulo = f"{f.nome} {r['recorte']}".strip()
    print(f"Coleta {r['coleta']} ({rotulo}): {r['total']} imóveis lidos, {r['novos']} novos, "
          f"{r['alterados']} alterados, {r['saidos']} saíram da lista, {r['avisos']} avisos.")
    for av in r["lista_avisos"][:10]:
        print("  aviso:", av)


def cmd_listar(a, repo):
    con = repo.con
    sql, p = "SELECT * FROM imoveis WHERE situacao='ativo'", []
    if a.uf:
        sql += " AND uf=?"; p.append(a.uf.upper())
    if a.categoria:
        sql += " AND categoria=?"; p.append(a.categoria.lower())
    if a.sem_alertas:
        sql += " AND COALESCE(alertas,'')=''"
    if a.desconto_min is not None:
        sql += " AND desconto_pct>=?"; p.append(a.desconto_min)
    if a.preco_max is not None:
        sql += " AND preco<=?"; p.append(a.preco_max)
    linhas = [r for r in con.execute(sql + " ORDER BY desconto_pct DESC", p)
              if (not a.cidade or chave(a.cidade) in chave(r["cidade"]))
              and (not a.tipo or chave(a.tipo) in (r["tipo"] or ""))]
    for r in linhas[:a.limite]:
        marca = "!" if r["alertas"] else " "
        print(f"{marca}{r['id_fonte']:>15} | {r['cidade'][:22]:<22} | {(r['tipo'] or '?')[:12]:<12} | "
              f"{_brl(r['preco']):>14} | aval. {_brl(r['valor_avaliacao']):>14} | "
              f"{(r['desconto_pct'] or 0):5.1f}% | {r['modalidade'][:24]}"
              + (f" | alertas: {r['alertas']}" if r["alertas"] else ""))
    print(f"{len(linhas)} imóveis (mostrando até {a.limite}). '!' = imóvel com alerta.")


def cmd_novidades(a, repo):
    con = repo.con
    ult = con.execute("SELECT * FROM coletas ORDER BY id DESC LIMIT 1").fetchone()
    if not ult:
        print("Nenhuma coleta registrada."); return
    print(f"Coleta {ult['id']} em {ult['quando']} ({ult['fonte']} {ult['recorte']}): "
          f"{ult['novos']} novos, {ult['alterados']} alterados, {ult['saidos']} saíram.")
    for h in con.execute("SELECT h.*, i.id_fonte, i.cidade FROM historico h JOIN imoveis i "
                         "ON i.id=h.imovel_id WHERE h.coleta_id=? AND h.evento<>'novo' "
                         "ORDER BY h.id LIMIT ?", (ult["id"], a.limite)):
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
    con = repo.con
    cur = con.execute("SELECT * FROM imoveis ORDER BY uf, cidade")
    with open(a.destino, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow([c[0] for c in cur.description])
        n = 0
        for r in cur:
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
    c.add_argument("--arquivo"); c.set_defaults(f=cmd_coletar)
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
        except (ErroDeFonte, OSError) as erro:
            print("Erro:", erro, file=sys.stderr); return 1


if __name__ == "__main__":
    sys.exit(main())
