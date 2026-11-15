"""Base central em SQLite: imóveis, histórico de mudanças e registro de cada coleta."""
import sqlite3
from datetime import datetime
from typing import Iterable, List

from .modelo import ImovelCaptado
from .normaliza import chave_endereco

ESQUEMA = """
CREATE TABLE IF NOT EXISTS imoveis (
  id INTEGER PRIMARY KEY,
  fonte TEXT NOT NULL, id_fonte TEXT NOT NULL,
  uf TEXT, cidade TEXT, bairro TEXT, endereco TEXT,
  preco REAL, valor_avaliacao REAL, desconto_pct REAL, modalidade TEXT,
  tipo TEXT, area_privativa REAL, area_terreno REAL, area_total REAL, descricao TEXT, link TEXT, data_fonte TEXT,
  categoria TEXT, alertas TEXT,
  chave_endereco TEXT,
  situacao TEXT NOT NULL DEFAULT 'ativo',      -- ativo | saiu_da_lista
  estagio TEXT NOT NULL DEFAULT 'identificado', -- identificado | analisar | depois | descartado
  primeira_vez TEXT NOT NULL, ultima_vez TEXT NOT NULL,
  UNIQUE (fonte, id_fonte)
);
CREATE INDEX IF NOT EXISTS ix_imoveis_chave ON imoveis (chave_endereco);
CREATE TABLE IF NOT EXISTS historico (
  id INTEGER PRIMARY KEY, imovel_id INTEGER NOT NULL REFERENCES imoveis(id),
  coleta_id INTEGER NOT NULL, quando TEXT NOT NULL,
  evento TEXT NOT NULL,                         -- novo | alterado | saiu_da_lista | voltou
  campo TEXT, valor_antigo TEXT, valor_novo TEXT
);
CREATE TABLE IF NOT EXISTS triagens (            -- toda mudança de estágio; nunca apagar
  id INTEGER PRIMARY KEY, imovel_id INTEGER NOT NULL REFERENCES imoveis(id),
  de TEXT NOT NULL, para TEXT NOT NULL, nota TEXT, quando TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_triagens_imovel ON triagens (imovel_id);
CREATE TABLE IF NOT EXISTS investigacao (        -- checklist; cada mudança é uma linha nova
  id INTEGER PRIMARY KEY, imovel_id INTEGER NOT NULL REFERENCES imoveis(id),
  item TEXT NOT NULL, status TEXT NOT NULL, nota TEXT, quando TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_investigacao_imovel ON investigacao (imovel_id, item);
CREATE TABLE IF NOT EXISTS anexos (              -- arquivos enviados à mão (matrícula, edital...)
  id INTEGER PRIMARY KEY, imovel_id INTEGER NOT NULL REFERENCES imoveis(id),
  tipo TEXT NOT NULL, nome_original TEXT NOT NULL, arquivo TEXT NOT NULL,
  tamanho INTEGER NOT NULL, sha256 TEXT NOT NULL, quando TEXT NOT NULL, leitura TEXT
);
CREATE INDEX IF NOT EXISTS ix_anexos_imovel ON anexos (imovel_id);
CREATE TABLE IF NOT EXISTS anexo_paginas (       -- texto extraído de cada página dos PDFs
  anexo_id INTEGER NOT NULL REFERENCES anexos(id), pagina INTEGER NOT NULL, texto TEXT NOT NULL,
  PRIMARY KEY (anexo_id, pagina)
);
CREATE TABLE IF NOT EXISTS simulacoes (          -- simulações salvas; a mais recente vale
  id INTEGER PRIMARY KEY, imovel_id INTEGER NOT NULL REFERENCES imoveis(id),
  premissas TEXT NOT NULL, resultado TEXT NOT NULL, quando TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_simulacoes_imovel ON simulacoes (imovel_id);
CREATE TABLE IF NOT EXISTS coletas (
  id INTEGER PRIMARY KEY, fonte TEXT, recorte TEXT, origem TEXT, quando TEXT,
  total INTEGER, novos INTEGER, alterados INTEGER, saidos INTEGER, avisos INTEGER
);
"""
ESTAGIOS = ("identificado", "analisar", "depois", "descartado")
CAMPOS = ("uf", "cidade", "bairro", "endereco", "preco", "valor_avaliacao", "desconto_pct",
          "modalidade", "tipo", "area_privativa", "area_terreno", "area_total", "descricao", "link", "data_fonte",
          "categoria", "alertas")


# Colunas acrescentadas depois da primeira versão: (tabela, coluna, tipo SQL).
# Base antiga ganha a coluna vazia; o valor é preenchido na próxima coleta ou por
# ferramentas/reprocessar_descricao.py.
COLUNAS_NOVAS = [
    ("imoveis", "area_total", "REAL"),
    ("imoveis", "categoria", "TEXT"),
    ("imoveis", "alertas", "TEXT"),
    ("anexos", "leitura", "TEXT"),        # lido | sem_texto | erro | desligada | imagem
]


# Tabelas criadas depois da primeira versão (o CREATE está em ESQUEMA).
TABELAS_NOVAS = ("triagens", "investigacao", "anexos", "simulacoes", "anexo_paginas")


def conectar(caminho: str) -> sqlite3.Connection:
    con = sqlite3.connect(caminho, timeout=10)
    con.row_factory = sqlite3.Row
    _copiar_se_for_migrar(con, caminho)
    con.executescript(ESQUEMA)
    for t, c, tipo in _colunas_faltando(con):
        con.execute(f"ALTER TABLE {t} ADD COLUMN {c} {tipo}")
    con.commit()
    return con


def _colunas_faltando(con):
    return [(t, c, tipo) for t, c, tipo in COLUNAS_NOVAS
            if c not in {r["name"] for r in con.execute(f"PRAGMA table_info({t})")}]


def _copiar_se_for_migrar(con, caminho: str) -> None:
    """Base existente que vai ganhar tabela ou coluna nova: copia antes de mexer."""
    tabelas = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if caminho == ":memory:" or "imoveis" not in tabelas:   # base nova: nada a preservar
        return
    if not (set(TABELAS_NOVAS) - tabelas or _colunas_faltando(con)):
        return
    destino = f"{caminho}.antes_migracao_{datetime.now():%Y%m%d_%H%M%S}"
    with sqlite3.connect(destino) as copia:
        con.backup(copia)
    copia.close()


def gravar_coleta(con, fonte: str, recorte: str, origem: str,
                  imoveis: Iterable[ImovelCaptado], n_avisos: int = 0, agora: str = None) -> dict:
    """Compara a coleta com a base. `recorte` (ex.: 'SP') limita quem pode ser marcado
    como 'saiu_da_lista': só imóveis da mesma fonte e do mesmo recorte."""
    agora = agora or datetime.now().isoformat(timespec="seconds")
    imoveis = list(imoveis)
    cur = con.execute("INSERT INTO coletas (fonte, recorte, origem, quando, total, avisos) "
                      "VALUES (?,?,?,?,?,?)", (fonte, recorte, origem, agora, len(imoveis), n_avisos))
    coleta = cur.lastrowid
    novos = alterados = 0
    vistos = set()

    def hist(imovel_id, evento, campo=None, antigo=None, novo=None):
        con.execute("INSERT INTO historico (imovel_id, coleta_id, quando, evento, campo, "
                    "valor_antigo, valor_novo) VALUES (?,?,?,?,?,?,?)",
                    (imovel_id, coleta, agora, evento, campo,
                     None if antigo is None else str(antigo), None if novo is None else str(novo)))

    for im in imoveis:
        if im.id_fonte in vistos:        # repetido dentro do mesmo arquivo
            continue
        vistos.add(im.id_fonte)
        d = im.como_dict()
        ch = chave_endereco(im.uf, im.cidade, im.endereco)
        atual = con.execute("SELECT * FROM imoveis WHERE fonte=? AND id_fonte=?",
                            (im.fonte, im.id_fonte)).fetchone()
        if atual is None:
            cols = ("fonte", "id_fonte") + CAMPOS + ("chave_endereco", "primeira_vez", "ultima_vez")
            vals = [im.fonte, im.id_fonte] + [d[c] for c in CAMPOS] + [ch, agora, agora]
            cur = con.execute(f"INSERT INTO imoveis ({','.join(cols)}) "
                              f"VALUES ({','.join('?' * len(cols))})", vals)
            hist(cur.lastrowid, "novo")
            novos += 1
            continue
        mudou = False
        for campo in ImovelCaptado.CAMPOS_MONITORADOS:
            if atual[campo] != d[campo]:
                hist(atual["id"], "alterado", campo, atual[campo], d[campo])
                mudou = True
        if atual["situacao"] == "saiu_da_lista":
            hist(atual["id"], "voltou")
            mudou = True
        alterados += mudou
        sets = ",".join(f"{c}=?" for c in CAMPOS)
        con.execute(f"UPDATE imoveis SET {sets}, chave_endereco=?, situacao='ativo', ultima_vez=? "
                    "WHERE id=?", [d[c] for c in CAMPOS] + [ch, agora, atual["id"]])

    saidos = 0
    if imoveis:   # coleta vazia não derruba a base inteira: provável falha da fonte
        for r in con.execute("SELECT id, id_fonte FROM imoveis WHERE fonte=? AND uf=? "
                             "AND situacao='ativo'", (fonte, recorte)).fetchall():
            if r["id_fonte"] not in vistos:
                con.execute("UPDATE imoveis SET situacao='saiu_da_lista' WHERE id=?", (r["id"],))
                hist(r["id"], "saiu_da_lista")
                saidos += 1
    con.execute("UPDATE coletas SET novos=?, alterados=?, saidos=? WHERE id=?",
                (novos, alterados, saidos, coleta))
    con.commit()
    return {"coleta": coleta, "total": len(vistos), "novos": novos,
            "alterados": alterados, "saidos": saidos, "avisos": n_avisos}


def possiveis_duplicados(con) -> List[list]:
    """Grupos de imóveis ativos com o mesmo endereço normalizado. Sugestão, não certeza."""
    grupos = []
    for g in con.execute("SELECT chave_endereco FROM imoveis WHERE situacao='ativo' "
                         "AND chave_endereco NOT LIKE '%|' GROUP BY chave_endereco "
                         "HAVING COUNT(*)>1").fetchall():
        grupos.append([dict(r) for r in con.execute(
            "SELECT id, fonte, id_fonte, cidade, endereco, preco FROM imoveis "
            "WHERE chave_endereco=? AND situacao='ativo'", (g[0],))])
    return grupos
