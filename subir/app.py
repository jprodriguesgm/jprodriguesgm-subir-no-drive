"""O "cérebro" do app: recebe os pedidos da tela (HTML) e responde.

A tela fala com o Python por mensagens {"cmd": ...}. O Python responde chamando app.recv({...}) na tela.
Quem leva as mensagens é a "ponte": no Mac, a janela WebKit (mac.py); nos testes, um servidorzinho local
(devserver.py). Assim a mesma lógica roda nos dois.
"""
from __future__ import annotations

import subprocess
import tempfile
import threading
import time
import traceback
from pathlib import Path

from . import __version__, config, fala
from .job import Job, make_items, transcription_dest
from .rclone import DriveError, Loc, Rclone, folder_id_from_link


class Bridge:
    """O que a ponte oferece ao app (o Mac implementa; os testes também)."""
    def send(self, msg: dict) -> None: ...
    def pick_files(self) -> list[str]: return []
    def pick_rclone(self) -> str | None: return None
    def open_url(self, url: str) -> None:
        subprocess.Popen(["open", url])
    def open_file(self, path: str) -> None:
        subprocess.Popen(["open", path])
    def quit(self) -> None: ...
    def minimize(self) -> None: ...
    def busy_changed(self, busy: bool) -> None: ...


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


class App:
    def __init__(self, bridge: Bridge):
        self.bridge = bridge
        self.cfg = config.load()
        self.rc: Rclone | None = None
        self.files: list[str] = []
        self.job: Job | None = None
        self.job_dest: Loc | None = None
        self.job_tr_dest: Loc | None = None
        self._last_push = 0.0
        self._push_timer: threading.Timer | None = None
        self._lock = threading.Lock()
        self._make_rc()

    # ---------------------------------------------------------------- base
    def _make_rc(self) -> None:
        self.rc = None
        if self.cfg.complete:
            try:
                self.rc = Rclone(self.cfg.rclone, self.cfg.remote, self.cfg.rclone_config, self.cfg.root)
            except DriveError:
                self.rc = None

    def send(self, msg: dict) -> None:
        self.bridge.send(msg)

    def init_view(self) -> dict:
        return {"type": "init", "version": __version__,
                "configured": self.rc is not None,
                "email": self.cfg.email, "remote": self.cfg.remote,
                "root": self.cfg.root, "root_name": self.cfg.root.split("/")[-1] if self.cfg.root else "Meu Drive",
                "engine": fala.available(),
                "files": self.files_view(),
                "job": self.job_view()}

    def files_view(self) -> list[dict]:
        out = []
        for p in self.files:
            pp = Path(p)
            try:
                size = pp.stat().st_size if pp.is_file() else None
            except OSError:
                size = None
            out.append({"path": p, "name": pp.name, "is_dir": pp.is_dir(), "size": size,
                        "video": pp.is_file() and fala.is_video(pp)})
        return out

    def job_view(self) -> dict | None:
        if not self.job:
            return None
        v = self.job.view()
        v["dest"] = self.job_dest.to_dict() if self.job_dest else None
        v["tr_dest"] = self.job_tr_dest.to_dict() if self.job_tr_dest else None
        return v

    # ---------------------------------------------------------------- mensagens da tela
    def handle(self, msg: dict) -> None:
        cmd = str(msg.get("cmd", ""))
        fn = getattr(self, "cmd_" + cmd, None)
        if fn is None:
            log(f"comando desconhecido: {cmd}")
            return
        rid = msg.get("rid")

        def run():
            try:
                res = fn(msg)
                if rid is not None:
                    self.send({"type": "reply", "rid": rid, "ok": True, "data": res})
            except DriveError as e:
                log(f"{cmd}: {e}")
                if rid is not None:
                    self.send({"type": "reply", "rid": rid, "ok": False, "error": str(e), "kind": e.kind})
            except Exception as e:
                log(f"{cmd}: {traceback.format_exc()}")
                if rid is not None:
                    self.send({"type": "reply", "rid": rid, "ok": False, "error": f"Erro inesperado: {e}",
                               "kind": "erro"})
        # comandos que abrem janela do sistema precisam rodar na linha principal (a ponte cuida disso)
        if cmd in ("pick_files", "pick_rclone", "setup_pick_rclone", "quit", "minimize"):
            run()
        else:
            threading.Thread(target=run, name=cmd, daemon=True).start()

    def cmd_ready(self, msg):
        return self.init_view()

    # -------- arquivos
    def add_files(self, paths: list[str]) -> None:
        if self.job and self.job.busy:
            self.send({"type": "toast", "text": "Aguarde o envio atual terminar antes de adicionar outros arquivos."})
            return
        if self.job and not self.job.busy:
            self.job = None            # envio anterior terminou: começa outro
        for p in paths:
            p = str(p)
            if Path(p).name.startswith(".") or p in self.files or not Path(p).exists():
                continue
            self.files.append(p)
        self.send({"type": "files", "files": self.files_view(), "job": self.job_view()})

    def cmd_pick_files(self, msg):
        paths = self.bridge.pick_files()
        if paths:
            self.add_files(paths)
        return {"files": self.files_view()}

    def cmd_add_files(self, msg):
        self.add_files([str(p) for p in msg.get("paths") or []])
        return {"files": self.files_view()}

    def cmd_remove_file(self, msg):
        p = msg.get("path")
        self.files = [f for f in self.files if f != p]
        return {"files": self.files_view()}

    # -------- pastas do Drive
    def _need_rc(self) -> Rclone:
        if self.rc is None:
            raise DriveError("Falta configurar o rclone neste Mac.", "config")
        return self.rc

    def cmd_list(self, msg):
        rc = self._need_rc()
        loc = Loc.from_dict(msg.get("loc"))
        return {"loc": loc.to_dict(), "dirs": rc.list_dirs(loc)}

    def cmd_mkdir(self, msg):
        rc = self._need_rc()
        name = str(msg.get("name", "")).strip().replace("/", "-")
        if not name:
            raise DriveError("Digite o nome da pasta.")
        loc = Loc.from_dict(msg.get("loc"))
        rc.mkdir(loc.child(name))
        return {"loc": loc.to_dict(), "dirs": rc.list_dirs(loc), "created": name}

    def cmd_link(self, msg):
        rc = self._need_rc()
        fid = folder_id_from_link(str(msg.get("text", "")))
        if not fid:
            raise DriveError("Isso não é um link de pasta do Drive.", "link")
        parts = rc.find_by_id(fid)
        if parts is not None:
            loc = Loc(parts)
        else:
            loc = Loc([], fid, rc.base_name(fid))
        return {"loc": loc.to_dict(), "dirs": rc.list_dirs(loc), "inside_root": parts is not None}

    def cmd_open_drive(self, msg):
        rc = self._need_rc()
        loc = Loc.from_dict(msg.get("loc"))
        fid = rc.folder_id(loc)
        if not fid:
            raise DriveError("Não achei o endereço desta pasta no Drive.")
        self.bridge.open_url(f"https://drive.google.com/drive/folders/{fid}")
        return {"ok": True}

    # -------- envio
    def cmd_upload(self, msg):
        rc = self._need_rc()
        if self.job and self.job.busy:
            raise DriveError("Já existe um envio em andamento.")
        if not self.files:
            raise DriveError("Escolha os vídeos primeiro.")
        dest = Loc.from_dict(msg.get("loc"))
        transcribe = bool(msg.get("transcribe", True)) and fala.available()
        items = make_items(self.files, transcribe)
        tr_dest, why = (None, "")
        if transcribe and any(it.tr == "fila" for it in items):
            tr_dest, why = transcription_dest(rc, dest)
        self.job_dest, self.job_tr_dest = dest, tr_dest
        self.job = Job(rc, items, dest, tr_dest, on_change=self._job_changed)
        log(f"envio: {len(items)} item(ns) para {rc.spec(dest)}; transcrição: "
            f"{rc.spec(tr_dest) if tr_dest else 'não (' + (why or 'desligada') + ')'}")
        self.job.start()
        self.bridge.busy_changed(True)
        return {"job": self.job_view(), "tr_note": why}

    def _job_changed(self) -> None:
        # no máximo ~4 atualizações por segundo para a tela; a última sempre chega
        with self._lock:
            now = time.time()
            wait = 0.25 - (now - self._last_push)
            if wait > 0:
                if self._push_timer is None:
                    self._push_timer = threading.Timer(wait, self._push_job)
                    self._push_timer.daemon = True
                    self._push_timer.start()
                return
            self._last_push = now
        self._push_job()

    def _push_job(self) -> None:
        with self._lock:
            self._push_timer = None
            self._last_push = time.time()
        job = self.job
        if not job:
            return
        v = self.job_view()
        self.send({"type": "job", "job": v})
        if not job.busy:
            self.bridge.busy_changed(False)

    def cmd_cancel(self, msg):
        if self.job:
            self.job.cancel()
            threading.Thread(target=self._after_cancel, daemon=True).start()
        return {"ok": True}

    def _after_cancel(self):
        job = self.job
        if job:
            job.wait(30)
            self._push_job()

    def cmd_retry(self, msg):
        if self.job and not self.job.busy:
            self.job.retry()
            self.bridge.busy_changed(True)
        return {"job": self.job_view()}

    def cmd_new(self, msg):
        """Novo envio (tela final → "Subir outros")."""
        if self.job and self.job.busy:
            raise DriveError("Ainda há um envio em andamento.")
        if self.job:
            self.job.cleanup()
        self.job = None
        self.files = []
        return {"files": self.files_view()}

    # -------- janela
    def cmd_quit(self, msg):
        if self.job and self.job.busy:
            self.job.cancel()
            self.job.wait(5)
        if self.job:
            self.job.cleanup()
        self.bridge.quit()

    def cmd_minimize(self, msg):
        self.bridge.minimize()

    def busy(self) -> bool:
        return bool(self.job and self.job.busy)

    # -------- primeira vez neste Mac
    def cmd_setup_info(self, msg):
        """Sugestões para a tela de configuração."""
        rclones = config.candidates()
        cur = self.cfg.rclone if self.cfg.rclone and Path(self.cfg.rclone).is_file() else None
        if cur and cur not in rclones:
            rclones.insert(0, cur)
        chosen = msg.get("rclone") or cur or (rclones[0] if rclones else "")
        return self._check(chosen, msg.get("remote") or self.cfg.remote, msg.get("root", self.cfg.root),
                           rclones=rclones)

    def cmd_setup_check(self, msg):
        return self._check(str(msg.get("rclone") or ""), str(msg.get("remote") or ""), str(msg.get("root") or ""))

    def _check(self, rclone: str, remote: str, root: str, rclones: list[str] | None = None) -> dict:
        out = {"rclone": rclone, "rclones": rclones or [], "remote": remote, "root": root.strip().strip("/"),
               "remotes": [], "rclone_ok": False, "remote_ok": False, "can_upload": None, "email": "",
               "root_ok": None, "problem": "", "action": ""}
        if not rclone or not Path(rclone).expanduser().is_file():
            out["problem"] = "Não achei o programa rclone. Clique em “Escolher…” e aponte o arquivo rclone."
            return out
        rclone = str(Path(rclone).expanduser())
        out["rclone"] = rclone
        try:
            tmp = Rclone(rclone, remote if remote else "drive", self.cfg.rclone_config)
            out["remotes"] = tmp.remotes()
            out["rclone_ok"] = True
        except DriveError as e:
            out["problem"] = str(e)
            return out
        if not out["remotes"]:
            out["problem"] = "O rclone deste Mac ainda não tem nenhuma conexão com o Google Drive."
            out["action"] = "create"
            return out
        if remote not in out["remotes"]:
            remote = "drive" if "drive" in out["remotes"] else out["remotes"][0]
            out["remote"] = remote
        rc = Rclone(rclone, remote, self.cfg.rclone_config, out["root"])
        out["remote_ok"] = True
        try:
            out["can_upload"] = rc.can_upload()
        except DriveError:
            out["can_upload"] = None
        out["email"] = rc.email() or ""
        if out["can_upload"] is False:
            out["problem"] = "Esta conexão só tem permissão para LER o Drive. Use “Corrigir permissão”."
            out["action"] = "fix_scope"
            return out
        try:
            rc.list_dirs(Loc())
            out["root_ok"] = True
        except DriveError as e:
            out["root_ok"] = False
            out["problem"] = str(e) if e.kind != "nao_achei" else "Não achei essa pasta inicial no Drive."
            if e.kind == "token":
                out["action"] = "reconnect"
        return out

    def cmd_setup_pick_rclone(self, msg):
        p = self.bridge.pick_rclone()
        return {"rclone": p}

    def cmd_pick_rclone(self, msg):
        return self.cmd_setup_pick_rclone(msg)

    def cmd_setup_save(self, msg):
        chk = self._check(str(msg.get("rclone") or ""), str(msg.get("remote") or ""), str(msg.get("root") or ""))
        if not (chk["rclone_ok"] and chk["remote_ok"] and chk["can_upload"] is not False and chk["root_ok"]):
            return {"saved": False, "check": chk}
        self.cfg = config.save(chk["rclone"], chk["remote"], chk["root"], chk["email"], self.cfg.rclone_config)
        self._make_rc()
        return {"saved": True, "init": self.init_view()}

    def cmd_open_terminal(self, msg):
        """Abre o Terminal com os comandos do rclone (corrigir permissão, reconectar ou criar a conexão).
        Usa um arquivo .command (o Mac abre no Terminal sem pedir permissão de controlar outro app)."""
        what = msg.get("what")
        rclone = str(msg.get("rclone") or self.cfg.rclone or "")
        remote = str(msg.get("remote") or self.cfg.remote or "drive")
        if not rclone or not Path(rclone).is_file():
            raise DriveError("Escolha primeiro onde está o rclone.")
        q = lambda s: "'" + s.replace("'", "'\\''") + "'"
        env = f"export RCLONE_CONFIG={q(self.cfg.rclone_config)}\n" if self.cfg.rclone_config else ""
        intro = {
            "fix_scope": "Corrigindo a permissão da conexão para poder ENVIAR ao Drive.",
            "reconnect": "Reconectando o rclone ao Google.",
            "create": "Criando a conexão do rclone com o Google Drive.",
        }.get(what)
        if not intro:
            raise DriveError("Pedido desconhecido.")
        tips = ("echo 'Em cada pergunta, só aperte Enter (resposta padrão).'\n"
                "echo 'Em \"Use web browser\", responda y. No navegador, escolha a conta da INSTITUIÇÃO e clique em Permitir.'\n"
                "echo 'Se a pasta das gravações estiver em \"Drives compartilhados\", responda y na pergunta do Shared Drive; senão, n.'\n")
        if what == "fix_scope":
            body = (f"{q(rclone)} config update {q(remote)} scope drive --non-interactive >/dev/null\n"
                    f"{q(rclone)} config reconnect {q(remote)}:\n")
        elif what == "reconnect":
            body = f"{q(rclone)} config reconnect {q(remote)}:\n"
        else:
            tips = ("echo 'Digite n (nova conexão) → nome: drive → tipo: drive (Google Drive).'\n"
                    "echo 'client_id e client_secret: Enter. scope: 1 (acesso total). Depois Enter em tudo.'\n"
                    "echo 'Em \"Use web browser\", responda y e escolha a conta da INSTITUIÇÃO.'\n")
            body = f"{q(rclone)} config\n"
        script = ("#!/bin/bash\nclear\n" + env + f"echo {q(intro)}\necho\n" + tips + "echo\n" + body +
                  "echo\necho 'Pronto. Pode fechar esta janela e voltar ao Subir no Drive (clique em Conferir).'\n")
        d = Path(tempfile.mkdtemp(prefix="subir_terminal_"))
        f = d / "Subir no Drive - rclone.command"
        f.write_text(script, encoding="utf-8")
        f.chmod(0o755)
        self.bridge.open_file(str(f))
        return {"ok": True}

    def cmd_log(self, msg):
        log("tela: " + str(msg.get("text", ""))[:500])
