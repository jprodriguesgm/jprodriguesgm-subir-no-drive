"""Conversa com o rclone: listar pastas, criar pasta, achar uma pasta pelo link e enviar com progresso.

Quem fala com o Google é o rclone, com o acesso guardado na configuração dele (a conta da instituição).
Por isso não importa qual conta Google está aberta no navegador.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path


class DriveError(Exception):
    def __init__(self, msg: str, kind: str = "erro"):
        super().__init__(msg)
        self.kind = kind          # "escopo" (só leitura), "token", "internet", "cheio", "nao_achei", "erro"


# ------------------------------------------------------------------ nomes

def plain(s: str) -> str:
    """Sem acento, minúsculo, sem espaço nas pontas (para comparar nomes de pasta)."""
    n = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in n if not unicodedata.combining(c)).lower().strip()


def is_saida(name: str) -> bool:
    return plain(name) in ("saida", "saidas")


def is_transcricoes(name: str) -> bool:
    return plain(name) in ("transcricoes", "transcricao")


TRANSCRICOES = "Transcrições"


def folder_id_from_link(link: str) -> str | None:
    """Id da pasta num link do Drive (".../folders/<id>", "?id=<id>") ou o próprio id colado."""
    t = (link or "").strip()
    m = re.search(r"/folders/([\w-]{10,})", t) or re.search(r"[?&]id=([\w-]{10,})", t)
    if m:
        return m.group(1)
    if re.fullmatch(r"[\w-]{20,}", t):
        return t
    return None


# ------------------------------------------------------------------ onde no Drive

@dataclass
class Loc:
    """Uma pasta no Drive: a partir da pasta inicial (fid=None) ou de uma pasta pelo id (link colado
    que não foi achado dentro da pasta inicial). `parts` = nomes das pastas a partir dessa base."""
    parts: list[str] = field(default_factory=list)
    fid: str | None = None
    base_name: str = ""        # nome da pasta do link (só quando fid)

    def child(self, name: str) -> "Loc":
        return Loc(self.parts + [name], self.fid, self.base_name)

    def parent(self) -> "Loc | None":
        if not self.parts:
            return None
        return Loc(self.parts[:-1], self.fid, self.base_name)

    @property
    def name(self) -> str:
        return self.parts[-1] if self.parts else self.base_name

    def to_dict(self) -> dict:
        return {"parts": list(self.parts), "fid": self.fid, "base_name": self.base_name}

    @staticmethod
    def from_dict(d: dict | None) -> "Loc":
        d = d or {}
        parts = [str(p) for p in (d.get("parts") or []) if str(p)]
        return Loc(parts, d.get("fid") or None, d.get("base_name") or "")


# ------------------------------------------------------------------ rclone

_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class Rclone:
    def __init__(self, path: str, remote: str, config: str | None = None, root: str = ""):
        if not path or not Path(path).is_file():
            raise DriveError("O rclone não foi encontrado neste Mac.", "sem_rclone")
        if not re.fullmatch(r"[\w.\- ]{1,60}", remote or ""):
            raise DriveError("Nome de conexão do rclone inválido.")
        self.path, self.remote, self.config = path, remote, config
        self.root_parts = [p for p in (root or "").strip("/").split("/") if p]
        self._tree: dict | None = None
        self._tree_at = 0.0
        self._tree_lock = threading.Lock()

    # -------- básico
    def env(self) -> dict:
        e = dict(os.environ)
        if self.config:
            e["RCLONE_CONFIG"] = self.config
        return e

    def run(self, args: list[str], timeout: float = 120) -> str:
        try:
            r = subprocess.run([self.path, *args], capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=timeout, env=self.env(), creationflags=_NO_WINDOW)
        except subprocess.TimeoutExpired:
            raise DriveError("O Drive demorou demais para responder. Confira a internet e tente de novo.", "internet")
        except OSError as e:
            raise DriveError(f"Não deu para rodar o rclone ({e}).", "sem_rclone")
        if r.returncode != 0:
            raise friendly(r.stderr)
        return r.stdout

    def spec(self, loc: Loc) -> str:
        """Endereço que o rclone entende."""
        if loc.fid:
            return f"{self.remote},root_folder_id={loc.fid}:" + "/".join(loc.parts)
        return f"{self.remote}:" + "/".join(self.root_parts + loc.parts)

    # -------- conexão
    def remotes(self) -> list[str]:
        out = self.run(["listremotes", "--long"], timeout=30)
        names = []
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "drive" and parts[0].endswith(":"):
                names.append(parts[0][:-1])
        return names

    def email(self) -> str | None:
        try:
            out = self.run(["config", "userinfo", f"{self.remote}:"], timeout=40)
        except DriveError:
            return None
        m = re.search(r"email:\s*(\S+)", out, re.I)
        return m.group(1) if m else None

    def scope(self) -> str:
        """Escopo da conexão. Vazio = o padrão do rclone ("drive", acesso total)."""
        out = self.run(["config", "show", self.remote], timeout=30)
        m = re.search(r"^\s*scope\s*=\s*(\S+)", out, re.M)
        return m.group(1) if m else ""

    def can_upload(self) -> bool:
        s = self.scope()
        return s in ("", "drive", "drive.file") or "drive," in s and "readonly" not in s

    # -------- pastas
    def lsjson(self, where: str, *flags: str, timeout: float = 120) -> list[dict]:
        out = self.run(["lsjson", where, *flags], timeout=timeout)
        try:
            data = json.loads(out or "[]")
        except json.JSONDecodeError:
            raise DriveError("Resposta estranha do Drive (lista de pastas).")
        return data if isinstance(data, list) else []

    def list_dirs(self, loc: Loc) -> list[str]:
        items = self.lsjson(self.spec(loc), "--dirs-only", "--no-modtime", "--no-mimetype", timeout=90)
        names = [str(i.get("Name", "")) for i in items if i.get("IsDir")]
        return sorted((n for n in names if n), key=lambda n: plain(n))

    def mkdir(self, loc: Loc) -> None:
        self.run(["mkdir", self.spec(loc)], timeout=60)

    def folder_id(self, loc: Loc) -> str | None:
        """Id da pasta (para o link "Abrir no Drive")."""
        if loc.fid and not loc.parts:
            return loc.fid
        try:
            items = self.lsjson(self.spec(loc), "--stat", "--no-modtime", "--no-mimetype", timeout=60)
        except DriveError:
            return None
        if items and isinstance(items, list):
            return items[0].get("ID") or None
        return None

    def find_by_id(self, fid: str, depth: int = 4) -> list[str] | None:
        """Onde fica, dentro da pasta inicial, a pasta do link colado (lista as pastas até 4 níveis;
        o resultado fica guardado 10 min). None = não está dentro da pasta inicial."""
        with self._tree_lock:
            if self._tree is None or time.time() - self._tree_at > 600:
                items = self.lsjson(self.spec(Loc()), "-R", "--dirs-only", "--no-modtime", "--no-mimetype",
                                    f"--max-depth={depth}", timeout=240)
                self._tree = {str(i.get("ID")): str(i.get("Path", "")) for i in items if i.get("ID")}
                self._tree_at = time.time()
            path = self._tree.get(fid)
        if path is None:
            if self.root_parts:
                try:
                    root_id = self.folder_id(Loc())
                except DriveError:
                    root_id = None
                if root_id == fid:
                    return []
            return None
        return [p for p in path.split("/") if p]

    def base_name(self, fid: str) -> str:
        """Nome da pasta do link (para o caminho no topo), quando ela não está na pasta inicial."""
        try:
            items = self.lsjson(f"{self.remote},root_folder_id={fid}:", "--stat", "--no-modtime",
                                "--no-mimetype", timeout=60)
            if items and items[0].get("Name"):
                return str(items[0]["Name"])
        except DriveError:
            pass
        return "Pasta do link"

    # -------- envio
    def copy(self, src: str, dst: Loc, name: str | None = None, progress=None,
             proc_holder: list | None = None) -> None:
        """Envia um arquivo (para dst/<nome>) ou uma pasta (para dst/<nome da pasta>).
        `progress(bytes, total, speed, eta)` a cada segundo. `proc_holder` recebe o processo (para cancelar)."""
        p = Path(src)
        name = name or p.name
        target = self.spec(dst.child(name))
        cmd = [self.path, "copyto" if p.is_file() else "copy", str(p), target,
               "--stats", "1s", "--stats-log-level", "NOTICE", "--use-json-log",
               "--drive-chunk-size", "32M", "--retries", "3", "--low-level-retries", "10"]
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=self.env(),
                                    text=True, encoding="utf-8", errors="replace", creationflags=_NO_WINDOW)
        except OSError as e:
            raise DriveError(f"Não deu para rodar o rclone ({e}).", "sem_rclone")
        if proc_holder is not None:
            proc_holder.append(proc)
        errors: list[str] = []
        for line in proc.stderr:
            st = parse_stats_line(line)
            if st is not None:
                if progress:
                    progress(*st)
                continue
            msg = _log_msg(line)
            if msg:
                errors.append(msg)
        rc = proc.wait()
        if rc == 0:
            return
        if rc < 0 or getattr(proc, "_subir_cancelled", False):
            raise DriveError("Envio cancelado.", "cancelado")
        raise friendly("\n".join(errors[-30:]))


# ------------------------------------------------------------------ leitura do progresso

_UNITS = {"": 1, "B": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3, "T": 1024 ** 4}
_TXT = re.compile(r"([\d.]+)\s*([KMGT]?)i?B\s*/\s*([\d.]+)\s*([KMGT]?)i?B,\s*(\d+)%"
                  r"(?:,\s*([\d.]+)\s*([KMGT]?)i?B/s)?(?:,\s*ETA\s*([\w.]+|-))?")


def _num(v: str, u: str) -> float:
    return float(v) * _UNITS.get(u.upper(), 1)


def _eta(s: str | None) -> float | None:
    if not s or s == "-":
        return None
    tot = 0.0
    for v, u in re.findall(r"([\d.]+)([wdhms])", s):
        tot += float(v) * {"w": 604800, "d": 86400, "h": 3600, "m": 60, "s": 1}[u]
    return tot


def parse_stats_line(line: str):
    """(bytes, total, velocidade B/s, faltam s) de uma linha de estatística do rclone, ou None."""
    line = line.strip()
    if not line:
        return None
    if line.startswith("{"):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            obj = None
        if isinstance(obj, dict):
            st = obj.get("stats")
            if isinstance(st, dict) and "bytes" in st:
                eta = st.get("eta")
                return (float(st.get("bytes") or 0), float(st.get("totalBytes") or 0),
                        float(st.get("speed") or 0), float(eta) if isinstance(eta, (int, float)) else None)
            line = str(obj.get("msg", ""))
    m = _TXT.search(line)
    if m and "Transferred" in line or (m and line.lstrip().startswith(tuple("0123456789"))):
        return (_num(m.group(1), m.group(2)), _num(m.group(3), m.group(4)),
                _num(m.group(6), m.group(7)) if m.group(6) else 0.0, _eta(m.group(8)))
    return None


def _log_msg(line: str) -> str:
    line = line.strip()
    if not line:
        return ""
    if line.startswith("{"):
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                return f"{obj.get('level', '')}: {obj.get('msg', '')}".strip()
        except json.JSONDecodeError:
            pass
    return line


# ------------------------------------------------------------------ mensagens em português

def friendly(stderr: str) -> DriveError:
    s = stderr or ""
    low = s.lower()
    if "access_token_scope_insufficient" in low or ("insufficient" in low and ("scope" in low or "permission" in low)):
        return DriveError("A conexão do rclone só tem permissão para LER o Drive, não para enviar. "
                          "Use “Corrigir permissão” (Configurar) e escolha a conta da instituição no navegador.",
                          "escopo")
    if "didn't find section in config file" in low or "not found in config" in low:
        return DriveError("A conexão escolhida não existe no rclone deste Mac. Abra “Configurar”.", "config")
    if "invalid_grant" in low or ("token" in low and "expired" in low) or ("oauth2" in low and "refresh" in low):
        return DriveError("A conexão do rclone com o Google expirou. Use “Reconectar” (Configurar) e escolha a "
                          "conta da instituição no navegador.", "token")
    if "storagequotaexceeded" in low or "quota" in low and "exceeded" in low:
        return DriveError("O Drive da conta está cheio (sem espaço).", "cheio")
    if "no such host" in low or "dial tcp" in low or "network is unreachable" in low or "timeout" in low \
            or "connection reset" in low or "i/o timeout" in low:
        return DriveError("A internet caiu ou o Google não respondeu.", "internet")
    if ("no such file or directory" in low or "file not found" in low) and ("stat" in low or "local" in low):
        return DriveError("O arquivo não foi encontrado no Mac (o disco foi desconectado?).", "arquivo")
    if "notfound" in low or "directory not found" in low or "404" in low:
        return DriveError("Pasta não encontrada no Drive (o link está certo? a conta da instituição tem acesso?).",
                          "nao_achei")
    last = [ln for ln in s.strip().splitlines() if ln.strip()]
    return DriveError("Erro do rclone: " + (last[-1][-240:] if last else "sem detalhe"))
