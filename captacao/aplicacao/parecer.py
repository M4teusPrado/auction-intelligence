"""Caso de uso: parecer preliminar da investigação, gerado por IA a pedido da pessoa.

Monta o material do imóvel (dados da fonte, descrição do lote e texto dos PDFs anexados),
mascara CPF e RG, pede a análise à porta AnalisadorDeDocumentos, confere cada citação
contra o texto enviado e guarda o parecer (nada é apagado; o mais recente vale).
Não marca nada na investigação: a pessoa decide.
"""
import re
from datetime import datetime
from typing import Optional

from ..dominio.parecer import conferir, conferir_regras, mascarar_dados_pessoais
from .portas import AnalisadorDeDocumentos, ErroDeAnalise, NaoEncontrado, RepositorioDeAnalise

TAMANHO_MAX = 700_000          # caracteres enviados; acima disso a pessoa é avisada (nada é cortado em silêncio)


def _valor(v):
    return "não informado" if v in (None, "") else (f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                                                     if isinstance(v, float) else str(v))


NUMERO_IMOVEL = re.compile(r"(?<!\d)\d{12}-?\d(?!\d)")


def _numeros(p: str) -> set:
    return {re.sub(r"\D", "", n) for n in NUMERO_IMOVEL.findall(p)}


def paginas_de_tabela(paginas) -> set:
    """Páginas que listam vários imóveis (2+ números de imóvel): a tabela de um edital coletivo."""
    return {i for i, p in enumerate(paginas) if len(_numeros(p)) >= 2}


def paginas_de_outros_imoveis(paginas, id_fonte: str) -> set:
    """Páginas de tabela de um edital com vários imóveis em que este imóvel não aparece. Ficam fora
    do envio à IA (no edital da Caixa são ~3/4 das páginas) e seguem valendo para conferir citações.
    Sem identificador numérico, nada é omitido."""
    alvo = re.sub(r"\D", "", id_fonte or "")
    if len(alvo) != 13:
        return set()
    return {i for i in paginas_de_tabela(paginas) if alvo not in _numeros(paginas[i])}


def _edital_coletivo(a: dict, id_fonte: str) -> bool:
    """Edital que lista vários imóveis, entre eles este: as regras gerais podem ser lidas uma vez."""
    return a.get("tipo") == "edital" and bool(paginas_de_outros_imoveis(a["paginas"], id_fonte))


def _texto_regras(codigo: str, regras: dict) -> str:
    linhas = [f"=== REGRAS GERAIS DO DOCUMENTO {codigo} (edital lido por inteiro uma vez; cada trecho abaixo é cópia "
              f"literal da página indicada do documento {codigo} e pode ser citado assim) ==="]
    for r in regras.get("regras", []):
        cits = [c for c in r.get("citacoes", []) if c.get("confirmada")]
        if not cits:
            continue                                  # regra sem trecho conferido não entra
        linhas.append(f"- [{r['tema']}] {r['regra']}")
        linhas += [f"    página {c['pagina']}: «{c['trecho']}»" for c in cits]
    return "\n".join(linhas) + "\n"


def montar_contexto(repo: RepositorioDeAnalise, imovel_id: int, regras_por_sha: Optional[dict] = None):
    """(texto para a IA, fontes por código de documento, lista de documentos).
    Edital coletivo com regras já lidas: entram as regras (com trechos) e só a página do imóvel."""
    im = repo.buscar_imovel(imovel_id)
    if im is None:
        raise NaoEncontrado(f"imóvel {imovel_id} não encontrado")
    regras_por_sha = regras_por_sha or {}
    lei = im.get("leilao") or {}
    fontes, documentos = {"DESCRICAO": [mascarar_dados_pessoais(im.get("descricao") or "")]}, [
        {"codigo": "DESCRICAO", "nome": f"Descrição do lote na fonte ({im['fonte']})", "anexo_id": None}]
    envio = {"DESCRICAO": None}                       # código -> None (tudo) ou (páginas a enviar, texto extra)
    for a in repo.textos_lidos(imovel_id):
        codigo = f"A{a['id']}"
        fontes[codigo] = [mascarar_dados_pessoais(p) for p in a["paginas"]]
        nome = a["nome_original"] + (" (transcrição por IA de PDF escaneado)" if a.get("transcrito_ia") else "")
        documentos.append({"codigo": codigo, "nome": nome, "anexo_id": a["id"]})
        outros = paginas_de_outros_imoveis(a["paginas"], im.get("id_fonte"))
        regras = regras_por_sha.get(a.get("sha256")) if a.get("tipo") == "edital" and outros else None
        if regras:
            proprias = [i for i in range(len(a["paginas"])) if i not in paginas_de_tabela(a["paginas"]) or i not in outros]
            proprias = [i for i in proprias if i in paginas_de_tabela(a["paginas"])]       # só a(s) página(s) do imóvel
            envio[codigo] = (set(proprias), _texto_regras(codigo, regras),
                             f"(DOCUMENTO {codigo}: enviadas as regras gerais acima e só a página onde este imóvel aparece.)")
        elif outros:
            envio[codigo] = (set(range(len(a["paginas"]))) - outros, "",
                             f"(DOCUMENTO {codigo}: {len(outros)} páginas omitidas por listarem apenas outros imóveis.)")
        else:
            envio[codigo] = None
    pracas = "; ".join(f"{p['numero']}ª praça {p['data']}: {_valor(p['valor'])}" for p in lei.get("pracas", [])) or "não informadas"
    cabecalho = "\n".join([
        "DADOS DO IMÓVEL (como publicados pela fonte)",
        f"Tipo: {im.get('tipo')} | Cidade: {im.get('cidade')}/{im.get('uf')} | Endereço: {im.get('endereco') or 'não informado'}",
        f"Identificador na fonte: {im.get('id_fonte')}",
        f"Preço/lance mínimo atual: {_valor(im.get('preco'))} | Avaliação da fonte: {_valor(im.get('valor_avaliacao'))}",
        f"Modalidade: {im.get('modalidade')} | Tipo de venda: {lei.get('tipo_venda') or 'não informado'} | Praças: {pracas}",
        f"Comitente: {lei.get('comitente') or 'não informado'} | Ocupação informada: {lei.get('ocupacao') or 'não informada'} | "
        f"Matrícula: {lei.get('matricula') or 'não informada'} | Processo: {lei.get('processo') or '-'} | Vara: {lei.get('vara') or '-'}",
        f"Áreas: privativa {im.get('area_privativa') or '-'} m², terreno {im.get('area_terreno') or '-'} m², total {im.get('area_total') or '-'} m²",
        "", "DOCUMENTOS DISPONÍVEIS: " + "; ".join(f"{d['codigo']} = {d['nome']}" for d in documentos),
        "(Se edital ou matrícula não estiverem na lista, eles ainda não foram anexados: diga isso nas perguntas.)", ""])
    partes = [cabecalho]
    for codigo, paginas in fontes.items():
        e = envio.get(codigo)
        if e and e[1]:
            partes.append(e[1])
        for i, texto in enumerate(paginas, start=1):
            if e is None or i - 1 in e[0]:
                partes.append(f"=== DOCUMENTO {codigo}, página {i} ===\n{texto.strip()}\n")
        if e:
            partes.append(e[2] + "\n")
    return "\n".join(partes), fontes, documentos


def preparar_regras_edital(repo: RepositorioDeAnalise, analisador, imovel_id: int, agora: str) -> tuple:
    """Camada 1: para cada edital coletivo anexado, lê as regras gerais uma vez (pelo conteúdo do PDF)
    e guarda; os outros imóveis do mesmo edital reaproveitam. Devolve ({sha: regras}, custo desta vez)."""
    im = repo.buscar_imovel(imovel_id) or {}
    regras, custo = {}, 0.0
    for a in repo.textos_lidos(imovel_id):
        if not _edital_coletivo(a, im.get("id_fonte")) or not a.get("sha256"):
            continue
        salvo = repo.regras_edital(a["sha256"])
        if salvo is None:
            if not hasattr(analisador, "extrair_regras_edital"):
                continue
            paginas = [mascarar_dados_pessoais(p) for p in a["paginas"]]
            tabela = paginas_de_tabela(paginas)
            texto = "\n".join(f"=== DOCUMENTO EDITAL, página {i} ===\n{p.strip()}\n"
                              for i, p in enumerate(paginas, start=1) if i - 1 not in tabela)
            r = analisador.extrair_regras_edital(texto)
            lidas = conferir_regras(r["regras"], paginas, "EDITAL")
            uso = r.get("uso") or {}
            repo.salvar_regras_edital(a["sha256"], getattr(analisador, "modelo_edital", analisador.modelo), lidas, uso, agora)
            custo += uso.get("custo_usd") or 0
            salvo = {"regras": lidas}
        regras[a["sha256"]] = salvo["regras"]
    return regras, custo


def gerar_parecer(repo: RepositorioDeAnalise, analisador: Optional[AnalisadorDeDocumentos], imovel_id: int,
                  agora: Optional[str] = None) -> dict:
    if analisador is None:
        raise ErroDeAnalise("a análise com IA não está configurada neste computador")
    motivo = analisador.disponivel()
    if motivo:
        raise ErroDeAnalise(motivo)
    quando = agora or datetime.now().isoformat(timespec="seconds")
    regras, custo_edital = preparar_regras_edital(repo, analisador, imovel_id, quando)
    contexto, fontes, documentos = montar_contexto(repo, imovel_id, regras)
    if len(contexto) > TAMANHO_MAX:
        raise ErroDeAnalise(f"os documentos deste imóvel são longos demais para uma análise ({len(contexto):,} caracteres). "
                            "Anexe só edital e matrícula.".replace(",", "."))
    r = analisador.analisar(contexto)
    parecer = conferir(r["parecer"], fontes)
    uso = dict(r.get("uso") or {})
    if custo_edital:                       # leitura única do edital: entra no custo de quem a disparou
        uso["custo_edital_usd"] = round(custo_edital, 4)
        uso["custo_usd"] = round((uso.get("custo_usd") or 0) + custo_edital, 4)
    repo.salvar_parecer(imovel_id, analisador.modelo, parecer, uso, documentos, quando)
    return {"parecer": parecer, "uso": uso, "documentos": documentos, "modelo": analisador.modelo, "quando": quando}
