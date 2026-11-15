"""Fonte: leiloeiros que usam a plataforma SOLEON (um adaptador para dezenas de sites).

Identificados no piloto de plataformas (relatorios/2026-11-15-piloto-plataformas.md) pela
lista oficial de leiloeiros da JUCESP. Todos os sites têm a mesma estrutura:
  /leiloes?page=N           leilões atuais (cartões com título, praças, tipo e situação)
  /leilao/<n>/lotes?page=N  lotes de um leilão
  /item/<n>/detalhes        página do lote (o que é lido)
A página se identifica com <meta name="author" content="SOLEON ...">.

Recorte = site do leiloeiro (ex.: "glleiloes.com.br"): os leiloeiros vendem imóveis de vários
estados, então "saiu da lista" vale por site, não por UF. Só imóveis entram; veículos e outros
bens são ignorados. Os PDFs ficam num servidor cujo robots.txt proíbe robôs: viram links.
"""
import html as htmlmod
import re
from datetime import datetime
from typing import Callable, List, Optional
from urllib.parse import urlsplit

from ...aplicacao.portas import Coleta, ErroDeFonte
from ...dominio.modelo import DadosLeilao, DocumentoFonte, ImovelCaptado, Praca
from ...dominio.normaliza import chave, numero_br, sem_acento
from .caixa import UFS

FONTE = "soleon"
PAGINAS_MAX = 30

# Sites Soleon achados no piloto (SP, 15/11/2026). Novos sites: acrescentar aqui.
SITES = [
    "glleiloes.com.br", "bestleiloes.com.br", "cencin.com.br", "3torresleiloes.com.br", "lottileiloes.com.br",
    "tmleiloes.com.br", "gspleiloes.com.br", "leiloesgold.com.br", "machadoleiloeiro.com.br", "vegasleiloes.com.br",
    "winleiloes.com.br", "cardosoleiloes.com.br", "ricoleiloes.com.br", "tribunaleiloes.com.br", "cravoleiloes.com.br",
    "guariglialeiloes.com.br", "leilaoinvestment.com.br", "gabrieltorresleiloes.com.br", "maximoleiloes.com.br",
    "nossoleilao.com.br", "atomazellileiloeira.com.br", "desantileiloes.com.br", "marcellolemosleiloeiro.com.br",
    "pavanileiloes.com.br", "wspleiloes.com.br", "amaralleiloes.com.br", "andradeleiloes.com.br", "benozzati.com.br",
    "bidmax.com.br", "clicleiloes.com.br", "conceitoleiloes.com.br", "danielgarcialeiloes.com.br",
    "editalleiloes.com.br", "joaoemilio.com.br", "raicherleiloes.com.br",
]

# palavra no título -> tipo (vocabulário do classifica.py); a ordem importa ("lote de terreno" antes de "lote")
TIPOS = [("apartamento", "apartamento"), ("apto", "apartamento"), ("cobertura", "apartamento"), ("sobrado", "sobrado"),
         ("casa", "casa"), ("residencia", "casa"), ("terreno", "terreno"), ("gleba", "gleba"), ("area", "terreno"),
         ("sala", "sala"), ("loja", "loja"), ("galpao", "galpao"), ("barracao", "galpao"), ("predio", "predio"),
         ("edificio", "predio"), ("chacara", "imovel rural"), ("sitio", "imovel rural"), ("fazenda", "imovel rural"),
         ("imovel rural", "imovel rural"), ("vaga", "vaga de garagem"), ("box", "vaga de garagem"),
         ("imovel comercial", "comercial"), ("salao", "salao"), ("imovel", "outros")]
NAO_IMOVEL = ("veicul", "automove", "moto", "caminh", "carro", "maquin", "equipament", "materia", "sucata", "semovent",
              "eletro", "informatica", "mobiliario", "joia", "embarca", "trator", "onibus", "bens moveis")
DOCUMENTOS = [("edital", "edital"), ("matricula", "matricula"), ("laudo", "laudo"), ("avaliacao", "laudo")]


def _texto(frag: str) -> str:
    frag = re.sub(r"<br\s*/?>", " ", frag or "", flags=re.I)
    return re.sub(r"\s+", " ", htmlmod.unescape(re.sub(r"<[^>]+>", " ", frag))).strip()


def _dinheiro(t: str) -> Optional[float]:
    m = re.search(r"R\$\s*([\d.]+,\d{2})", t or "")
    return numero_br(m.group(1)) if m else None


def _rotulo(pagina: str, nome: str) -> str:
    """Valor de '<b>Nome:</b> valor' até a próxima quebra."""
    m = re.search(r"<b>\s*" + nome + r"\s*:?\s*</b>(.*?)(?:<br|</p>|</div>|<b>)", pagina, re.S | re.I)
    return _texto(m.group(1)) if m else ""


def _tipo(titulo: str) -> Optional[str]:
    t = chave(titulo)
    if any(p in t for p in NAO_IMOVEL):
        return None
    t = re.sub(r"^(lote \d+ )?(direitos (sobre|de|do|da) (o |a )?)", "", t)
    for palavra, tipo in TIPOS:
        if re.search(r"\b" + palavra + r"\b", t):
            return tipo
    return None


def _area(texto: str, nomes: str) -> Optional[float]:
    num, uni = r"(\d[\d.]*(?:,\d+)?)", r"\s*m(?:²|2)\b"
    for padrao in (num + uni + r"\s*(?:de\s*)?(?:área\s*)?(?:" + nomes + r")", r"(?:" + nomes + r")\s*(?:de|com)?\s*" + num + uni):
        m = re.search(padrao, texto, re.I)
        if m and numero_br(m.group(1)):
            return numero_br(m.group(1))
    return None


def _bairro(titulo: str) -> str:
    m = re.search(r"\bBairro\s+([A-ZÀ-Ú][\wÀ-ú'. ]+?)(?=\s+-|\s+em\s|\s*\(|\s*,|$)", titulo)
    return m.group(1).strip() if m else ""


def interpretar_lote(pagina: str, url: str, dominio: str, hoje: Optional[str] = None) -> Optional[ImovelCaptado]:
    """Lê a página de um lote. Devolve None se o lote não for imóvel. Formato estranho: ErroDeFonte."""
    if "soleon" not in (re.search(r'<meta name="author" content="([^"]*)"', pagina) or [None, ""])[1].lower():
        raise ErroDeFonte("a página não é de um site da plataforma Soleon (formato mudou?)")
    m_id = re.search(r"/item/(\d+)/detalhes", url or "") or re.search(r'<option value="(\d+)" selected', pagina)
    desc_meta = htmlmod.unescape((re.search(r'<meta name="description" content="([^"]*)"', pagina) or [None, ""])[1])
    titulo = re.sub(r"^\s*lote\s*\d+\s*-\s*", "", desc_meta, flags=re.I).strip()
    cidade_uf = _rotulo(pagina, "Cidade")
    if not (m_id and titulo):
        raise ErroDeFonte("lote Soleon sem número ou título (formato mudou?)")
    matricula = _rotulo(pagina, "Matrícula")
    md = re.search(r"<b>\s*Descrição:\s*</b>(.*?)</div>", pagina, re.S)
    descricao = _texto(md.group(1))[:4000] if md else ""
    tipo = _tipo(titulo) or (_tipo(descricao[:200]) if matricula else None)
    if tipo == "outros" and descricao:                # título genérico ("Imóvel em ..."): a descrição diz o tipo
        tipo = _tipo(descricao[:300]) or tipo
    if tipo is None:
        return None                                   # veículo, máquina, "lote diverso"...: não é imóvel
    if not cidade_uf:
        raise ErroDeFonte("lote de imóvel sem cidade (formato mudou?)")
    partes = [p.strip() for p in cidade_uf.split("/") if p.strip()]
    uf = partes[-1].upper() if partes and partes[-1].upper() in UFS else ""
    if not uf:
        raise ErroDeFonte(f"UF não reconhecida em '{cidade_uf}'")
    cidade = sem_acento(partes[0]).upper()
    preco = _dinheiro(_texto((re.search(r'id="lance_inicial"[^>]*>(.*?)</h3>', pagina, re.S) or [None, ""])[1]))
    avaliacao = _dinheiro(_texto((re.search(r"Valor de Avalia[çc][ãa]o:\s*</strong>(.*?)</h6>", pagina, re.S) or [None, ""])[1]))
    pracas = []
    for m in re.finditer(r"Data\s*(?:(\d)º\s*)?Leil[ãa]o:\s*</strong>\s*(\d{2}/\d{2}/\d{4})\s*(\d{2}:\d{2})", pagina):
        valor = _dinheiro(_texto(re.search(r"Lance Inicial:\s*</strong>(.*?)</h6>", pagina[m.end():m.end() + 400], re.S).group(1))) \
            if re.search(r"Lance Inicial:", pagina[m.end():m.end() + 400]) else None
        d, mth, a = m.group(2).split("/")
        numero = int(m.group(1)) if m.group(1) else 1
        while numero in {p.numero for p in pracas}:
            numero += 1
        pracas.append(Praca(numero=numero, data=f"{a}-{mth}-{d}T{m.group(3)}", valor=valor))
    tipo_venda = ""
    mt = re.search(r'<h6 class="text-center">\s*(LEIL[ÃA]O [A-ZÁ-Ú]+|VENDA DIRETA)\s*</h6>', pagina)
    if mt:
        tipo_venda = mt.group(1).title().replace("Leilão ", "").replace("Leilao ", "")
    leiloeiro = _texto((re.search(r"LEILOEIRO OFICIAL</h5>(.*?)<br", pagina, re.S) or [None, ""])[1])
    comissao = re.search(r"Comiss[ãa]o\s*(?:\(\s*|:\s*)(\d+(?:,\d+)?)\s*%", _texto(pagina))
    incremento = _dinheiro((re.search(r"Incremento M[íi]nimo:\s*([^<]+)", pagina) or [None, ""])[1])
    docs = []
    bloco_docs = pagina[pagina.find('class="arquivos-lote'):]
    for href, rot in re.findall(r'<a class="btn btn-block[^"]*" href="(https://[^"]+)"[^>]*>(.*?)</a>', bloco_docs[:6000], re.S):
        r = chave(_texto(rot))
        t = next((tp for p, tp in DOCUMENTOS if p in r), None)
        if t and not any(d.tipo == t for d in docs):
            docs.append(DocumentoFonte(tipo=t, url=htmlmod.unescape(href), rotulo=_texto(rot)))
    desc_up = descricao.upper()
    ocupacao = "desocupado" if re.search(r"\bDESOCUPAD[OA]\b", desc_up) else "ocupado" if re.search(r"\bOCUPAD[OA]\b", desc_up) else ""
    texto_areas = f"{titulo}. {descricao}"
    privativa = _area(texto_areas, "privativa")
    terreno = _area(texto_areas, r"terreno")
    total = _area(texto_areas, r"total|constru[íi]da|a\.c\.")
    if not (privativa or terreno or total):           # só o título tem a área ("Terreno ... 40.750,0m²")
        m_tit = re.search(r"(\d[\d.]*(?:,\d+)?)\s*m(?:²|2)\b", titulo)
        if m_tit:
            if tipo in ("terreno", "gleba", "imovel rural"):
                terreno = numero_br(m_tit.group(1))
            else:
                total = numero_br(m_tit.group(1))
    endereco = _rotulo(pagina, "Endereço")
    item_id = m_id.group(1)
    lei = DadosLeilao(tipo_venda=tipo_venda, leilao="", lote=_texto((re.search(r'<option value="\d+" selected>([^<]+)', pagina) or [None, ""])[1]).title(),
                      comitente=_rotulo(pagina, "Comitente"), leiloeiro=leiloeiro, ocupacao=ocupacao, matricula=matricula,
                      comissao_pct=numero_br(comissao.group(1)) if comissao else None, incremento=incremento,
                      pracas=pracas, documentos=docs)
    return ImovelCaptado(
        fonte=FONTE, id_fonte=f"{dominio}:{item_id}", uf=uf, cidade=cidade, bairro=_bairro(titulo), endereco=endereco,
        preco=preco, valor_avaliacao=avaliacao,
        desconto_pct=round((1 - preco / avaliacao) * 100, 2) if preco and avaliacao and preco <= avaliacao else None,
        modalidade=tipo_venda or "Leilão", tipo=tipo, area_privativa=privativa, area_terreno=terreno, area_total=total,
        descricao=f"{titulo}. {descricao}"[:4000], link=f"https://www.{dominio}/item/{item_id}/detalhes",
        data_fonte=hoje or datetime.now().strftime("%d/%m/%Y"), leilao=lei)


def leiloes_da_pagina(pagina: str) -> List[dict]:
    """Cartões de leilão: link, título e se está encerrado."""
    saida = []
    partes = re.split(r'class="[^"]*\bbox-leilao\b[^"]*"', pagina)[1:]
    for p in partes:
        link = re.search(r'href="(https?://[^"]*/leilao/\d+/lotes)"', p)
        if not link or any(s["url"] == link.group(1) for s in saida):
            continue
        texto = _texto(p[:4000])
        titulo = _texto((re.search(r'card-title[^>]*>(.*?)</h6>', p, re.S) or [None, ""])[1])
        saida.append({"url": link.group(1), "titulo": titulo, "texto": texto,
                      "encerrado": bool(re.search(r"\bEncerrad[oa]\b|\bFinalizad[oa]\b|\bCancelad[oa]\b", texto[:800]))})
    return saida


def itens_da_pagina(pagina: str) -> List[str]:
    vistos = []
    for href in re.findall(r'href="(https?://[^"]*/item/\d+/detalhes)', pagina):
        if href not in vistos:
            vistos.append(href)
    return vistos


def pode_ter_imovel(cartao: dict) -> bool:
    t = chave(cartao["titulo"] + " " + cartao["texto"][:300])
    if "imove" in t or _tipo(cartao["titulo"]):
        return True
    return not any(p in t for p in NAO_IMOVEL)       # título neutro: abre para conferir


class FonteSoleon:
    """Adaptador da porta FonteDeImoveis para os leiloeiros da plataforma Soleon."""
    nome = FONTE
    rotulo = "Leiloeiros Soleon"
    descricao = f"{len(SITES)} leiloeiros que usam a plataforma Soleon (judiciais e extrajudiciais), lidos dos sites"

    def __init__(self, cliente, relatar: Callable[[str], None] = None, sites: Optional[List[str]] = None):
        self.cliente = cliente
        self.sites = list(sites or SITES)
        self._relatar = relatar or (lambda msg: None)

    def recortes(self) -> List[str]:
        return list(self.sites)

    def _dominio(self, url: str) -> str:
        return urlsplit(url or "").netloc.lower().removeprefix("www.")

    def aceita_url(self, url: str) -> bool:
        p = urlsplit(url or "")
        return p.scheme == "https" and self._dominio(url) in self.sites and bool(re.fullmatch(r"/item/\d+/detalhes/?", p.path))

    def importar_url(self, url: str) -> ImovelCaptado:
        if not self.aceita_url(url):
            raise ErroDeFonte("link não é de um lote de um site Soleon conhecido")
        dominio, caminho = self._dominio(url), urlsplit(url).path
        limpo = f"https://www.{dominio}{caminho}"
        im = interpretar_lote(self.cliente.baixar(limpo).decode("utf-8", "replace"), limpo, dominio)
        if im is None:
            raise ErroDeFonte("este lote não é um imóvel")
        return im

    def coletar(self, recorte: str, arquivo: Optional[bytes] = None, nome_arquivo: str = "",
                limite: Optional[int] = None) -> Coleta:
        dominio = recorte.lower().removeprefix("www.")
        if arquivo is not None:          # uma página de lote salva (testes)
            im = interpretar_lote(arquivo.decode("utf-8", "replace"), nome_arquivo if nome_arquivo.startswith("http") else "", dominio)
            return Coleta(imoveis=[im] if im else [], recorte=dominio, origem=nome_arquivo or "arquivo enviado")
        base = f"https://www.{dominio}"
        avisos, completa, leiloes = [], True, []
        for n in range(1, PAGINAS_MAX + 1):
            try:
                cartoes = leiloes_da_pagina(self.cliente.baixar(f"{base}/leiloes?page={n}").decode("utf-8", "replace"))
            except ErroDeFonte as e:
                avisos.append(f"{dominio} leilões página {n}: {e}"); completa = False
                break
            novos = [c for c in cartoes if c["url"] not in {l["url"] for l in leiloes}]
            leiloes += novos
            if not novos:
                break
        abertos = [l for l in leiloes if not l["encerrado"] and pode_ter_imovel(l)]
        self._relatar(f"  {dominio}: {len(leiloes)} leilões, {len(abertos)} abertos com possível imóvel")
        itens = []
        for l in abertos:
            for n in range(1, PAGINAS_MAX + 1):
                try:
                    pagina_itens = itens_da_pagina(self.cliente.baixar(f"{l['url']}?page={n}").decode("utf-8", "replace"))
                except ErroDeFonte as e:
                    avisos.append(f"{l['url']} página {n}: {e}"); completa = False
                    break
                novos = [i for i in pagina_itens if i not in itens]
                itens += novos
                if not novos:
                    break
            if limite and len(itens) >= limite:
                break
        if limite:
            itens, completa = itens[:limite], False
        imoveis = []
        for url in itens:
            try:
                im = interpretar_lote(self.cliente.baixar(url).decode("utf-8", "replace"), url, dominio)
                if im:
                    imoveis.append(im)
            except ErroDeFonte as e:
                avisos.append(f"{url}: {e}"); completa = False
        return Coleta(imoveis=imoveis, recorte=dominio, origem=f"{base}/leiloes", avisos=avisos, completa=completa)

    def descrever_modalidade(self, modalidade: str) -> Optional[str]:
        m = (modalidade or "").lower()
        if m == "judicial":
            return "Leilão judicial: venda determinada pela Justiça num processo. Confira no edital a vara, as praças e as dívidas."
        if m == "extrajudicial":
            return "Leilão extrajudicial: em geral banco ou empresa vendendo imóvel retomado. Hipótese; confirme no edital."
        if m == "venda direta":
            return "Venda direta: compra sem disputa de lances, nas condições do edital."
        return None
