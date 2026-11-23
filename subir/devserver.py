"""Servidorzinho para testar a tela no navegador, sem o Mac (só para desenvolvimento e testes).

    python -m subir dev --porta 8765

A tela é a mesma do app; a "ponte" é HTTP: POST /msg (tela → Python) e GET /events (Python → tela).
Com SUBIR_FAKE_FALA=1 a transcrição é simulada (o motor de verdade só roda no Mac).
"""
from __future__ import annotations

import json
import os
import queue
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import fala
from .app import App, Bridge

UI = Path(__file__).resolve().parent / "ui" / "index.html"


class HttpBridge(Bridge):
    def __init__(self):
        self.q: queue.Queue = queue.Queue()
        self.opened: list[str] = []
        self.picks: list[str] = [p for p in os.environ.get("SUBIR_DEV_PICK", "").split(os.pathsep) if p]
        self.quit_called = False

    def send(self, msg):
        self.q.put(msg)

    def pick_files(self):
        return list(self.picks)

    def pick_rclone(self):
        return os.environ.get("SUBIR_DEV_RCLONE")

    def open_url(self, url):
        self.opened.append(url)
        self.send({"type": "toast", "text": "(teste) abriria: " + url})

    def open_file(self, path):
        self.opened.append(path)

    def quit(self):
        self.quit_called = True
        self.send({"type": "toast", "text": "(teste) o app fecharia agora"})


def fake_transcriber(path, progress=None, cancel=None, proc_holder=None):
    n = int(os.environ.get("SUBIR_FAKE_CHUNKS", "4"))
    step = float(os.environ.get("SUBIR_FAKE_STEP", "0.4"))
    if "semfala" in Path(path).name:
        time.sleep(step)
        raise fala.SpeechError("sem_fala")
    if progress:
        progress(0.0, 0, n)
    time.sleep(step)
    for k in range(n):
        if cancel is not None and cancel.is_set():
            raise fala.Cancelled()
        if progress:
            progress(k / n, k + 1, n)
        time.sleep(step)
    words = [[1.0, 1.4, "Olá,", 0.9], [1.5, 1.9, "pessoal.", 0.95]]
    return fala.build(Path(path).name, 10.0, words, [[1.0, 1.9, "Olá, pessoal."]], model=fala.MODEL_NAME)


def serve(port: int = 8765):
    bridge = HttpBridge()
    if os.environ.get("SUBIR_FAKE_FALA"):
        fala.available = lambda: True
    app = App(bridge)
    if os.environ.get("SUBIR_FAKE_FALA"):
        import subir.job as jobmod
        orig = jobmod.Job.__init__

        def init(self, *a, **k):
            orig(self, *a, **k)
            self.transcriber = fake_transcriber
        jobmod.Job.__init__ = init

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                body = UI.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path == "/events":
                out = []
                try:
                    out.append(bridge.q.get(timeout=20))
                    while True:
                        out.append(bridge.q.get_nowait())
                except queue.Empty:
                    pass
                body = json.dumps(out).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path == "/state":
                body = json.dumps({"opened": bridge.opened, "quit": bridge.quit_called}).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(404)
            self.end_headers()

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(n) or b"{}")
            if self.path == "/msg":
                app.handle(data)
            elif self.path == "/drop":           # simula arrastar arquivos para a janela/ícone
                app.add_files(data.get("paths") or [])
            self.send_response(204)
            self.end_headers()

    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    print(f"tela de teste em http://127.0.0.1:{port}", flush=True)
    srv.serve_forever()
