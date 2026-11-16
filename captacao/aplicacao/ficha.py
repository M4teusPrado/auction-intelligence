"""Casos de uso da ficha do imóvel: montar a ficha, registrar a investigação, anexar
arquivos e simular. Nada é apagado: cada mudança é uma linha nova.

Recebem um RepositorioDeAnalise; não sabem de SQL nem de HTTP. Nenhuma busca na
internet: os anexos vêm do navegador de quem usa a tela.
(Arquivos em disco e leitura de PDF ainda são chamados daqui; viram portas na etapa 3.)
"""
import hashlib
import os
import re
from datetime import datetime

from .. import documentos
from ..dominio import simulador
from ..dominio.analise import ITENS_CHAVES, STATUS_INVESTIGACAO, TIPOS_ANEXO, checklist
from .portas import BaixadorWeb, EntradaInvalida, ErroDeFonte, NaoEncontrado, RepositorioDeAnalise

ANEXO_MAX = 25 * 1024 * 1024
NOTA_MAX = 2000
ASSINATURAS = [(b"%PDF-", ".pdf", "application/pdf"), (b"\x89PNG\r\n\x1a\n", ".png", "image/png"),
               (b"\xff\xd8\xff", ".jpg", "image/jpeg")]


def _agora(agora=None):
    return agora or datetime.now().isoformat(timespec="seconds")


def _buscar_imovel(repo: RepositorioDeAnalise, imovel_id: int) -> dict:
    im = repo.buscar_imovel(imovel_id)
    if im is None:
        raise NaoEncontrado(f"imóvel {imovel_id} não encontrado")
    return im


def _ler_pdf(repo: RepositorioDeAnalise, anexo_id: int, dados: bytes) -> str:
    """Extrai e guarda o texto das páginas. Devolve a situação da leitura."""
    if not dados.startswith(b"%PDF-"):
        repo.gravar_leitura(anexo_id, "imagem")
        return "imagem"
    if not documentos.leitura_ligada():
        repo.gravar_leitura(anexo_id, "desligada")
        return "desligada"
    try:
        paginas = documentos.extrair_paginas(dados)
    except Exception:
        paginas, situacao = [], "erro"
    else:
        situacao = "lido" if documentos.tem_texto_util(paginas) else "sem_texto"
    repo.gravar_leitura(anexo_id, situacao, paginas)
    return situacao


def _achados(repo: RepositorioDeAnalise, imovel_id: int, pasta: str = None) -> dict:
    """Trechos encontrados nos PDFs do imóvel, agrupados por item da investigação."""
    if pasta:   # anexos enviados antes da leitura existir (ou com ela desligada): lê agora
        for a in repo.anexos_sem_leitura(imovel_id):
            if not documentos.leitura_ligada() and a["arquivo"].endswith(".pdf"):
                continue
            caminho = os.path.join(pasta, a["arquivo"])
            if os.path.isfile(caminho):
                with open(caminho, "rb") as f:
                    _ler_pdf(repo, a["id"], f.read())
    por_item = {}
    for a in repo.textos_lidos(imovel_id):
        for ach in documentos.buscar(a["paginas"]):
            ach.update(anexo_id=a["id"], documento=a["nome_original"])
            por_item.setdefault(ach.pop("item"), []).append(ach)
    return por_item


def _descrever_modalidade(fontes, im):
    f = (fontes or {}).get(im.get("fonte"))
    return f.descrever_modalidade(im.get("modalidade")) if f else None


def ficha(repo: RepositorioDeAnalise, imovel_id: int, pasta: str = None, fontes: dict = None, analisador=None) -> dict:
    im = _buscar_imovel(repo, imovel_id)
    return {"imovel": im, "historico": repo.historico(imovel_id), "triagens": repo.triagens(imovel_id),
            "investigacao": checklist(repo.investigacao_atual(imovel_id)), "status": STATUS_INVESTIGACAO,
            "achados": _achados(repo, imovel_id, pasta), "anexos": repo.anexos(imovel_id), "tipos_anexo": TIPOS_ANEXO,
            "leitura_pdf": documentos.leitura_ligada(), "sugestao_leilao": _descrever_modalidade(fontes, im),
            "premissas": simulador.descricao_premissas(),
            "premissas_padrao": simulador.padrao_para(im),
            "premissas_da_fonte": ["comissao_leiloeiro_pct"] if (im.get("leilao") or {}).get("comissao_pct") is not None else [],
            "simulacao_salva": repo.ultima_simulacao(imovel_id),
            "documentos_fonte": documentos_da_fonte(im, fontes),
            "parecer": repo.ultimo_parecer(imovel_id),
            "tarefas": tarefas(repo, imovel_id),
            "regras_edital": _regras_dos_editais(repo, imovel_id),
            "ia": {"disponivel": analisador is not None and analisador.disponivel() is None,
                   "motivo": "a análise com IA não está configurada" if analisador is None else analisador.disponivel(),
                   "modelo": getattr(analisador, "modelo", None)}}


def investigar(repo: RepositorioDeAnalise, imovel_id: int, corpo, agora: str = None) -> dict:
    if not isinstance(corpo, dict) or set(corpo) - {"item", "status", "nota"}:
        raise EntradaInvalida("envie {item, status, nota}")
    _buscar_imovel(repo, imovel_id)
    item, status, nota = corpo.get("item"), corpo.get("status"), corpo.get("nota")
    if item not in ITENS_CHAVES:
        raise EntradaInvalida("item inválido: use " + ", ".join(ITENS_CHAVES))
    if status not in STATUS_INVESTIGACAO:
        raise EntradaInvalida("status inválido: use " + ", ".join(STATUS_INVESTIGACAO))
    if nota is not None:
        if not isinstance(nota, str):
            raise EntradaInvalida("'nota' deve ser texto")
        nota = nota.strip()
        if len(nota) > NOTA_MAX:
            raise EntradaInvalida(f"nota muito longa (máximo {NOTA_MAX} caracteres)")
        nota = nota or None
    repo.registrar_investigacao(imovel_id, item, status, nota, _agora(agora))
    return {"investigacao": checklist(repo.investigacao_atual(imovel_id))}


def anexar(repo: RepositorioDeAnalise, pasta: str, imovel_id: int, tipo: str, nome: str, dados: bytes,
           agora: str = None) -> dict:
    _buscar_imovel(repo, imovel_id)
    if tipo not in TIPOS_ANEXO:
        raise EntradaInvalida("tipo de anexo inválido: use " + ", ".join(TIPOS_ANEXO))
    if not dados:
        raise EntradaInvalida("arquivo vazio")
    if len(dados) > ANEXO_MAX:
        raise EntradaInvalida("arquivo maior que 25 MB")
    ext = next((e for assinatura, e, _ in ASSINATURAS if dados.startswith(assinatura)), None)
    if ext is None:
        raise EntradaInvalida("formato não aceito: envie PDF, PNG ou JPG")
    nome = re.sub(r"[\x00-\x1f]", "", os.path.basename((nome or "").replace("\\", "/"))).strip()[:150] or f"anexo{ext}"
    sha = hashlib.sha256(dados).hexdigest()
    if repo.anexo_por_conteudo(imovel_id, sha):
        return {"anexos": repo.anexos(imovel_id), "achados": _achados(repo, imovel_id), "duplicado": True}
    relativo = os.path.join(str(imovel_id), sha[:24] + ext)       # nome no disco nunca vem do usuário
    destino = os.path.join(pasta, relativo)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    with open(destino, "wb") as f:
        f.write(dados)
    anexo_id = repo.inserir_anexo(imovel_id, tipo, nome, relativo, len(dados), sha, _agora(agora))
    _ler_pdf(repo, anexo_id, dados)
    return {"anexos": repo.anexos(imovel_id), "achados": _achados(repo, imovel_id), "duplicado": False}


def arquivo_anexo(repo: RepositorioDeAnalise, pasta: str, anexo_id: int):
    """Devolve (caminho no disco, nome original, tipo MIME)."""
    a = repo.anexo(anexo_id)
    if a is None:
        raise NaoEncontrado("anexo não encontrado")
    caminho = os.path.realpath(os.path.join(pasta, a["arquivo"]))
    if not caminho.startswith(os.path.realpath(pasta) + os.sep) or not os.path.isfile(caminho):
        raise NaoEncontrado("arquivo do anexo não está na pasta de anexos")
    mime = next(m for _, e, m in ASSINATURAS if caminho.endswith(e))
    return caminho, a["nome_original"], mime


def simular(corpo) -> dict:
    if not isinstance(corpo, dict) or set(corpo) != {"premissas"}:
        raise EntradaInvalida("envie {premissas: {...}}")
    try:
        return simulador.simular(corpo["premissas"])
    except simulador.PremissaInvalida as e:
        raise EntradaInvalida(str(e))


def salvar_simulacao(repo: RepositorioDeAnalise, imovel_id: int, corpo, agora: str = None) -> dict:
    _buscar_imovel(repo, imovel_id)
    r = simular(corpo)
    quando = _agora(agora)
    repo.salvar_simulacao(imovel_id, r["premissas"], r, quando)
    return {"resultado": r, "quando": quando}


def documentos_da_fonte(im: dict, fontes: dict = None) -> list:
    """Documentos publicados pela fonte: os gravados na coleta (leilões) mais os que a fonte sabe
    localizar pelo identificador do imóvel (ex.: matrícula da Caixa)."""
    docs = list((im.get("leilao") or {}).get("documentos") or im.get("documentos") or [])
    f = (fontes or {}).get(im.get("fonte"))
    if f is not None and hasattr(f, "documentos_conhecidos"):
        urls = {d["url"] for d in docs}
        docs += [d for d in f.documentos_conhecidos(im) if d["url"] not in urls]
    return docs


def baixar_documentos_fonte(repo: RepositorioDeAnalise, pasta: str, imovel_id: int, baixador: BaixadorWeb,
                            agora: str = None, fontes: dict = None) -> dict:
    """Baixa edital, matrícula e laudo publicados pela fonte do anúncio e anexa à ficha
    (a leitura de PDF roda em seguida). Só links gravados na coleta; nada digitado por pessoas.
    Imóvel em 'Para analisar': download sob demanda (decisão do Mateus, 15/11/2026), um pedido
    por documento, mesmo onde o robots.txt do servidor de arquivos não permite robôs."""
    im = _buscar_imovel(repo, imovel_id)
    sob_demanda = im.get("estagio") == "analisar"
    docs = documentos_da_fonte(im, fontes)
    if not docs:
        raise EntradaInvalida("a fonte deste imóvel não publicou documentos para baixar")
    baixados, erros = [], []
    for d in docs:
        if d["tipo"] not in TIPOS_ANEXO or not d["url"].startswith("https://"):
            continue
        try:
            dados = baixador.baixar(d["url"], sob_demanda=sob_demanda)
            r = anexar(repo, pasta, imovel_id, d["tipo"], (d['rotulo'] or d['tipo']).replace("/", "-") + ".pdf", dados, agora)
            baixados.append({"tipo": d["tipo"], "duplicado": r["duplicado"]})
        except (ErroDeFonte, EntradaInvalida) as e:
            erros.append(f"{d['rotulo'] or d['tipo']}: {e}")
    return {"baixados": baixados, "erros": erros, "sob_demanda": sob_demanda, "anexos": repo.anexos(imovel_id),
            "achados": _achados(repo, imovel_id)}


def documentos_pendentes(repo: RepositorioDeAnalise, imovel_id: int, fontes: dict = None) -> bool:
    """A fonte publicou documentos que ainda não estão anexados?"""
    im = repo.buscar_imovel(imovel_id) or {}
    docs = documentos_da_fonte(im, fontes)
    tipos = {a["tipo"] for a in repo.anexos(imovel_id)}
    return any(d["tipo"] not in tipos for d in docs if d["tipo"] in TIPOS_ANEXO)


def transcrever_anexo(repo: RepositorioDeAnalise, pasta: str, transcritor, anexo_id: int) -> dict:
    """PDF escaneado (sem texto): a IA transcreve, página por página, a pedido da pessoa.
    A transcrição é guardada com CPF e RG mascarados e passa a valer para a busca de trechos e o parecer."""
    from ..dominio.parecer import mascarar_dados_pessoais
    from .portas import ErroDeAnalise
    a = repo.anexo(anexo_id)
    if a is None:
        raise NaoEncontrado("anexo não encontrado")
    if transcritor is None:
        raise ErroDeAnalise("a leitura de PDF escaneado com IA não está configurada")
    motivo = transcritor.disponivel()
    if motivo:
        raise ErroDeAnalise(motivo)
    atual = next((x for x in repo.anexos(a["imovel_id"]) if x["id"] == anexo_id), {})
    if not a["arquivo"].endswith(".pdf"):
        raise EntradaInvalida("só PDFs podem ser transcritos")
    if atual.get("leitura") in ("lido", "transcrito_ia"):
        raise EntradaInvalida("este PDF já tem texto lido; não precisa transcrever")
    caminho, _, _ = arquivo_anexo(repo, pasta, anexo_id)
    with open(caminho, "rb") as f:
        dados = f.read()
    if len(dados) > 30 * 1024 * 1024:
        raise EntradaInvalida("PDF maior que 30 MB")
    r = transcritor.transcrever_pdf(dados)
    paginas = [mascarar_dados_pessoais(p) for p in r["paginas"]]
    if not any(p.strip() for p in paginas):
        raise ErroDeAnalise("a IA não encontrou texto legível neste PDF")
    repo.gravar_leitura(anexo_id, "transcrito_ia", paginas)
    return {"anexos": repo.anexos(a["imovel_id"]), "achados": _achados(repo, a["imovel_id"]),
            "uso": r.get("uso") or {}, "paginas": len(paginas)}


def indexar_edital_caixa(repo, pasta: str, baixador: BaixadorWeb, url: str, fontes: dict = None) -> dict:
    """Um edital da Caixa lista centenas de imóveis pelo número. Baixa o edital uma vez, liga-o a
    todos os imóveis da base que aparecem nele e anexa nos que já estão em 'Para analisar'."""
    import re
    from ..documentos import extrair_paginas
    from .portas import ErroDeFonte
    m = re.fullmatch(r"https://venda-imoveis\.caixa\.gov\.br/editais/(E[LA]\w{4,40})\.pdf", (url or "").strip(), re.I)
    if not m:
        raise EntradaInvalida("cole o link do edital da Caixa (https://venda-imoveis.caixa.gov.br/editais/EL....PDF)")
    url = url.strip()
    dados = baixador.baixar(url, sob_demanda=True)
    if not dados.startswith(b"%PDF"):
        raise ErroDeFonte("a Caixa não devolveu um PDF nesse endereço")
    texto = "\n".join(extrair_paginas(dados))
    numeros = sorted({re.sub(r"\D", "", n) for n in re.findall(r"(?<!\d)\d{12}-?\d(?!\d)", texto)})
    cod = m.group(1).upper()
    num = re.match(r"E[LA](\d{4})(\d{4})", cod)
    rotulo = f"Edital {num.group(1)}/{num.group(2)} (Caixa)" if num else f"Edital {cod} (Caixa)"
    achados = repo.vincular_documento("caixa", numeros, "edital", url, rotulo)
    if hasattr(repo, "registrar_edital_caixa"):
        repo.registrar_edital_caixa(cod, True, url, len(numeros), _agora(None))
    anexados = []
    for a in achados:
        if a["estagio"] == "analisar" and documentos_pendentes(repo, a["id"], fontes):
            r = baixar_documentos_fonte(repo, pasta, a["id"], baixador, fontes=fontes)
            if r["baixados"]:
                anexados.append(a["id"])
    return {"edital": rotulo, "url": url, "imoveis_no_edital": len(numeros), "imoveis_na_base": len(achados),
            "anexados_em_analise": anexados}


def _regras_dos_editais(repo, imovel_id: int) -> list:
    """Regras gerais já lidas dos editais anexados (uma leitura por edital, vale para todos os imóveis dele)."""
    saida = []
    for a in repo.anexos(imovel_id):
        salvo = a["tipo"] == "edital" and a.get("sha256") and repo.regras_edital(a["sha256"])
        if salvo:
            regras = [{**r, "citacoes": [{**c, "documento": f"A{a['id']}"} for c in r.get("citacoes", []) if c.get("confirmada")]}
                      for r in salvo["regras"].get("regras", [])]
            saida.append({"anexo_id": a["id"], "nome": a["nome_original"], "quando": salvo["quando"],
                          "regras": [r for r in regras if r["citacoes"]]})
    return saida


SERIE_CAIXA_PADRAO = ("0226", "CPARE")      # série e unidade do edital 0061/0226 - CPA/RE (nov/2026)
URL_EDITAL_CAIXA = "https://venda-imoveis.caixa.gov.br/editais/EL{numero:04d}{serie}{unidade}.PDF"


def buscar_edital_caixa(repo, pasta: str, baixador: BaixadorWeb, imovel_id: int, fontes: dict = None,
                        agora: str = None, limite: int = 90) -> dict:
    """Imóvel da Caixa sem edital: procura o edital pelo nome do arquivo (EL<número><série><unidade>.PDF),
    que segue numeração sequencial. Autorizado pelo Mateus em 16/11/2026. Cada edital encontrado é
    baixado uma vez e ligado a todos os imóveis que ele lista; os já consultados não são pedidos de novo
    (os inexistentes são reconsultados depois de 7 dias, quando a Caixa pode ter publicado). Para quando
    o imóvel ganha edital ou acabam os candidatos. Pedidos sob demanda, identificados e com pausa."""
    import re
    from datetime import datetime, timedelta
    from .portas import ErroDeFonte
    im = _buscar_imovel(repo, imovel_id)
    tem = lambda: any(d["tipo"] == "edital" for d in documentos_da_fonte(repo.buscar_imovel(imovel_id), fontes))
    if im.get("fonte") != "caixa" or tem():
        return {"encontrado": tem(), "consultados": 0}
    agora = agora or _agora(None)
    conhecidos = {e["codigo"]: e for e in repo.editais_caixa_conhecidos()}
    series = {}
    for cod in conhecidos:
        m = re.fullmatch(r"EL(\d{4})(\d{4})([A-Z]+)", cod)
        if m:
            series.setdefault((m.group(2), m.group(3)), []).append(int(m.group(1)) if conhecidos[cod]["existe"] else 0)
    series.setdefault(SERIE_CAIXA_PADRAO, [0])
    limite_antigo = (datetime.fromisoformat(agora) - timedelta(days=7)).isoformat(timespec="seconds")
    consultados = 0

    def tentar(n, serie, unidade):
        """None: já consultado; True: existe (e foi indexado); False: não existe."""
        nonlocal consultados
        cod = f"EL{n:04d}{serie}{unidade}"
        e = conhecidos.get(cod)
        if e and (e["existe"] or e["quando"] >= limite_antigo):
            return None if e["existe"] else False
        url = URL_EDITAL_CAIXA.format(numero=n, serie=serie, unidade=unidade)
        consultados += 1
        try:
            indexar_edital_caixa(repo, pasta, baixador, url, fontes)
            return True
        except ErroDeFonte as erro:
            if "respondeu 404" not in str(erro):
                raise
            repo.registrar_edital_caixa(cod, False, url, 0, agora)
            return False

    for (serie, unidade), ns in series.items():
        maior = max(ns)
        n, faltas = maior + 1, 0                 # 1ª fase: editais novos, até 3 números seguidos sem edital
        while faltas < 3 and consultados < limite:
            r = tentar(n, serie, unidade)
            faltas = faltas + 1 if r is False else 0
            if r and tem():
                return {"encontrado": True, "consultados": consultados}
            n += 1
        for n in range(maior, 0, -1):            # 2ª fase: os anteriores ainda não consultados, do mais novo ao mais antigo
            if consultados >= limite:
                return {"encontrado": False, "consultados": consultados, "parou": "limite"}
            if tentar(n, serie, unidade) and tem():
                return {"encontrado": True, "consultados": consultados}
    return {"encontrado": tem(), "consultados": consultados}


def transcrever_pendentes(repo, pasta: str, transcritor, imovel_id: int) -> dict:
    """Antes do parecer: PDFs escaneados de edital, matrícula ou laudo são transcritos (modelo barato,
    < US$ 0,01 por matrícula). Um que falhe não impede o parecer: ele segue com o que houver."""
    feitos, custo, erros = [], 0.0, []
    for a in repo.anexos(imovel_id):
        if a["tipo"] in ("edital", "matricula", "laudo") and a["leitura"] in ("sem_texto", "erro") \
                and a["nome_original"].lower().endswith(".pdf"):
            try:
                r = transcrever_anexo(repo, pasta, transcritor, a["id"])
                feitos.append(a["id"]); custo += (r.get("uso") or {}).get("custo_usd") or 0
            except Exception as e:                 # segue sem esse documento; o parecer avisa que não há texto
                erros.append(f"{a['nome_original']}: {e}")
    return {"transcritos": feitos, "custo_usd": round(custo, 4), "erros": erros}


TAREFA_MAX = 300


def _chave_pergunta(texto: str) -> str:
    import hashlib, re as _re
    return "ia:" + hashlib.sha1(_re.sub(r"\W+", " ", texto.lower()).strip().encode("utf-8")).hexdigest()[:16]


def tarefas(repo, imovel_id: int) -> list:
    """O que falta apurar: as perguntas do parecer mais recente (com a situação que a pessoa marcou)
    e as tarefas criadas pela pessoa. Abertas primeiro."""
    salvas = {t["chave"]: t for t in repo.tarefas(imovel_id)}
    parecer = repo.ultimo_parecer(imovel_id)
    lista = []
    for q in ((parecer or {}).get("parecer") or {}).get("perguntas") or []:
        t = salvas.get(_chave_pergunta(q))
        lista.append({"chave": _chave_pergunta(q), "texto": q, "origem": "ia", "feita": bool(t and t["feita"]),
                      "quando": t["quando"] if t else None})
    lista += [{**t, "feita": bool(t["feita"])} for t in salvas.values() if t["origem"] == "manual"]
    return sorted(lista, key=lambda t: t["feita"])


def marcar_tarefa(repo, imovel_id: int, corpo, agora: str = None) -> dict:
    """{chave, feita}: marca uma tarefa existente. {texto}: cria uma tarefa da pessoa."""
    _buscar_imovel(repo, imovel_id)
    if not isinstance(corpo, dict) or set(corpo) - {"chave", "feita", "texto"}:
        raise EntradaInvalida("envie {chave, feita} ou {texto}")
    quando = _agora(agora)
    if "texto" in corpo:
        texto = corpo["texto"].strip() if isinstance(corpo["texto"], str) else ""
        if not texto or len(texto) > TAREFA_MAX:
            raise EntradaInvalida(f"escreva a tarefa (até {TAREFA_MAX} caracteres)")
        repo.gravar_tarefa(imovel_id, "manual:" + _chave_pergunta(texto + quando)[3:], texto, "manual", False, quando)
    else:
        atual = {t["chave"]: t for t in tarefas(repo, imovel_id)}.get(corpo.get("chave"))
        if atual is None or not isinstance(corpo.get("feita"), bool):
            raise EntradaInvalida("tarefa não encontrada ou 'feita' inválido")
        repo.gravar_tarefa(imovel_id, atual["chave"], atual["texto"], atual["origem"], corpo["feita"], quando)
    return {"tarefas": tarefas(repo, imovel_id)}
