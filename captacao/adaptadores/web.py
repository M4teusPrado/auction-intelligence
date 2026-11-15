"""Acesso educado à web, igual para todas as fontes que leem sites.

- Respeita o robots.txt de cada site (e o Crawl-delay, se houver).
- Espera um intervalo mínimo entre pedidos ao mesmo site (padrão: 3 segundos).
- Guarda cópia local das páginas por algumas horas, para não pedir a mesma página duas vezes.
- Se identifica com um nome genérico do projeto, sem dados pessoais.
Falha de acesso vira ErroDeFonte com mensagem clara.
"""
import hashlib
import os
import time
import urllib.error
import urllib.request
import urllib.robotparser
from typing import Callable, Dict, Optional
from urllib.parse import urlsplit

from ..aplicacao.portas import ErroDeFonte

AGENTE = "captacao-imoveis/0.1 (coleta diaria, uso interno)"
TAMANHO_MAX = 30 * 1024 * 1024


class ClienteWeb:
    def __init__(self, agente: str = AGENTE, intervalo: float = 3.0, timeout: float = 30.0,
                 pasta_cache: Optional[str] = None, validade_cache_h: float = 20.0,
                 abrir: Callable = None, dormir: Callable[[float], None] = time.sleep,
                 relogio: Callable[[], float] = time.monotonic):
        self.agente, self.intervalo, self.timeout = agente, intervalo, timeout
        self.pasta_cache, self.validade_cache = pasta_cache, validade_cache_h * 3600
        self._abrir = abrir or urllib.request.urlopen     # trocável nos testes
        self._dormir, self._relogio = dormir, relogio
        self._robots: Dict[str, urllib.robotparser.RobotFileParser] = {}
        self._ultimo: Dict[str, float] = {}
        self.pedidos = 0                                   # pedidos de fato feitos à rede

    # ---------------------------------------------------------------- robots e ritmo
    def _pedir(self, url: str) -> bytes:
        host = urlsplit(url).netloc
        espera = self._intervalo_do_host(host) - (self._relogio() - self._ultimo.get(host, -1e9))
        if espera > 0:
            self._dormir(espera)
        req = urllib.request.Request(url, headers={"User-Agent": self.agente, "Accept-Language": "pt-BR"})
        try:
            with self._abrir(req, timeout=self.timeout) as resp:
                dados = resp.read(TAMANHO_MAX + 1)
        except urllib.error.HTTPError as e:
            raise ErroDeFonte(f"o site respondeu {e.code} para {url}")
        except (urllib.error.URLError, OSError) as e:
            raise ErroDeFonte(f"não foi possível acessar {url} ({e})")
        finally:
            self._ultimo[host] = self._relogio()
            self.pedidos += 1
        if len(dados) > TAMANHO_MAX:
            raise ErroDeFonte(f"resposta grande demais de {url}")
        return dados

    def _regras(self, url: str) -> urllib.robotparser.RobotFileParser:
        p = urlsplit(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                texto = self._pedir(base + "/robots.txt").decode("utf-8", "replace")
            except ErroDeFonte as e:
                texto = "" if "respondeu 404" in str(e) else None    # sem robots.txt = sem restrições
            if texto is None:      # robots.txt inacessível (não 404): por cautela, não coleta
                rp.disallow_all = True
            else:
                rp.parse(texto.splitlines())
            self._robots[base] = rp
        return self._robots[base]

    def _intervalo_do_host(self, host: str) -> float:
        rp = self._robots.get(f"https://{host}") or self._robots.get(f"http://{host}")
        atraso = rp.crawl_delay(self.agente) if rp else None
        return max(self.intervalo, float(atraso or 0))

    def permitido(self, url: str) -> bool:
        return self._regras(url).can_fetch(self.agente, url)

    # ---------------------------------------------------------------- uso
    def baixar(self, url: str, usar_cache: bool = True, sob_demanda: bool = False) -> bytes:
        """sob_demanda=True: um documento pedido por causa de uma decisão humana (imóvel em
        'Para analisar'), não uma varredura. Por decisão do Mateus (15/11/2026), nesse caso o
        robots.txt não impede o pedido; ritmo e identificação continuam valendo."""
        p = urlsplit(url)
        if p.scheme not in ("https", "http") or not p.netloc:
            raise ErroDeFonte(f"endereço inválido: {url}")
        if not sob_demanda and not self.permitido(url):
            raise ErroDeFonte(f"o robots.txt de {p.netloc} não permite acessar {p.path}")
        caminho = self._arquivo_cache(url)
        if usar_cache and caminho and os.path.isfile(caminho) and time.time() - os.path.getmtime(caminho) < self.validade_cache:
            with open(caminho, "rb") as f:
                return f.read()
        dados = self._pedir(url)
        if caminho:
            os.makedirs(os.path.dirname(caminho), exist_ok=True)
            with open(caminho, "wb") as f:
                f.write(dados)
        return dados

    def _arquivo_cache(self, url: str) -> Optional[str]:
        if not self.pasta_cache:
            return None
        h = hashlib.sha256(url.encode()).hexdigest()
        return os.path.join(self.pasta_cache, urlsplit(url).netloc, h[:2], h)
