"""Caso de uso: parecer preliminar da investigação, gerado por IA a pedido da pessoa.

Monta o material do imóvel (dados da fonte, descrição do lote e texto dos PDFs anexados),
mascara CPF e RG, pede a análise à porta AnalisadorDeDocumentos, confere cada citação
contra o texto enviado e guarda o parecer (nada é apagado; o mais recente vale).
Não marca nada na investigação: a pessoa decide.
"""
from datetime import datetime
from typing import Optional

from ..dominio.parecer import conferir, mascarar_dados_pessoais
from .portas import AnalisadorDeDocumentos, ErroDeAnalise, NaoEncontrado, RepositorioDeAnalise

TAMANHO_MAX = 700_000          # caracteres enviados; acima disso a pessoa é avisada (nada é cortado em silêncio)


def _valor(v):
    return "não informado" if v in (None, "") else (f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                                                     if isinstance(v, float) else str(v))


def montar_contexto(repo: RepositorioDeAnalise, imovel_id: int):
    """(texto para a IA, fontes por código de documento, lista de documentos)."""
    im = repo.buscar_imovel(imovel_id)
    if im is None:
        raise NaoEncontrado(f"imóvel {imovel_id} não encontrado")
    lei = im.get("leilao") or {}
    fontes, documentos = {"DESCRICAO": [mascarar_dados_pessoais(im.get("descricao") or "")]}, [
        {"codigo": "DESCRICAO", "nome": f"Descrição do lote na fonte ({im['fonte']})", "anexo_id": None}]
    for a in repo.textos_lidos(imovel_id):
        codigo = f"A{a['id']}"
        fontes[codigo] = [mascarar_dados_pessoais(p) for p in a["paginas"]]
        nome = a["nome_original"] + (" (transcrição por IA de PDF escaneado)" if a.get("transcrito_ia") else "")
        documentos.append({"codigo": codigo, "nome": nome, "anexo_id": a["id"]})
    pracas = "; ".join(f"{p['numero']}ª praça {p['data']}: {_valor(p['valor'])}" for p in lei.get("pracas", [])) or "não informadas"
    cabecalho = "\n".join([
        "DADOS DO IMÓVEL (como publicados pela fonte)",
        f"Tipo: {im.get('tipo')} | Cidade: {im.get('cidade')}/{im.get('uf')} | Endereço: {im.get('endereco') or 'não informado'}",
        f"Preço/lance mínimo atual: {_valor(im.get('preco'))} | Avaliação da fonte: {_valor(im.get('valor_avaliacao'))}",
        f"Modalidade: {im.get('modalidade')} | Tipo de venda: {lei.get('tipo_venda') or 'não informado'} | Praças: {pracas}",
        f"Comitente: {lei.get('comitente') or 'não informado'} | Ocupação informada: {lei.get('ocupacao') or 'não informada'} | "
        f"Matrícula: {lei.get('matricula') or 'não informada'} | Processo: {lei.get('processo') or '-'} | Vara: {lei.get('vara') or '-'}",
        f"Áreas: privativa {im.get('area_privativa') or '-'} m², terreno {im.get('area_terreno') or '-'} m², total {im.get('area_total') or '-'} m²",
        "", "DOCUMENTOS DISPONÍVEIS: " + "; ".join(f"{d['codigo']} = {d['nome']}" for d in documentos),
        "(Se edital ou matrícula não estiverem na lista, eles ainda não foram anexados: diga isso nas perguntas.)", ""])
    partes = [cabecalho]
    for codigo, paginas in fontes.items():
        for i, texto in enumerate(paginas, start=1):
            partes.append(f"=== DOCUMENTO {codigo}, página {i} ===\n{texto.strip()}\n")
    return "\n".join(partes), fontes, documentos


def gerar_parecer(repo: RepositorioDeAnalise, analisador: Optional[AnalisadorDeDocumentos], imovel_id: int,
                  agora: Optional[str] = None) -> dict:
    if analisador is None:
        raise ErroDeAnalise("a análise com IA não está configurada neste computador")
    motivo = analisador.disponivel()
    if motivo:
        raise ErroDeAnalise(motivo)
    contexto, fontes, documentos = montar_contexto(repo, imovel_id)
    if len(contexto) > TAMANHO_MAX:
        raise ErroDeAnalise(f"os documentos deste imóvel são longos demais para uma análise ({len(contexto):,} caracteres). "
                            "Anexe só edital e matrícula.".replace(",", "."))
    r = analisador.analisar(contexto)
    parecer = conferir(r["parecer"], fontes)
    quando = agora or datetime.now().isoformat(timespec="seconds")
    repo.salvar_parecer(imovel_id, analisador.modelo, parecer, r.get("uso") or {}, documentos, quando)
    return {"parecer": parecer, "uso": r.get("uso") or {}, "documentos": documentos, "modelo": analisador.modelo, "quando": quando}
