"""Comandos do Subir no Drive.

    python -m subir                      abre o app (Mac)
    python -m subir transcrever <vídeo> [--saida <pasta>]
                                         só transcreve (grava <nome>.transcricao.json)
    python -m subir diagnostico          confere FFmpeg, whisper-cli e o modelo dentro do app
    python -m subir dev [--porta 8765]   tela de teste no navegador (desenvolvimento)
"""
from __future__ import annotations

import argparse
import platform
import subprocess
import sys
import time
from pathlib import Path


def cmd_transcrever(args) -> int:
    from . import fala
    t = time.time()

    def prog(frac, k, n):
        print(f"  trecho {k} de {n} ({frac * 100:.0f}%)", flush=True)
    data = fala.transcribe_video(args.video, progress=prog)
    out_dir = Path(args.saida) if args.saida else Path(args.video).parent
    p = fala.write(out_dir, Path(args.video).name, data)
    print(f"{p}  ·  {len(data['words'])} palavras  ·  {time.time() - t:.1f} s  ·  "
          f"{data['motor'].get('onde', '?')}")
    print("texto:", " ".join(w[2] for w in data["words"])[:600])
    return 0


def diagnostico() -> int:
    from . import __version__, fala
    print(f"Subir no Drive {__version__} · {platform.system()} {platform.machine()} · "
          f"Python {platform.python_version()}")
    ok = True
    for name, p in (("ffmpeg", fala.find_tool("ffmpeg")), ("ffprobe", fala.find_tool("ffprobe")),
                    ("whisper-cli", fala.find_cli())):
        if not p:
            print(f"{name:<12} FALTA")
            ok = False
            continue
        arg = "-h" if name == "whisper-cli" else "-version"
        r = subprocess.run([p, arg], capture_output=True, text=True, errors="replace")
        first = (r.stdout or r.stderr).strip().splitlines()[:1]
        print(f"{name:<12} ok   {first[0][:70] if first else ''}  ({p})")
    m = fala.find_model()
    print(f"{'modelo':<12} {'ok' if m else 'FALTA'}  ({m})")
    ok = ok and bool(m)
    try:
        import numpy
        print(f"{'numpy':<12} ok   {numpy.__version__}")
    except Exception as e:
        print(f"{'numpy':<12} ERRO {e}")
        ok = False
    print("TUDO OK" if ok else "FALTA ALGUMA COISA")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    argv = [a for a in argv if not a.startswith("-psn_")]        # o Finder antigo manda "-psn_…"
    if not argv:
        from . import mac
        return mac.run([])
    ap = argparse.ArgumentParser(prog="subir")
    sub = ap.add_subparsers(dest="cmd")
    t = sub.add_parser("transcrever")
    t.add_argument("video")
    t.add_argument("--saida")
    sub.add_parser("diagnostico")
    d = sub.add_parser("dev")
    d.add_argument("--porta", type=int, default=8765)
    s = sub.add_parser("janela-teste")
    s.add_argument("--foto", required=True)
    s.add_argument("arquivos", nargs="*")
    if argv[0] not in ("transcrever", "diagnostico", "dev", "janela-teste", "-h", "--help"):
        # arquivos passados ao abrir o app (arrastados para o ícone)
        from . import mac
        return mac.run(argv)
    a = ap.parse_args(argv)
    if a.cmd == "transcrever":
        return cmd_transcrever(a)
    if a.cmd == "diagnostico":
        return diagnostico()
    if a.cmd == "dev":
        from . import devserver
        devserver.serve(a.porta)
        return 0
    if a.cmd == "janela-teste":
        from . import mac
        return mac.run(a.arquivos, snapshot=a.foto)
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
