"""Configuração do app: onde está o rclone, qual conexão usar e a pasta inicial no Drive.

Mesmos arquivos e mesmo formato da versão 4 (o instalador .command), em
~/Library/Application Support/SubirNoDrive/ — o Revisor de Vídeos 1.2.0 lê estes dois arquivos
para achar o rclone no "Baixar do Drive", então NÃO mudar lugar nem formato:

  env.sh      export PATH="<pasta do rclone>:$PATH"
              export RCLONE_CONFIG="<arquivo>"          (só quando não é o padrão)
  config.txt  1ª linha: conexão do rclone (ex.: drive)
              2ª linha: pasta inicial no Drive (ex.: Gravações IEC; vazio = raiz)
              3ª linha: e-mail da conta (só para mostrar)

Nos Macs que já têm a versão 4, o app usa o que está lá. Nos outros, a tela "Primeira vez neste Mac"
grava os dois arquivos.
"""
from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path


def support_dir() -> Path:
    """Pasta dos dados do app (pode ser trocada nos testes por SUBIR_SUPPORT_DIR)."""
    if os.environ.get("SUBIR_SUPPORT_DIR"):
        return Path(os.environ["SUBIR_SUPPORT_DIR"])
    return Path.home() / "Library" / "Application Support" / "SubirNoDrive"


@dataclass
class Config:
    rclone: str | None = None          # caminho do programa rclone
    rclone_config: str | None = None   # RCLONE_CONFIG (None = o padrão do rclone)
    remote: str = ""                   # nome da conexão (ex.: drive)
    root: str = ""                     # pasta inicial no Drive (ex.: Gravações IEC)
    email: str = ""                    # e-mail da conta (só para mostrar)
    path_dirs: list[str] = field(default_factory=list)   # pastas do PATH do env.sh

    @property
    def complete(self) -> bool:
        return bool(self.rclone and Path(self.rclone).is_file() and self.remote)


def _rclone_in(d: str) -> str | None:
    p = Path(d).expanduser() / "rclone"
    return str(p) if p.is_file() else None


def candidates() -> list[str]:
    """Lugares comuns do rclone nos Macs (o do setor fica em ~/Applications/rclone, fora do PATH)."""
    home = Path.home()
    out = []
    for p in (home / "Applications" / "rclone" / "rclone", Path("/Applications/rclone/rclone"),
              Path("/opt/homebrew/bin/rclone"), Path("/usr/local/bin/rclone"), home / "bin" / "rclone",
              home / "rclone" / "rclone"):
        if p.is_file() and str(p) not in out:
            out.append(str(p))
    w = shutil.which("rclone")
    if w and w not in out:
        out.append(w)
    return out


def load() -> Config:
    cfg = Config()
    sup = support_dir()
    try:
        for line in (sup / "env.sh").read_text(encoding="utf-8").splitlines():
            m = re.match(r'\s*export\s+RCLONE_CONFIG="([^"]*)"', line)
            if m and m.group(1):
                cfg.rclone_config = m.group(1)
            m = re.match(r'\s*export\s+PATH="([^"]*)"', line)
            if m:
                cfg.path_dirs = [d for d in m.group(1).split(":") if d and "$" not in d]
    except OSError:
        pass
    for d in cfg.path_dirs:
        p = _rclone_in(d)
        if p:
            cfg.rclone = p
            break
    try:
        lines = (sup / "config.txt").read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    if lines:
        cfg.remote = lines[0].strip()
    if len(lines) > 1:
        cfg.root = lines[1].strip().strip("/")
    if len(lines) > 2:
        cfg.email = lines[2].strip()
    return cfg


def save(rclone: str, remote: str, root: str, email: str = "", rclone_config: str | None = None) -> Config:
    """Grava env.sh e config.txt no formato da versão 4."""
    sup = support_dir()
    sup.mkdir(parents=True, exist_ok=True)
    rdir = str(Path(rclone).expanduser().resolve().parent)
    env = ["# Subir no Drive: onde está o rclone (lido também pelo Revisor de Vídeos)",
           f'export PATH="{rdir}:$PATH"']
    if rclone_config:
        env.append(f'export RCLONE_CONFIG="{rclone_config}"')
    _write(sup / "env.sh", "\n".join(env) + "\n")
    _write(sup / "config.txt", f"{remote.strip()}\n{root.strip().strip('/')}\n{email.strip()}\n")
    return load()


def _write(p: Path, text: str) -> None:
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(p)


def log_path() -> Path:
    return support_dir() / "subir.log"
