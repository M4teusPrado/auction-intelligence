"""Adaptador de persistência em SQLite: imóveis, histórico de mudanças, coletas e análise.

Único lugar do sistema com SQL. Implementa as portas de repositório (aplicacao/portas.py).
"""
import json
import sqlite3
from datetime import datetime
from typing import Iterable, List, Optional

from ...dominio.modelo import ImovelCaptado
from ...dominio.normaliza import chave, chave_endereco

ESQUEMA = """
CREATE TABLE IF NOT EXISTS imoveis (
  id INTEGER PRIMARY KEY,
  fonte TEXT NOT NULL, id_fonte TEXT NOT NULL, recorte TEXT,
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
CREATE TABLE IF NOT EXISTS leiloes (             -- dados de leilão do anúncio, como vieram da fonte
  imovel_id INTEGER PRIMARY KEY REFERENCES imoveis(id),
  tipo_venda TEXT, leilao TEXT, lote TEXT, comitente TEXT, leiloeiro TEXT, ocupacao TEXT,
  matricula TEXT, cartorio TEXT, processo TEXT, vara TEXT, comissao_pct REAL, incremento REAL
);
CREATE TABLE IF NOT EXISTS pracas (
  imovel_id INTEGER NOT NULL REFERENCES imoveis(id), numero INTEGER NOT NULL,
  data TEXT, valor REAL, PRIMARY KEY (imovel_id, numero)
);
CREATE INDEX IF NOT EXISTS ix_pracas_data ON pracas (data);
CREATE TABLE IF NOT EXISTS documentos_fonte (    -- links de edital/matrícula publicados pela fonte
  imovel_id INTEGER NOT NULL REFERENCES imoveis(id), tipo TEXT NOT NULL, url TEXT NOT NULL, rotulo TEXT,
  PRIMARY KEY (imovel_id, url)
);
CREATE TABLE IF NOT EXISTS pareceres (           -- pareceres preliminares gerados por IA; nada é apagado
  id INTEGER PRIMARY KEY, imovel_id INTEGER NOT NULL REFERENCES imoveis(id), modelo TEXT NOT NULL,
  parecer TEXT NOT NULL, uso TEXT, documentos TEXT, quando TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_pareceres_imovel ON pareceres (imovel_id);
CREATE TABLE IF NOT EXISTS coletas (
  id INTEGER PRIMARY KEY, fonte TEXT, recorte TEXT, origem TEXT, quando TEXT,
  total INTEGER, novos INTEGER, alterados INTEGER, saidos INTEGER, avisos INTEGER
);
"""
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
    ("imoveis", "recorte", "TEXT"),       # parte da fonte em que o imóvel apareceu (ex.: UF)
]


# Tabelas criadas depois da primeira versão (o CREATE está em ESQUEMA).
TABELAS_NOVAS = ("triagens", "investigacao", "anexos", "simulacoes", "anexo_paginas", "leiloes", "pracas",
                 "documentos_fonte", "pareceres")


def conectar(caminho: str) -> sqlite3.Connection:
    con = sqlite3.connect(caminho, timeout=10)
    con.row_factory = sqlite3.Row
    _copiar_se_for_migrar(con, caminho)
    con.executescript(ESQUEMA)
    for t, c, tipo in _colunas_faltando(con):
        con.execute(f"ALTER TABLE {t} ADD COLUMN {c} {tipo}")
    # dados antigos: antes da coluna recorte só havia a Caixa, coletada por UF
    con.execute("UPDATE imoveis SET recorte=uf WHERE recorte IS NULL AND fonte='caixa'")
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


_CAMPOS_LEILAO = ("tipo_venda", "leilao", "lote", "comitente", "leiloeiro", "ocupacao", "matricula", "cartorio",
                  "processo", "vara", "comissao_pct", "incremento")


def _gravar_leilao(con, imovel_id: int, lei) -> None:
    """Substitui os dados de leilão do anúncio pelos da coleta (são da fonte, não de pessoas)."""
    if lei is None:
        return
    con.execute(f"INSERT OR REPLACE INTO leiloes (imovel_id, {', '.join(_CAMPOS_LEILAO)}) "
                f"VALUES ({', '.join('?' * (len(_CAMPOS_LEILAO) + 1))})",
                [imovel_id] + [getattr(lei, c) for c in _CAMPOS_LEILAO])
    con.execute("DELETE FROM pracas WHERE imovel_id=?", (imovel_id,))
    con.executemany("INSERT OR REPLACE INTO pracas (imovel_id, numero, data, valor) VALUES (?,?,?,?)",
                    [(imovel_id, p.numero, p.data, p.valor) for p in lei.pracas])
    con.execute("DELETE FROM documentos_fonte WHERE imovel_id=?", (imovel_id,))
    con.executemany("INSERT OR IGNORE INTO documentos_fonte (imovel_id, tipo, url, rotulo) VALUES (?,?,?,?)",
                    [(imovel_id, doc.tipo, doc.url, doc.rotulo) for doc in lei.documentos])


def _gravar_coleta(con, fonte: str, recorte: str, origem: str,
                   imoveis: Iterable[ImovelCaptado], n_avisos: int = 0, agora: Optional[str] = None,
                   marcar_saidos: bool = True) -> dict:
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
            cols = ("fonte", "id_fonte", "recorte") + CAMPOS + ("chave_endereco", "primeira_vez", "ultima_vez")
            vals = [im.fonte, im.id_fonte, recorte] + [d[c] for c in CAMPOS] + [ch, agora, agora]
            cur = con.execute(f"INSERT INTO imoveis ({','.join(cols)}) "
                              f"VALUES ({','.join('?' * len(cols))})", vals)
            hist(cur.lastrowid, "novo")
            _gravar_leilao(con, cur.lastrowid, im.leilao)
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
        con.execute(f"UPDATE imoveis SET {sets}, recorte=?, chave_endereco=?, situacao='ativo', ultima_vez=? "
                    "WHERE id=?", [d[c] for c in CAMPOS] + [recorte, ch, agora, atual["id"]])
        _gravar_leilao(con, atual["id"], im.leilao)

    saidos = 0
    if imoveis and marcar_saidos:   # coleta vazia não derruba a base inteira: provável falha da fonte
        for r in con.execute("SELECT id, id_fonte FROM imoveis WHERE fonte=? AND recorte=? "
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


def _possiveis_duplicados(con) -> List[list]:
    """Grupos de imóveis ativos com o mesmo endereço normalizado. Sugestão, não certeza."""
    grupos = []
    for g in con.execute("SELECT chave_endereco FROM imoveis WHERE situacao='ativo' "
                         "AND chave_endereco NOT LIKE '%|' GROUP BY chave_endereco "
                         "HAVING COUNT(*)>1").fetchall():
        grupos.append([dict(r) for r in con.execute(
            "SELECT id, fonte, id_fonte, cidade, endereco, preco FROM imoveis "
            "WHERE chave_endereco=? AND situacao='ativo'", (g[0],))])
    return grupos


class RepositorioSQLite:
    """Implementa as portas de repositório sobre um arquivo SQLite. Use com `with`."""

    def __init__(self, caminho: str, migrar: bool = True):
        """migrar=False abre sem conferir o esquema (para requisições, depois de migrado na partida)."""
        self.caminho = caminho
        if migrar:
            self.con = conectar(caminho)
        else:
            self.con = sqlite3.connect(caminho, timeout=10)
            self.con.row_factory = sqlite3.Row

    def close(self) -> None:
        self.con.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def gravar_coleta(self, fonte: str, recorte: str, origem: str, imoveis: Iterable[ImovelCaptado],
                      n_avisos: int = 0, agora: Optional[str] = None, marcar_saidos: bool = True) -> dict:
        """Compara a coleta com a base. Só imóveis da mesma fonte e do mesmo recorte
        podem ser marcados como 'saiu_da_lista', e só se a coleta foi completa."""
        return _gravar_coleta(self.con, fonte, recorte, origem, imoveis, n_avisos, agora, marcar_saidos)

    def gravar_avulso(self, imovel: ImovelCaptado, origem: str, agora: Optional[str] = None) -> int:
        """Grava um imóvel importado por link, sem marcar os outros como 'saiu da lista'."""
        _gravar_coleta(self.con, imovel.fonte, imovel.uf, origem, [imovel], 0, agora, marcar_saidos=False)
        return self.con.execute("SELECT id FROM imoveis WHERE fonte=? AND id_fonte=?",
                                (imovel.fonte, imovel.id_fonte)).fetchone()[0]

    def possiveis_duplicados(self) -> List[list]:
        return _possiveis_duplicados(self.con)

    # ------------------------------------------------------------------ consulta
    # Colunas devolvidas para a tela; a nota é a da triagem mais recente.
    _COLUNAS_IMOVEL = """
      id, fonte, id_fonte, recorte, uf, cidade, bairro, endereco, preco, valor_avaliacao, desconto_pct,
      modalidade, tipo, categoria, area_privativa, area_terreno, area_total, link, data_fonte,
      alertas, situacao, estagio, primeira_vez, ultima_vez,
      (SELECT nota FROM triagens t WHERE t.imovel_id = imoveis.id ORDER BY t.id DESC LIMIT 1) AS nota,
      (SELECT tipo_venda FROM leiloes l WHERE l.imovel_id = imoveis.id) AS tipo_venda,
      (SELECT ocupacao FROM leiloes l WHERE l.imovel_id = imoveis.id) AS ocupacao,
      (SELECT comitente FROM leiloes l WHERE l.imovel_id = imoveis.id) AS comitente,
      (SELECT MIN(data) FROM pracas p WHERE p.imovel_id = imoveis.id AND p.data >= strftime('%Y-%m-%dT%H:%M', 'now', 'localtime')) AS proxima_praca,
      (SELECT valor FROM pracas p WHERE p.imovel_id = imoveis.id AND p.data >= strftime('%Y-%m-%dT%H:%M', 'now', 'localtime') ORDER BY p.data LIMIT 1)
        AS proxima_praca_valor
    """
    _ORDENS = {   # nulos sempre no fim; id desempata para a paginação ser estável
        "desconto": "desconto_pct IS NULL, desconto_pct DESC, id",
        "preco": "preco IS NULL, preco ASC, id",
        "area_terreno": "area_terreno IS NULL, area_terreno DESC, id",
        "recente": "primeira_vez DESC, id DESC",
        "leilao": "proxima_praca IS NULL, proxima_praca ASC, id",
    }

    @staticmethod
    def _imovel(r) -> dict:
        d = dict(r)
        d["alertas"] = [a for a in (d.get("alertas") or "").split(",") if a]
        return d

    def listar_imoveis(self, f) -> tuple:
        """(total, página de imóveis) para um FiltroImoveis. Só imóveis ativos."""
        self.con.create_function("chave", 1, chave, deterministic=True)
        where, args = ["situacao = 'ativo'"], []
        def em(coluna, valores):
            where.append(f"{coluna} IN ({','.join('?' * len(valores))})"); args.extend(valores)
        if f.estagio:
            where.append("estagio = ?"); args.append(f.estagio)
        if f.fontes:
            em("fonte", f.fontes)
        if f.uf:
            where.append("uf = ?"); args.append(f.uf)
        if f.modalidades:
            em("modalidade", f.modalidades)
        if f.categorias:
            em("categoria", f.categorias)
        if f.cidades:
            where.append("(" + " OR ".join("chave(cidade) LIKE ?" for _ in f.cidades) + ")")
            args.extend(f"%{chave(c)}%" for c in f.cidades)
        if f.tipo:
            where.append("chave(COALESCE(tipo, '')) LIKE ?"); args.append(f"%{chave(f.tipo)}%")
        for valor, expr in ((f.preco_min, "preco >= ?"), (f.preco_max, "preco <= ?"),
                            (f.desconto_min, "desconto_pct >= ?"), (f.area_terreno_min, "area_terreno >= ?")):
            if valor is not None:
                where.append(expr); args.append(valor)
        if f.sem_alertas:
            where.append("COALESCE(alertas, '') = ''")
        cond = " AND ".join(where)
        total = self.con.execute(f"SELECT COUNT(*) FROM imoveis WHERE {cond}", args).fetchone()[0]
        linhas = self.con.execute(
            f"SELECT {self._COLUNAS_IMOVEL} FROM imoveis WHERE {cond} ORDER BY {self._ORDENS[f.ordem]} "
            "LIMIT ? OFFSET ?", args + [f.limite, f.deslocamento]).fetchall()
        return total, [self._imovel(r) for r in linhas]

    def buscar_imovel(self, imovel_id: int) -> Optional[dict]:
        r = self.con.execute(f"SELECT {self._COLUNAS_IMOVEL} FROM imoveis WHERE id=?", (imovel_id,)).fetchone()
        if not r:
            return None
        im = self._imovel(r)
        im["descricao"] = self.con.execute("SELECT descricao FROM imoveis WHERE id=?", (imovel_id,)).fetchone()[0] or ""
        lei = self.con.execute("SELECT * FROM leiloes WHERE imovel_id=?", (imovel_id,)).fetchone()
        im["leilao"] = None if not lei else {
            **{k: lei[k] for k in lei.keys() if k != "imovel_id"},
            "pracas": [dict(p) for p in self.con.execute(
                "SELECT numero, data, valor FROM pracas WHERE imovel_id=? ORDER BY numero", (imovel_id,))],
            "documentos": [dict(d) for d in self.con.execute(
                "SELECT tipo, url, rotulo FROM documentos_fonte WHERE imovel_id=? ORDER BY tipo", (imovel_id,))]}
        return im

    def contar_por_estagio(self) -> dict:
        return dict(self.con.execute("SELECT estagio, COUNT(*) FROM imoveis WHERE situacao='ativo' GROUP BY estagio"))

    def ultima_coleta(self) -> Optional[dict]:
        ult = self.con.execute("SELECT * FROM coletas ORDER BY id DESC LIMIT 1").fetchone()
        if not ult:
            return None
        quedas = self.con.execute(
            "SELECT COUNT(*) FROM historico WHERE coleta_id=? AND evento='alterado' "
            "AND campo='preco' AND CAST(valor_novo AS REAL) < CAST(valor_antigo AS REAL)", (ult["id"],)).fetchone()[0]
        data_fonte = self.con.execute(
            "SELECT data_fonte FROM imoveis WHERE fonte=? AND recorte=? ORDER BY ultima_vez DESC LIMIT 1",
            (ult["fonte"], ult["recorte"])).fetchone()
        return {**dict(ult), "quedas_preco": quedas, "data_fonte": data_fonte[0] if data_fonte else None}

    def eventos_da_coleta(self, coleta_id: int, limite: int) -> List[dict]:
        """Mudanças de uma coleta, exceto imóveis novos."""
        return [dict(r) for r in self.con.execute(
            "SELECT h.evento, h.campo, h.valor_antigo, h.valor_novo, i.id_fonte, i.cidade FROM historico h "
            "JOIN imoveis i ON i.id=h.imovel_id WHERE h.coleta_id=? AND h.evento<>'novo' ORDER BY h.id LIMIT ?",
            (coleta_id, limite))]

    def opcoes(self) -> dict:
        def contar(coluna, ordem):
            return [{"valor": v, "n": n} for v, n in self.con.execute(
                f"SELECT {coluna}, COUNT(*) FROM imoveis WHERE situacao='ativo' AND {coluna} IS NOT NULL "
                f"AND {coluna} <> '' GROUP BY {coluna} ORDER BY {ordem}")]
        return {"fontes": contar("fonte", "2 DESC, 1"), "modalidades": contar("modalidade", "2 DESC, 1"),
                "categorias": contar("categoria", "2 DESC, 1"), "cidades": contar("cidade", "1")}

    def historico(self, imovel_id: int) -> List[dict]:
        return [dict(r) for r in self.con.execute(
            "SELECT quando, evento, campo, valor_antigo, valor_novo FROM historico WHERE imovel_id=? ORDER BY id",
            (imovel_id,))]

    def exportar(self) -> tuple:
        """(nomes das colunas, linhas) de todos os imóveis."""
        cur = self.con.execute("SELECT * FROM imoveis ORDER BY uf, cidade")
        return [c[0] for c in cur.description], cur

    # ------------------------------------------------------------------ triagem
    def triagens(self, imovel_id: int) -> List[dict]:
        return [dict(r) for r in self.con.execute(
            "SELECT id, de, para, nota, quando FROM triagens WHERE imovel_id=? ORDER BY id", (imovel_id,))]

    def ultima_triagem(self, imovel_id: int) -> Optional[dict]:
        r = self.con.execute("SELECT id, de, para, nota, quando FROM triagens WHERE imovel_id=? "
                             "ORDER BY id DESC LIMIT 1", (imovel_id,)).fetchone()
        return dict(r) if r else None

    def registrar_triagem(self, imovel_id: int, de: str, para: str, nota: Optional[str], quando: str) -> int:
        """Grava a mudança de estágio (nunca apaga) e atualiza o estágio do imóvel."""
        cur = self.con.execute("INSERT INTO triagens (imovel_id, de, para, nota, quando) VALUES (?,?,?,?,?)",
                               (imovel_id, de, para, nota, quando))
        self.con.execute("UPDATE imoveis SET estagio=? WHERE id=?", (para, imovel_id))
        self.con.commit()
        return cur.lastrowid

    # ------------------------------------------------------------------ investigação
    def investigacao_atual(self, imovel_id: int) -> dict:
        """Situação mais recente de cada item: {item: {status, nota, quando}}."""
        return {r["item"]: dict(r) for r in self.con.execute(
            "SELECT item, status, nota, quando FROM investigacao WHERE id IN "
            "(SELECT MAX(id) FROM investigacao WHERE imovel_id=? GROUP BY item)", (imovel_id,))}

    def registrar_investigacao(self, imovel_id: int, item: str, status: str, nota: Optional[str], quando: str) -> None:
        self.con.execute("INSERT INTO investigacao (imovel_id, item, status, nota, quando) VALUES (?,?,?,?,?)",
                         (imovel_id, item, status, nota, quando))
        self.con.commit()

    # ------------------------------------------------------------------ anexos
    def anexos(self, imovel_id: int) -> List[dict]:
        return [dict(r) for r in self.con.execute(
            "SELECT id, tipo, nome_original, tamanho, quando, leitura FROM anexos WHERE imovel_id=? ORDER BY id DESC",
            (imovel_id,))]

    def anexo_por_conteudo(self, imovel_id: int, sha256: str) -> Optional[int]:
        r = self.con.execute("SELECT id FROM anexos WHERE imovel_id=? AND sha256=?", (imovel_id, sha256)).fetchone()
        return r[0] if r else None

    def inserir_anexo(self, imovel_id: int, tipo: str, nome: str, arquivo: str, tamanho: int,
                      sha256: str, quando: str) -> int:
        cur = self.con.execute("INSERT INTO anexos (imovel_id, tipo, nome_original, arquivo, tamanho, sha256, quando) "
                               "VALUES (?,?,?,?,?,?,?)", (imovel_id, tipo, nome, arquivo, tamanho, sha256, quando))
        self.con.commit()
        return cur.lastrowid

    def anexo(self, anexo_id: int) -> Optional[dict]:
        r = self.con.execute("SELECT id, imovel_id, arquivo, nome_original, tipo FROM anexos WHERE id=?",
                             (anexo_id,)).fetchone()
        return dict(r) if r else None

    def anexos_sem_leitura(self, imovel_id: int) -> List[dict]:
        return [dict(r) for r in self.con.execute(
            "SELECT id, arquivo FROM anexos WHERE imovel_id=? AND (leitura IS NULL OR leitura='desligada')",
            (imovel_id,))]

    def gravar_leitura(self, anexo_id: int, situacao: str, paginas: Optional[List[str]] = None) -> None:
        """Situação da leitura; com `paginas`, substitui o texto guardado do anexo."""
        if paginas is not None:
            self.con.execute("DELETE FROM anexo_paginas WHERE anexo_id=?", (anexo_id,))
            self.con.executemany("INSERT INTO anexo_paginas (anexo_id, pagina, texto) VALUES (?,?,?)",
                                 [(anexo_id, i, t) for i, t in enumerate(paginas, start=1)])
        self.con.execute("UPDATE anexos SET leitura=? WHERE id=?", (situacao, anexo_id))
        self.con.commit()

    def textos_lidos(self, imovel_id: int) -> List[dict]:
        """Anexos lidos com o texto de cada página: [{id, nome_original, paginas: [...]}]."""
        saida = []
        for a in self.con.execute("SELECT id, nome_original, leitura FROM anexos WHERE imovel_id=? "
                                  "AND leitura IN ('lido', 'transcrito_ia') ORDER BY id", (imovel_id,)).fetchall():
            paginas = [r[0] for r in self.con.execute(
                "SELECT texto FROM anexo_paginas WHERE anexo_id=? ORDER BY pagina", (a["id"],))]
            saida.append({"id": a["id"], "nome_original": a["nome_original"], "paginas": paginas,
                          "transcrito_ia": a["leitura"] == "transcrito_ia"})
        return saida

    # ------------------------------------------------------------------ simulações
    def ultima_simulacao(self, imovel_id: int) -> Optional[dict]:
        r = self.con.execute("SELECT premissas, quando FROM simulacoes WHERE imovel_id=? ORDER BY id DESC LIMIT 1",
                             (imovel_id,)).fetchone()
        return {"premissas": json.loads(r["premissas"]), "quando": r["quando"]} if r else None

    def salvar_simulacao(self, imovel_id: int, premissas: dict, resultado: dict, quando: str) -> None:
        self.con.execute("INSERT INTO simulacoes (imovel_id, premissas, resultado, quando) VALUES (?,?,?,?)",
                         (imovel_id, json.dumps(premissas), json.dumps(resultado, ensure_ascii=False), quando))
        self.con.commit()

    # ------------------------------------------------------------------ pareceres (IA)
    def salvar_parecer(self, imovel_id: int, modelo: str, parecer: dict, uso: dict, documentos: list, quando: str) -> None:
        self.con.execute("INSERT INTO pareceres (imovel_id, modelo, parecer, uso, documentos, quando) VALUES (?,?,?,?,?,?)",
                         (imovel_id, modelo, json.dumps(parecer, ensure_ascii=False), json.dumps(uso),
                          json.dumps(documentos, ensure_ascii=False), quando))
        self.con.commit()

    def ultimo_parecer(self, imovel_id: int) -> Optional[dict]:
        r = self.con.execute("SELECT modelo, parecer, uso, documentos, quando FROM pareceres WHERE imovel_id=? "
                             "ORDER BY id DESC LIMIT 1", (imovel_id,)).fetchone()
        if not r:
            return None
        return {"modelo": r["modelo"], "parecer": json.loads(r["parecer"]), "uso": json.loads(r["uso"] or "{}"),
                "documentos": json.loads(r["documentos"] or "[]"), "quando": r["quando"]}
