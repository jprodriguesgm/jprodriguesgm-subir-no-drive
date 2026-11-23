"""Ponto de entrada do app empacotado (PyInstaller).

Dois cliques (ou arrastar vídeos para o ícone): abre a janela.
Pelo Terminal também aceita os comandos de teste, ex.:
  "Subir no Drive.app/Contents/MacOS/Subir no Drive" diagnostico
  "Subir no Drive.app/Contents/MacOS/Subir no Drive" transcrever "01 Aula.mp4"
"""
from __future__ import annotations

import os
import sys
import time


def _log_to_file():
    """Sem janela de terminal: o que o app escreveria vai para subir.log (pasta de dados do app)."""
    from subir import config
    try:
        home = config.support_dir()
        home.mkdir(parents=True, exist_ok=True)
        log = home / "subir.log"
        if log.is_file() and log.stat().st_size > 2_000_000:
            log.replace(home / "subir.log.1")
        fh = open(log, "a", encoding="utf-8", buffering=1, errors="replace")
        fh.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} abrindo (pid {os.getpid()})\n")
        sys.stdout = fh
        sys.stderr = fh
    except OSError:
        pass


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-psn_")]
    if getattr(sys, "frozen", False) and (not args or args[0] not in ("diagnostico", "transcrever", "janela-teste")):
        _log_to_file()
    from subir.__main__ import main as run
    return run(args) or 0


if __name__ == "__main__":
    sys.exit(main())
