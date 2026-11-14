"""Servidor local da tela de triagem. Só biblioteca padrão; escuta apenas em 127.0.0.1.

Rotas:
  GET  /                              captacao/web/index.html
  GET  /api/resumo | /api/opcoes | /api/imoveis?...
  POST /api/imoveis/<id>/triagem      {"para": "...", "nota": "..."} ou {"desfazer": true}
"""
import json
import os
import re
import sqlite3
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from . import repositorio, triagem

HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "index.html")
CORPO_MAX = 16 * 1024
ROTA_TRIAGEM = re.compile(r"^/api/imoveis/(\d{1,12})/triagem$")


def _criar_handler(caminho_base: str, porta: int):
    hosts_validos = {f"127.0.0.1:{porta}", f"localhost:{porta}"}

    class Handler(BaseHTTPRequestHandler):
        server_version = "captacao"
        sys_version = ""

        def log_message(self, fmt, *args):            # log curto no terminal
            sys.stderr.write(f"  {self.command} {self.path[:120]} -> {args[1] if len(args) > 1 else ''}\n")

        def _con(self):
            con = sqlite3.connect(caminho_base, timeout=10)
            con.row_factory = sqlite3.Row
            return con

        def _enviar(self, status: int, corpo: bytes, tipo: str):
            self.send_response(status)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(corpo)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                             "script-src 'self' 'unsafe-inline'; img-src 'self' data:")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(corpo)

        def _json(self, status: int, dados):
            self._enviar(status, json.dumps(dados, ensure_ascii=False).encode("utf-8"),
                         "application/json; charset=utf-8")

        def _host_ok(self) -> bool:
            # protege contra DNS rebinding: só aceita o próprio endereço local
            if self.headers.get("Host", "") in hosts_validos:
                return True
            self._json(403, {"erro": "acesso permitido só por 127.0.0.1"})
            return False

        def _executar(self, funcao, *args):
            con = self._con()
            try:
                self._json(200, funcao(con, *args))
            except triagem.EntradaInvalida as e:
                self._json(400, {"erro": str(e)})
            except triagem.NaoEncontrado as e:
                self._json(404, {"erro": str(e)})
            except Exception as e:                    # erro inesperado: mensagem genérica
                sys.stderr.write(f"  ERRO: {e!r}\n")
                self._json(500, {"erro": "erro interno; veja o terminal"})
            finally:
                con.close()

        def do_GET(self):
            if not self._host_ok():
                return
            url = urlsplit(self.path)
            if url.path in ("/", "/index.html"):
                with open(HTML, "rb") as f:
                    self._enviar(200, f.read(), "text/html; charset=utf-8")
            elif url.path == "/api/resumo":
                self._executar(triagem.resumo)
            elif url.path == "/api/opcoes":
                self._executar(triagem.opcoes)
            elif url.path == "/api/imoveis":
                params = parse_qs(url.query, keep_blank_values=True, max_num_fields=100)
                self._executar(triagem.listar, params)
            else:
                self._json(404, {"erro": "rota não encontrada"})

        do_HEAD = do_GET

        def do_POST(self):
            if not self._host_ok():
                return
            m = ROTA_TRIAGEM.match(urlsplit(self.path).path)
            if not m:
                return self._json(404, {"erro": "rota não encontrada"})
            # exigir JSON impede envio por formulário de outro site (CSRF)
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                return self._json(415, {"erro": "envie Content-Type: application/json"})
            try:
                tamanho = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return self._json(400, {"erro": "Content-Length inválido"})
            if not 0 < tamanho <= CORPO_MAX:
                return self._json(413 if tamanho > CORPO_MAX else 400, {"erro": "corpo vazio ou grande demais"})
            try:
                corpo = json.loads(self.rfile.read(tamanho).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return self._json(400, {"erro": "JSON inválido"})
            self._executar(triagem.triar, int(m.group(1)), corpo)

    return Handler


def rodar(caminho_base: str, porta: int = 8765, abrir_navegador: bool = True) -> int:
    if not os.path.exists(caminho_base):
        print(f"Base não encontrada: {caminho_base}. Rode antes: python -m captacao coletar --uf SP",
              file=sys.stderr)
        return 1
    repositorio.conectar(caminho_base).close()        # migra o esquema (com cópia) se preciso
    try:
        servidor = ThreadingHTTPServer(("127.0.0.1", porta), _criar_handler(caminho_base, porta))
    except OSError as e:
        print(f"Não foi possível usar a porta {porta}: {e}. Tente --porta 8766.", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{porta}/"
    print(f"Tela de triagem em {url}  (base: {os.path.abspath(caminho_base)})")
    print("Ctrl+C para encerrar.")
    if abrir_navegador:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrado.")
    finally:
        servidor.server_close()
    return 0
