"""Um envio: os vídeos sobem um de cada vez e, AO MESMO TEMPO, cada vídeo é transcrito.

Regras (pedido do JP, 23/11/2026):
- A transcrição nunca atrasa o envio: o vídeo começa a subir na hora; a transcrição roda em paralelo.
- O .transcricao.json (pequeno) sobe quando a transcrição fica pronta E o vídeo já subiu.
- Se o editor fechar o app antes, o vídeo subiu do mesmo jeito; só falta a transcrição (o Revisor ouve
  sozinho, como sempre).
- A transcrição vai para a pasta "Transcrições" AO LADO da pasta onde o vídeo fica (irmã dela), fora da
  Saída, para não ir para o servidor/NAS junto com os vídeos. Vale para qualquer pasta escolhida.
- Pasta arrastada (ex.: a "Saída" inteira): cada arquivo de dentro sobe para <destino>/<pasta>/…, e os
  vídeos de dentro também são transcritos (Transcrições fica ao lado da pasta enviada).
- Cada envio gera a transcrição de novo (vídeo corrigido = outra duração = transcrição nova).
"""
from __future__ import annotations

import os
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import fala
from .rclone import TRANSCRICOES, DriveError, Loc, Rclone, is_transcricoes


def work_root() -> Path:
    if os.environ.get("SUBIR_WORK_DIR"):
        return Path(os.environ["SUBIR_WORK_DIR"])
    return Path.home() / "Library" / "Caches" / "SubirNoDrive"


def transcription_dest(rc: Rclone, dest: Loc) -> tuple[Loc | None, str]:
    """Pasta "Transcrições" ao lado da pasta escolhida (usa a que já existir, com ou sem acento).
    Devolve (pasta, "") ou (None, motivo)."""
    parent = dest.parent()
    if parent is None:
        if dest.fid:
            return None, ("Esta pasta veio de um link e não está dentro da pasta inicial: não sei qual pasta "
                          "fica ao lado dela. A transcrição fica desligada neste envio.")
        return None, "A pasta inicial não tem pasta ao lado. Escolha uma pasta dentro dela para transcrever."
    try:
        names = rc.list_dirs(parent)
    except DriveError:
        names = []
    name = next((n for n in names if is_transcricoes(n)), TRANSCRICOES)
    return parent.child(name), ""


@dataclass
class Item:
    id: int
    path: str
    name: str
    is_dir: bool
    size: int
    sub: list = field(default_factory=list)      # pastas a partir do destino (ex.: ["Saída"] se veio numa pasta)
    tr_dest: Loc | None = None                     # pasta "Transcrições" deste vídeo
    # envio do vídeo: fila | enviando | ok | erro | cancelado
    up: str = "fila"
    up_bytes: float = 0.0
    up_total: float = 0.0
    up_speed: float = 0.0
    up_eta: float | None = None
    up_err: str = ""
    up_kind: str = ""
    # transcrição: fila | ouvindo | pronta | enviando | ok | erro | sem_fala | sem_audio | desligada
    #              | nao_se_aplica | cancelada
    tr: str = "fila"
    tr_frac: float = 0.0
    tr_chunk: int = 0
    tr_chunks: int = 0
    tr_eta: float | None = None
    tr_err: str = ""
    tr_file: str = ""
    tr_t0: float = 0.0

    def view(self) -> dict:
        return {k: getattr(self, k) for k in (
            "id", "name", "is_dir", "size", "sub", "up", "up_bytes", "up_total", "up_speed", "up_eta", "up_err",
            "up_kind", "tr", "tr_frac", "tr_chunk", "tr_chunks", "tr_eta", "tr_err")}


def size_of(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    tot = 0
    for f in p.rglob("*"):
        if f.is_file():
            try:
                tot += f.stat().st_size
            except OSError:
                pass
    return tot


def _visible(p: Path, base: Path) -> bool:
    return not any(part.startswith(".") for part in p.relative_to(base).parts)


def make_items(paths: list[str], transcribe: bool) -> list[Item]:
    """Um item por arquivo. Uma pasta arrastada (ex.: "Saída") vira um item por arquivo de dentro, que sobe
    para <destino>/<pasta>/…: assim os vídeos de dentro também são transcritos (pedido do JP, 26/11/2026)."""
    items: list[Item] = []

    def add(f: Path, sub: list):
        it = Item(len(items), str(f), f.name, False, f.stat().st_size, list(sub))
        if not fala.is_video(f):
            it.tr = "nao_se_aplica"
        elif not transcribe:
            it.tr = "desligada"
        items.append(it)

    for s in paths:
        p = Path(s)
        if p.is_dir():
            for f in sorted(p.rglob("*"), key=lambda x: str(x.relative_to(p)).lower()):
                if f.is_file() and _visible(f, p):
                    add(f, [p.name] + list(f.relative_to(p).parent.parts))
        elif p.is_file():
            add(p, [])
    return items


def landing(dest: Loc, it: Item) -> Loc:
    """Pasta do Drive onde o arquivo vai ficar."""
    loc = dest
    for part in it.sub:
        loc = loc.child(part)
    return loc


def assign_transcription_dests(rc: Rclone, dest: Loc, items: list[Item]) -> str:
    """Escolhe a pasta "Transcrições" de cada vídeo: ao lado da pasta onde o vídeo fica.
    Devolve o motivo quando algum vídeo fica sem transcrição."""
    cache: dict[str, tuple] = {}
    why = ""
    for it in items:
        if it.tr != "fila":
            continue
        land = landing(dest, it)
        key = repr(land.to_dict())
        if key not in cache:
            cache[key] = transcription_dest(rc, land)
        it.tr_dest, w = cache[key]
        if it.tr_dest is None:
            it.tr = "desligada"
            why = why or w
    return why


@dataclass
class Job:
    rc: Rclone
    items: list[Item]
    dest: Loc
    on_change: object = None                     # chamada (sem argumentos) quando algo muda
    transcriber: object = None                   # para testes: função(video, progress, cancel, holder) -> dict
    cancel_ev: threading.Event = field(default_factory=threading.Event)
    procs: list = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock)
    threads: list = field(default_factory=list)
    started: float = 0.0
    up_running: bool = False
    tr_running: bool = False
    work: Path | None = None

    # ---------------------------------------------------------------- começar / tentar de novo
    def start(self) -> None:
        self.started = time.time()
        self.cancel_ev.clear()
        if self.work is None:
            self.work = work_root() / time.strftime("envio-%Y%m%d-%H%M%S")
            self.work.mkdir(parents=True, exist_ok=True)
        with self.lock:
            for it in self.items:
                if it.up in ("erro", "cancelado"):
                    it.up, it.up_err, it.up_kind, it.up_bytes = "fila", "", "", 0.0
                if it.tr in ("erro", "cancelada"):
                    it.tr, it.tr_err = ("pronta" if it.tr_file else "fila"), ""
                if it.tr == "pronta" and it.tr_dest is None:
                    it.tr = "erro"
                if it.tr == "fila" and it.tr_dest is None:
                    it.tr = "desligada"
            self.up_running = any(it.up == "fila" for it in self.items)
            self.tr_running = any(it.tr == "fila" for it in self.items)
        self.threads = []
        if self.up_running:
            self.threads.append(threading.Thread(target=self._upload_loop, name="envio", daemon=True))
        if self.tr_running:
            self.threads.append(threading.Thread(target=self._transcribe_loop, name="fala", daemon=True))
        for t in self.threads:
            t.start()
        # transcrições prontas de antes, cujo vídeo já subiu (tentar de novo depois de erro no envio delas)
        for it in self.items:
            self._maybe_send_tr(it)
        self._changed()

    def retry(self) -> None:
        if self.busy:
            return
        self.start()

    # ---------------------------------------------------------------- estado
    @property
    def busy(self) -> bool:
        return self.up_running or self.tr_running or any(it.tr == "enviando" for it in self.items)

    @property
    def videos_done(self) -> bool:
        return not self.up_running

    @property
    def pending_tr(self) -> list[Item]:
        """Transcrições que ainda não chegaram ao Drive mas podem chegar (para o aviso ao fechar)."""
        return [it for it in self.items if it.tr in ("fila", "ouvindo", "pronta", "enviando")]

    def view(self) -> dict:
        with self.lock:
            items = [it.view() for it in self.items]
        failed_up = [i for i in items if i["up"] in ("erro", "cancelado")]
        return {"items": items, "busy": self.busy, "videos_done": self.videos_done,
                "up_running": self.up_running, "tr_running": self.tr_running,
                "failed": len(failed_up),
                "retryable": bool(failed_up) or any(i["tr"] in ("erro",) for i in items),
                "pending_tr": len(self.pending_tr)}

    def _changed(self) -> None:
        if self.on_change:
            try:
                self.on_change()
            except Exception:
                pass

    # ---------------------------------------------------------------- envio dos vídeos
    def _upload_loop(self) -> None:
        try:
            for it in self.items:
                if self.cancel_ev.is_set():
                    break
                if it.up != "fila":
                    continue
                with self.lock:
                    it.up, it.up_bytes, it.up_total = "enviando", 0.0, float(it.size)
                self._changed()
                last = [0.0]

                def prog(b, total, speed, eta, it=it, last=last):
                    with self.lock:
                        it.up_bytes, it.up_total = b, (total or it.up_total)
                        it.up_speed, it.up_eta = speed, eta
                    if time.time() - last[0] > 0.4:
                        last[0] = time.time()
                        self._changed()
                try:
                    self.rc.copy(it.path, landing(self.dest, it), it.name, progress=prog, proc_holder=self.procs)
                except DriveError as e:
                    with self.lock:
                        if self.cancel_ev.is_set():
                            it.up, it.up_err = "cancelado", "Envio cancelado."
                        else:
                            it.up, it.up_err, it.up_kind = "erro", str(e), e.kind
                    self._changed()
                    continue
                with self.lock:
                    it.up = "ok"
                    it.up_bytes = it.up_total = float(it.up_total or it.size)
                self._changed()
                self._maybe_send_tr(it)
        finally:
            with self.lock:
                if self.cancel_ev.is_set():
                    for it in self.items:
                        if it.up in ("fila", "enviando"):
                            it.up, it.up_err = "cancelado", "Envio cancelado."
                self.up_running = False
            self._changed()

    # ---------------------------------------------------------------- transcrição
    def _transcribe_loop(self) -> None:
        try:
            for it in self.items:
                if self.cancel_ev.is_set():
                    break
                if it.tr != "fila":
                    continue
                with self.lock:
                    it.tr, it.tr_frac, it.tr_chunk, it.tr_chunks, it.tr_eta = "ouvindo", 0.0, 0, 0, None
                    it.tr_t0 = time.time()
                self._changed()

                def prog(frac, chunk, chunks, it=it):
                    with self.lock:
                        it.tr_frac, it.tr_chunk, it.tr_chunks = frac, chunk, chunks
                        el = time.time() - it.tr_t0
                        it.tr_eta = el / frac * (1 - frac) if frac > 0.04 else None
                    self._changed()
                try:
                    fn = self.transcriber or fala.transcribe_video
                    data = fn(it.path, progress=prog, cancel=self.cancel_ev, proc_holder=self.procs)
                    p = fala.write(self.work / str(it.id), it.name, data)
                except fala.Cancelled:
                    with self.lock:
                        it.tr = "cancelada"
                    break
                except fala.SpeechError as e:
                    msg = str(e)
                    with self.lock:
                        if self.cancel_ev.is_set():
                            it.tr = "cancelada"
                        elif msg == "sem_fala":
                            it.tr, it.tr_err = "sem_fala", "não encontrei fala no áudio"
                        elif msg == "sem_audio":
                            it.tr, it.tr_err = "sem_audio", "o vídeo não tem áudio"
                        else:
                            it.tr, it.tr_err = "erro", msg[-300:]
                    self._changed()
                    continue
                except Exception as e:          # nunca derrubar o envio por causa da transcrição
                    with self.lock:
                        it.tr, it.tr_err = "erro", f"{type(e).__name__}: {e}"[-300:]
                    self._changed()
                    continue
                with self.lock:
                    it.tr, it.tr_file, it.tr_frac, it.tr_eta = "pronta", str(p), 1.0, 0.0
                self._changed()
                self._maybe_send_tr(it)
        finally:
            with self.lock:
                if self.cancel_ev.is_set():
                    for it in self.items:
                        if it.tr in ("fila", "ouvindo"):
                            it.tr = "cancelada"
                self.tr_running = False
            self._changed()

    def _maybe_send_tr(self, it: Item) -> None:
        """Sobe a transcrição quando ela está pronta e o vídeo já subiu (chamado pelos dois lados)."""
        with self.lock:
            if not (it.tr == "pronta" and it.up == "ok" and it.tr_file and it.tr_dest is not None):
                return
            if self.cancel_ev.is_set():
                return
            it.tr = "enviando"
        self._changed()

        def send():
            try:
                self.rc.copy(it.tr_file, it.tr_dest, Path(it.tr_file).name, proc_holder=self.procs)
                ok, err = True, ""
            except DriveError as e:
                ok, err = False, str(e)
            with self.lock:
                if ok:
                    it.tr = "ok"
                elif self.cancel_ev.is_set():
                    it.tr = "pronta"
                else:
                    it.tr, it.tr_err = "erro", "a transcrição ficou pronta, mas não subiu: " + err
            self._changed()
        t = threading.Thread(target=send, name="envio-transcricao", daemon=True)
        t.start()
        self.threads.append(t)

    # ---------------------------------------------------------------- cancelar / fechar
    def cancel(self) -> None:
        self.cancel_ev.set()
        for p in list(self.procs):
            try:
                if p.poll() is None:
                    p._subir_cancelled = True
                    p.terminate()
            except Exception:
                pass
        self._changed()

    def wait(self, timeout: float | None = None) -> None:
        end = None if timeout is None else time.time() + timeout
        for t in list(self.threads):
            t.join(None if end is None else max(0.0, end - time.time()))
        # o envio da última transcrição pode começar enquanto esperamos
        for t in list(self.threads):
            t.join(None if end is None else max(0.0, end - time.time()))

    def cleanup(self) -> None:
        if self.work and self.work.is_dir():
            shutil.rmtree(self.work, ignore_errors=True)
