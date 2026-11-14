"""Preenche area_total, categoria e alertas de imóveis já gravados, a partir da
`descricao` guardada na base. Não baixa nada e não altera os campos da fonte
(tipo, áreas, preço): se a reextração divergir do que está gravado, só reporta.

Uso:  python ferramentas/reprocessar_descricao.py [--base captacao.db]
"""
import argparse
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from captacao import classifica, repositorio          # noqa: E402
from captacao.fontes import caixa                       # noqa: E402
from captacao.modelo import ImovelCaptado               # noqa: E402

EXTRATORES = {"caixa": caixa.tipo_e_areas}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--base", default="captacao.db")
    a = p.parse_args(argv)
    if not os.path.exists(a.base):
        print("Base não encontrada:", a.base, file=sys.stderr); return 1
    con = repositorio.conectar(a.base)      # migra o esquema (com cópia) se preciso
    campos = [f for f in ImovelCaptado.__dataclass_fields__ if f not in ("categoria", "alertas")]
    n, divergentes, sem_extrator = 0, [], Counter()
    for r in con.execute("SELECT * FROM imoveis").fetchall():
        extrair = EXTRATORES.get(r["fonte"])
        if not extrair:
            sem_extrator[r["fonte"]] += 1; continue
        tipo, priv, terr, total = extrair(r["descricao"] or "")
        if (tipo, priv, terr) != (r["tipo"], r["area_privativa"], r["area_terreno"]):
            divergentes.append((r["id_fonte"], (r["tipo"], r["area_privativa"], r["area_terreno"]),
                                (tipo, priv, terr)))
        d = {c: r[c] for c in campos if c != "area_total"}
        im = ImovelCaptado(area_total=total, **d)
        classifica.classificar([im])
        con.execute("UPDATE imoveis SET area_total=?, categoria=?, alertas=? WHERE id=?",
                    (im.area_total, im.categoria, im.alertas, r["id"]))
        n += 1
    con.commit()
    print(f"{n} imóveis reprocessados.")
    for f, k in sem_extrator.items():
        print(f"  {k} imóveis da fonte '{f}' ignorados (sem extrator).")
    print(f"{len(divergentes)} com tipo/áreas gravados diferentes da reextração (não alterados).")
    for d in divergentes[:20]:
        print("  ", d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
