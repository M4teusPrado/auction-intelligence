"""Servidor local da tela de triagem. Só biblioteca padrão; escuta apenas em 127.0.0.1.

Rotas:
  GET  /                              captacao/web/index.html
  GET  /api/resumo | /api/opcoes | /api/imoveis?...
  GET  /api/imoveis/<id>                       ficha do imóvel
  POST /api/imoveis/<id>/triagem               {"para": "...", "nota": "..."} ou {"desfazer": true}
  POST /api/imoveis/<id>/investigacao          {"item": "...", "status": "...", "nota": "..."}
  POST /api/imoveis/<id>/simulacao             {"premissas": {...}}  (salva)
  POST /api/simular                            {"premissas": {...}}  (só calcula)
  POST /api/imoveis/<id>/anexos?tipo=matricula corpo = o arquivo (PDF, PNG ou JPG)
  GET  /anexos/<id>                            abre um anexo
  POST /api/importar                           {"url": "..."}  importa uma oferta pelo link
  POST /api/imoveis/<id>/documentos-fonte      baixa edital/matrícula publicados pela fonte
  POST /api/imoveis/<id>/parecer               gera o parecer preliminar com IA (só sugere)
  POST /api/anexos/<id>/transcrever            PDF escaneado: a IA transcreve o texto
  POST /api/editais-caixa {url}                 indexa um edital da Caixa e liga aos imóveis dele
"""
import json
import os
import re
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from . import montagem
from .aplicacao import ficha, triagem
from .aplicacao.coletar import importar_link
from .aplicacao.parecer import gerar_parecer
from .aplicacao.portas import EntradaInvalida, ErroDeAnalise, ErroDeFonte, NaoEncontrado

HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "index.html")
# pdf.js 4.10.38 (Apache 2.0), aprovado pelo Mateus em 16/11/2026: leitor de PDF com trecho em destaque
VENDOR = {"/vendor/pdfjs/pdf.min.mjs", "/vendor/pdfjs/pdf.worker.min.mjs"}
CORPO_MAX = 16 * 1024
ROTA_IMOVEL = re.compile(r"^/api/imoveis/(\d{1,12})(?:/(triagem|investigacao|simulacao|anexos|documentos-fonte|parecer|tarefas))?$")
ROTA_ANEXO = re.compile(r"^/anexos/(\d{1,12})$")
ROTA_TRANSCREVER = re.compile(r"^/api/anexos/(\d{1,12})/transcrever$")
TIPOS_UPLOAD = {"application/pdf", "image/png", "image/jpeg"}


EM_BUSCA = set()                 # imóveis com busca de documentos em andamento (a ficha mostra o aviso)
_TRAVA_BUSCA = threading.Lock()  # uma busca de edital da Caixa por vez: evita pedidos repetidos ao site


def baixar_em_segundo_plano(caminho_base: str, pasta_anexos: str, imovel_id: int) -> None:
    """Imóvel marcado 'Para analisar': baixa os documentos da fonte sem travar a tela. Imóvel da Caixa
    sem edital conhecido: procura o edital pelo número (pode levar alguns minutos na primeira vez)."""
    if imovel_id in EM_BUSCA:
        return
    EM_BUSCA.add(imovel_id)

    def tarefa():
        try:
            with montagem.repositorio(caminho_base, migrar=False) as repo:
                repo.ligar_editais_de_leiloeiros()
                if (repo.buscar_imovel(imovel_id) or {}).get("fonte") == "caixa":
                    with _TRAVA_BUSCA:
                        r = ficha.buscar_edital_caixa(repo, pasta_anexos, montagem.CLIENTE_WEB, imovel_id, montagem.FONTES)
                    sys.stderr.write(f"  edital da Caixa do imóvel {imovel_id}: "
                                     f"{'encontrado' if r['encontrado'] else 'não encontrado'} ({r['consultados']} consultas)\n")
                if ficha.documentos_pendentes(repo, imovel_id, montagem.FONTES):
                    r = ficha.baixar_documentos_fonte(repo, pasta_anexos, imovel_id, montagem.CLIENTE_WEB,
                                                      fontes=montagem.FONTES)
                    sys.stderr.write(f"  documentos do imóvel {imovel_id}: {len(r['baixados'])} baixados, "
                                     f"{len(r['erros'])} com erro\n")
        except Exception as e:                        # erro aqui não pode derrubar o servidor
            sys.stderr.write(f"  documentos do imóvel {imovel_id}: falhou ({e!r})\n")
        finally:
            EM_BUSCA.discard(imovel_id)
    threading.Thread(target=tarefa, daemon=True).start()


def _criar_handler(caminho_base: str, porta: int):
    pasta_anexos = os.path.join(os.path.dirname(os.path.abspath(caminho_base)), "anexos")
    hosts_validos = {f"127.0.0.1:{porta}", f"localhost:{porta}"}

    class Handler(BaseHTTPRequestHandler):
        server_version = "captacao"
        sys_version = ""

        def log_message(self, fmt, *args):            # log curto no terminal
            sys.stderr.write(f"  {self.command} {self.path[:120]} -> {args[1] if len(args) > 1 else ''}\n")

        def _repo(self):
            # esquema já migrado na partida; cada requisição abre e fecha sua conexão
            return montagem.repositorio(caminho_base, migrar=False)

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
            repo = self._repo()
            try:
                self._json(200, funcao(repo, *args))
            except EntradaInvalida as e:
                self._json(400, {"erro": str(e)})
            except NaoEncontrado as e:
                self._json(404, {"erro": str(e)})
            except ErroDeFonte as e:                  # site da fonte fora do ar, bloqueio, formato mudou
                self._json(502, {"erro": f"Não foi possível ler a fonte: {e}"})
            except ErroDeAnalise as e:                # IA sem credencial, recusa, limite...
                self._json(503, {"erro": f"Análise com IA indisponível: {e}"})
            except Exception as e:                    # erro inesperado: mensagem genérica
                sys.stderr.write(f"  ERRO: {e!r}\n")
                self._json(500, {"erro": "erro interno; veja o terminal"})
            finally:
                repo.close()

        def do_GET(self):
            if not self._host_ok():
                return
            url = urlsplit(self.path)
            if url.path in ("/", "/index.html"):
                with open(HTML, "rb") as f:
                    self._enviar(200, f.read(), "text/html; charset=utf-8")
            elif url.path in VENDOR:
                with open(os.path.join(os.path.dirname(HTML), url.path.lstrip("/")), "rb") as f:
                    self._enviar(200, f.read(), "text/javascript; charset=utf-8")
            elif url.path == "/api/resumo":
                self._executar(triagem.resumo)
            elif url.path == "/api/opcoes":
                nomes = {f.nome: f.rotulo for f in montagem.FONTES.values()}
                self._executar(lambda repo: {**triagem.opcoes(repo), "nomes_fontes": nomes})
            elif url.path == "/api/imoveis":
                params = parse_qs(url.query, keep_blank_values=True, max_num_fields=100)
                self._executar(triagem.listar, params)
            elif (m := ROTA_IMOVEL.match(url.path)) and m.group(2) is None:
                self._executar(lambda repo: {**ficha.ficha(repo, int(m.group(1)), pasta_anexos, montagem.FONTES, montagem.ANALISADOR),
                                             "buscando_documentos": int(m.group(1)) in EM_BUSCA})
            elif m := ROTA_ANEXO.match(url.path):
                self._enviar_anexo(int(m.group(1)))
            else:
                self._json(404, {"erro": "rota não encontrada"})

        do_HEAD = do_GET

        def _enviar_anexo(self, anexo_id: int):
            repo = self._repo()
            try:
                caminho, nome, mime = ficha.arquivo_anexo(repo, pasta_anexos, anexo_id)
            except NaoEncontrado as e:
                return self._json(404, {"erro": str(e)})
            finally:
                repo.close()
            with open(caminho, "rb") as f:
                dados = f.read()
            nome_ascii = re.sub(r"[^A-Za-z0-9._ -]", "_", nome)
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(dados)))
            self.send_header("Content-Disposition", f'inline; filename="{nome_ascii}"')
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(dados)

        def _ler_corpo(self, maximo: int):
            try:
                tamanho = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._json(400, {"erro": "Content-Length inválido"}); return None
            if tamanho <= 0:
                self._json(400, {"erro": "corpo vazio"}); return None
            if tamanho > maximo:
                self._json(413, {"erro": f"corpo maior que {maximo // 1024 // 1024 or 1} MB"}); return None
            return self.rfile.read(tamanho)

        def do_POST(self):
            if not self._host_ok():
                return
            url = urlsplit(self.path)
            tipo_corpo = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
            m = ROTA_IMOVEL.match(url.path)
            if m and m.group(2) == "anexos":
                # tipos não-"simples" exigem preflight CORS: outro site não consegue enviar
                if tipo_corpo not in TIPOS_UPLOAD:
                    return self._json(415, {"erro": "envie o arquivo com Content-Type PDF, PNG ou JPG"})
                dados = self._ler_corpo(ficha.ANEXO_MAX)
                if dados is None:
                    return
                q = parse_qs(url.query)
                nome = unquote(self.headers.get("X-Nome-Arquivo", ""))
                return self._executar(lambda repo: ficha.anexar(
                    repo, pasta_anexos, int(m.group(1)), (q.get("tipo") or [""])[0], nome, dados))
            mt = ROTA_TRANSCREVER.match(url.path)
            if mt:
                return self._executar(lambda repo: ficha.transcrever_anexo(repo, pasta_anexos, montagem.ANALISADOR, int(mt.group(1))))
            if url.path not in ("/api/simular", "/api/importar", "/api/editais-caixa") and not (m and m.group(2)):
                return self._json(404, {"erro": "rota não encontrada"})
            # exigir JSON impede envio por formulário de outro site (CSRF)
            if tipo_corpo != "application/json":
                return self._json(415, {"erro": "envie Content-Type: application/json"})
            bruto = self._ler_corpo(CORPO_MAX)
            if bruto is None:
                return
            try:
                corpo = json.loads(bruto.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return self._json(400, {"erro": "JSON inválido"})
            if url.path == "/api/simular":
                return self._executar(lambda repo: ficha.simular(corpo))
            if url.path == "/api/editais-caixa":
                if not isinstance(corpo, dict) or set(corpo) != {"url"}:
                    return self._json(400, {"erro": "envie {\"url\": \"...\"}"})
                return self._executar(lambda repo: ficha.indexar_edital_caixa(
                    repo, pasta_anexos, montagem.CLIENTE_WEB, str(corpo["url"]), montagem.FONTES))
            if url.path == "/api/importar":
                if not isinstance(corpo, dict) or set(corpo) != {"url"}:
                    return self._json(400, {"erro": "envie {\"url\": \"...\"}"})
                return self._executar(lambda repo: importar_link(montagem.FONTES, repo, corpo["url"]))
            if m.group(2) == "parecer":
                def parecer(repo):
                    iid = int(m.group(1))
                    t = ficha.transcrever_pendentes(repo, pasta_anexos, montagem.ANALISADOR, iid)
                    r = gerar_parecer(repo, montagem.ANALISADOR, iid)
                    if t["custo_usd"]:
                        r["uso"]["custo_transcricao_usd"] = t["custo_usd"]
                    return {**r, "transcricao": t}
                return self._executar(parecer)
            if m.group(2) == "documentos-fonte":
                def baixar_agora(repo):
                    iid = int(m.group(1))
                    r = ficha.baixar_documentos_fonte(repo, pasta_anexos, iid, montagem.CLIENTE_WEB, fontes=montagem.FONTES)
                    sem_edital = (repo.buscar_imovel(iid) or {}).get("fonte") == "caixa" and not any(
                        d["tipo"] == "edital" for d in ficha.documentos_da_fonte(repo.buscar_imovel(iid), montagem.FONTES))
                    if sem_edital:
                        baixar_em_segundo_plano(caminho_base, pasta_anexos, iid)
                    return {**r, "buscando_edital": sem_edital}
                return self._executar(baixar_agora)
            if m.group(2) == "triagem":
                def triar_e_baixar(repo):
                    im = triagem.triar(repo, int(m.group(1)), corpo)
                    if im.get("estagio") == "analisar":
                        baixar_em_segundo_plano(caminho_base, pasta_anexos, int(m.group(1)))
                    return im
                return self._executar(triar_e_baixar)
            acao = {"triagem": triagem.triar, "investigacao": ficha.investigar,
                    "simulacao": ficha.salvar_simulacao, "tarefas": ficha.marcar_tarefa}[m.group(2)]
            self._executar(acao, int(m.group(1)), corpo)

    return Handler


def rodar(caminho_base: str, porta: int = 8765, abrir_navegador: bool = True) -> int:
    if not os.path.exists(caminho_base):
        print(f"Base não encontrada: {caminho_base}. Rode antes: python -m captacao coletar --uf SP",
              file=sys.stderr)
        return 1
    montagem.repositorio(caminho_base).close()        # migra o esquema (com cópia) se preciso
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
