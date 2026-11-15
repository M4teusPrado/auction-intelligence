"""Fonte: Mega Leilões (megaleiloes.com.br), leilões judiciais e extrajudiciais.

Duas formas de entrada, com o mesmo leitor de página:
- importar por link: uma oferta colada por uma pessoa;
- coleta diária de um estado (recorte = UF): percorre as listagens por categoria
  (/imoveis/<categoria>/<uf>?pagina=N) e lê a página de cada lote.

Acesso sempre pelo ClienteWeb (robots.txt, intervalo entre pedidos, cópia local).
A página não tem dados estruturados: o leitor usa os blocos "header"/"value" do HTML.
Se o site mudar e um campo obrigatório sumir, o lote vira aviso, não dado errado.
"""
import html as htmlmod
import re
from datetime import datetime
from typing import Callable, List, Optional, Tuple
from urllib.parse import urlsplit

from ...aplicacao.portas import Coleta, ErroDeFonte
from ...dominio.modelo import DadosLeilao, DocumentoFonte, ImovelCaptado, Praca
from ...dominio.normaliza import chave, numero_br, sem_acento
from .caixa import UFS

FONTE = "megaleiloes"
BASE = "https://www.megaleiloes.com.br"
RE_LOTE = re.compile(r"^/imoveis/[a-z0-9-]+/[a-z]{2}/[a-z0-9-]+/[a-z0-9-]+-([xj]\d+)/?$")
PAGINAS_MAX = 40                 # por categoria e estado; proteção contra laço

# categoria da URL -> tipo (no vocabulário do classifica.py)
TIPOS = {"apartamentos": "apartamento", "casas": "casa", "terrenos-e-lotes": "terreno", "glebas": "gleba",
         "galpoes--industriais": "galpao", "predios": "predio", "lojas": "loja", "salas": "sala",
         "salas-comerciais": "sala", "imoveis-comerciais": "comercial", "imoveis-rurais": "imovel rural",
         "terrenos-para-incorporacao": "terreno", "casa-em-terreno-para-incorporacoes": "terreno"}
DOCUMENTOS = {"edital": "edital", "matricula": "matricula", "laudo de avaliacao": "laudo", "laudo": "laudo"}


# ------------------------------------------------------------------ leitura de página
def _texto(frag: str) -> str:
    frag = re.sub(r"<br\s*/?>", " | ", frag or "", flags=re.I)
    return re.sub(r"\s+", " ", htmlmod.unescape(re.sub(r"<[^>]+>", " ", frag))).strip(" |")


def _campo(pagina: str, rotulo: str) -> str:
    """Valor de um bloco <div class="header">Rótulo</div><div class="value">...</div>."""
    m = re.search(r'<div\s+class="header">\s*' + re.escape(rotulo) + r'\s*</div>\s*<div\s+class="value">(.*?)</div>',
                  pagina, re.S | re.I)
    return m.group(1) if m else ""


def _dinheiro(texto: str) -> Optional[float]:
    m = re.search(r"R\$\s*([\d.]+,\d{2})", texto or "")
    return numero_br(m.group(1)) if m else None


def _data_iso(dia: str, hora: str) -> str:
    d, mth, a = dia.split("/")
    return f"{a}-{mth}-{d}T{hora}"


def _area(descricao: str, nome: str) -> Optional[float]:
    num, uni = r"([\d.]*\d(?:,\d+)?)", r"(?:m²|m2|metros quadrados)"
    for padrao in (num + r"\s*" + uni + r"\s*de\s*área\s*" + nome, r"área\s*" + nome + r"\s*(?:de\s*)?" + num + r"\s*" + uni):
        m = re.search(padrao, descricao, re.I)
        if m:
            v = numero_br(m.group(1))
            if v:
                return v
    return None


def _pracas(pagina: str) -> List[Praca]:
    m = re.search(r'<div\s+class="instance-text">', pagina)
    i = m.start() if m else -1
    if i < 0:
        return []
    bloco = pagina[i:pagina.find("countdown-holder", i)]
    pracas = []
    for inst in re.findall(r'<div\s+class="instance[^"]*">(.*?)</div>', bloco, re.S):
        valor = _dinheiro(_texto(inst))
        for rotulo, dia, hora in re.findall(r"<b>([^<]*)</b>\s*(\d{2}/\d{2}/\d{4})\s*às\s*(\d{2}:\d{2})", inst):
            r = _texto(rotulo).lower()
            if r.startswith("início"):
                continue
            numero = 2 if r.startswith("2") else 1
            pracas.append(Praca(numero=numero, data=_data_iso(dia, hora), valor=valor))
    return pracas


def interpretar_oferta(pagina: str, url: str = "", hoje: Optional[str] = None) -> ImovelCaptado:
    """Lê a página de um lote. Campo obrigatório ausente: ErroDeFonte."""
    titulo = _texto((re.search(r'<h1\s+class="section-header">(.*?)</h1>', pagina, re.S) or [None, ""])[1])
    codigo = _texto(_campo(pagina, "Código Lote")).upper()
    if not codigo:
        m = re.search(r"-([xj]\d+)(?:[/?#]|$)", url or "")
        codigo = m.group(1).upper() if m else ""
    local = _texto(_campo(pagina, "Localização"))
    preco = _dinheiro(_texto(_campo(pagina, "Valor inicial")))
    if not (titulo and codigo and local):
        raise ErroDeFonte("página da Mega Leilões sem título, código do lote ou localização (formato mudou?)")
    partes = [p.strip() for p in local.split(",") if p.strip()]
    uf = partes[-1].upper() if partes and re.fullmatch(r"[A-Za-z]{2}", partes[-1]) else ""
    if uf not in UFS:
        raise ErroDeFonte(f"UF não reconhecida na localização: {local}")
    cidade = sem_acento(partes[-2]).upper() if len(partes) >= 2 else ""
    bairro = partes[-3] if len(partes) >= 4 else ""
    endereco = ", ".join(partes[:-3] if len(partes) >= 4 else partes[:-2])

    k = pagina.find('id="tab-description"')
    k = pagina.find(">", k) + 1 if k >= 0 else -1          # começa depois da tag de abertura
    descricao = _texto(pagina[k:pagina.find("</div></div>", k)] if k > 0 else "")[:4000]
    desc_up = descricao.upper()
    avaliacao = _dinheiro(_texto(_campo(pagina, "Valor de Avaliação"))) or None   # "R$ 0,00 (não informado)" vira vazio
    caminho = urlsplit(url).path if url else ""
    categoria_url = caminho.split("/")[2] if caminho.count("/") >= 3 else ""
    tipo = TIPOS.get(categoria_url) or chave(titulo.split(" ")[0]) or "outros"
    if titulo.lower().startswith("direitos sobre"):
        tipo = TIPOS.get(categoria_url, tipo)

    texto_pagina = _texto(pagina)
    comissao = re.search(r"comiss[ãa]o devida ao leiloeiro de\s*(\d+(?:,\d+)?)\s*%", texto_pagina, re.I)
    matricula = re.search(r"MATR[IÍ]CULA(?:\(S\))?\s*(?:N[º°O.]*)?\s*:?\s*(\d[\d.]*\d)", desc_up)
    cartorio = (re.search(r"Cart[óo]rio:\s*([^.|]+)", descricao) or
                re.search(r"CART[ÓO]RIO DE REGISTRO DE IM[ÓO]VEIS DA COMARCA DE ([A-ZÀ-Ú/ ]+)", desc_up))
    ocupacao = "desocupado" if re.search(r"\bDESOCUPADO\b", desc_up) else "ocupado" if re.search(r"\bOCUPADO\b", desc_up) else ""
    docs = []
    for href, rotulo in re.findall(r'class="btn-download" href="([^"]+)"[^>]*><span>([^<]+)</span>', pagina):
        t = DOCUMENTOS.get(chave(rotulo))
        if t and href.startswith("https://"):
            docs.append(DocumentoFonte(tipo=t, url=htmlmod.unescape(href), rotulo=_texto(rotulo)))
    lei = DadosLeilao(
        tipo_venda=_texto((re.search(r'<div\s+class="batch-type">(.*?)</div>', pagina, re.S) or [None, ""])[1]),
        leilao=_texto(_campo(pagina, "Leilão")), lote=_texto(_campo(pagina, "Número Lote")),
        comitente=_texto(_campo(pagina, "Comitente")),
        leiloeiro=_texto(_campo(pagina, "Leiloeiro")).split(" | ")[0],
        ocupacao=ocupacao, matricula=matricula.group(1) if matricula else "",
        cartorio=cartorio.group(1).strip() if cartorio else "",
        processo=_texto(_campo(pagina, "Processo")).replace("()", "").strip(), vara=_texto(_campo(pagina, "Vara")),
        comissao_pct=numero_br(comissao.group(1)) if comissao else None,
        incremento=_dinheiro(_texto(_campo(pagina, "Incremento"))),
        pracas=_pracas(pagina), documentos=docs)
    desconto = round((1 - preco / avaliacao) * 100, 2) if preco and avaliacao else None
    privativa, terreno, total = _area(descricao, "privativa"), _area(descricao, r"do\s*terreno"), _area(descricao, "total")
    if not (privativa or terreno or total):      # a descrição não traz área: usa a do título ("Apartamento 55 m²")
        m_tit = re.search(r"(\d+(?:[.,]\d+)?)\s*m²", titulo)
        total = numero_br(m_tit.group(1)) if m_tit else None
    return ImovelCaptado(
        fonte=FONTE, id_fonte=codigo, uf=uf, cidade=cidade, bairro=bairro, endereco=endereco,
        preco=preco, valor_avaliacao=avaliacao, desconto_pct=desconto, modalidade=lei.tipo_venda or "Leilão",
        tipo=tipo, area_privativa=privativa, area_terreno=terreno,
        area_total=total, descricao=f"{titulo}. {descricao}"[:4000],
        link=f"{BASE}{caminho}" if caminho else "", data_fonte=hoje or datetime.now().strftime("%d/%m/%Y"),
        leilao=lei)


def links_da_listagem(pagina: str) -> Tuple[List[str], bool]:
    """(links dos lotes na página, existe próxima página)."""
    links = []
    for href in re.findall(r'href="(https://www\.megaleiloes\.com\.br/imoveis/[^"?#]+)', pagina):
        if RE_LOTE.match(urlsplit(href).path) and href not in links:
            links.append(href)
    atual = re.search(r'<li class="active"><a[^>]*>(\d+)</a>', pagina)
    n = int(atual.group(1)) if atual else 1
    tem_proxima = f"pagina={n + 1}" in pagina
    return links, tem_proxima


def categorias(pagina_imoveis: str) -> List[str]:
    vistas = []
    for slug in re.findall(r'href="https://www\.megaleiloes\.com\.br/imoveis/([a-z0-9-]+)"', pagina_imoveis):
        if slug not in vistas:
            vistas.append(slug)
    return vistas


# ------------------------------------------------------------------ adaptador
class FonteMegaLeiloes:
    """Adaptador da porta FonteDeImoveis (e importação por link) para a Mega Leilões."""
    nome = FONTE
    rotulo = "Mega Leilões"
    descricao = "Leilões judiciais e extrajudiciais (bancos) da Mega Leilões, lidos do site"

    def __init__(self, cliente, relatar: Callable[[str], None] = None):
        self.cliente = cliente                         # ClienteWeb: robots, ritmo e cópia local
        self._relatar = relatar or (lambda msg: None)

    def recortes(self) -> List[str]:
        return list(UFS)

    def aceita_url(self, url: str) -> bool:
        p = urlsplit(url or "")
        return p.scheme == "https" and p.netloc in ("www.megaleiloes.com.br", "megaleiloes.com.br") and bool(RE_LOTE.match(p.path))

    def importar_url(self, url: str) -> ImovelCaptado:
        if not self.aceita_url(url):
            raise ErroDeFonte("link não é de uma oferta de imóvel da Mega Leilões")
        limpo = BASE + urlsplit(url).path
        return interpretar_oferta(self.cliente.baixar(limpo).decode("utf-8", "replace"), limpo)

    def coletar(self, recorte: str, arquivo: Optional[bytes] = None, nome_arquivo: str = "",
                limite: Optional[int] = None) -> Coleta:
        uf = recorte.upper()
        if arquivo is not None:          # uma página de lote salva (testes ou importação manual)
            im = interpretar_oferta(arquivo.decode("utf-8", "replace"), nome_arquivo if nome_arquivo.startswith("http") else "")
            if im.uf != uf:
                raise ErroDeFonte(f"o lote é de {im.uf}, não de {uf}")
            return Coleta(imoveis=[im], recorte=uf, origem=nome_arquivo or "arquivo enviado")
        avisos, links, completa = [], [], True
        cats = categorias(self.cliente.baixar(f"{BASE}/imoveis").decode("utf-8", "replace"))
        if not cats:
            raise ErroDeFonte("não encontrei as categorias de imóveis no site da Mega Leilões")
        for cat in cats:
            for n in range(1, PAGINAS_MAX + 1):
                url = f"{BASE}/imoveis/{cat}/{uf.lower()}" + (f"?pagina={n}" if n > 1 else "")
                try:
                    pagina_links, tem_proxima = links_da_listagem(self.cliente.baixar(url).decode("utf-8", "replace"))
                except ErroDeFonte as e:
                    if n > 1 or "respondeu 404" not in str(e):   # categoria sem imóveis no estado dá 404: normal
                        avisos.append(f"listagem {cat}/{uf} página {n}: {e}")
                        completa = False
                    break
                novos = [l for l in pagina_links if l not in links]
                links += novos
                # depois da última página o site repete a mesma lista: parar quando nada é novo
                if not tem_proxima or not novos:
                    break
            else:
                avisos.append(f"listagem {cat}/{uf}: parou no limite de {PAGINAS_MAX} páginas")
                completa = False
            self._relatar(f"  {cat}: {len(links)} lotes encontrados até agora")
            if limite and len(links) >= limite:
                break
        if limite:
            links, completa = links[:limite], False
        imoveis = []
        for i, url in enumerate(links, start=1):
            try:
                im = interpretar_oferta(self.cliente.baixar(url).decode("utf-8", "replace"), url)
                if im.uf == uf:
                    imoveis.append(im)
            except ErroDeFonte as e:
                avisos.append(f"{url}: {e}")
                completa = False      # lote não lido não pode ser marcado como saído
            if i % 20 == 0:
                self._relatar(f"  {i}/{len(links)} lotes lidos")
        if links and not imoveis:
            raise ErroDeFonte("nenhum lote pôde ser lido (o formato do site mudou?)")
        return Coleta(imoveis=imoveis, recorte=uf, origem=f"{BASE}/imoveis/*/{uf.lower()}", avisos=avisos,
                      completa=completa)

    def descrever_modalidade(self, modalidade: str) -> Optional[str]:
        m = (modalidade or "").lower()
        if m == "judicial":
            return ("Leilão judicial: venda determinada pela Justiça num processo. Confira no edital a vara, "
                    "as praças e o que acontece com as dívidas do imóvel.")
        if m == "extrajudicial":
            return ("Leilão extrajudicial: em geral é o banco (comitente) vendendo imóvel retomado por "
                    "alienação fiduciária (Lei 9.514). Hipótese; confirme no edital.")
        return None
