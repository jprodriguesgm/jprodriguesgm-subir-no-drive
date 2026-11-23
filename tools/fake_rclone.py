#!/usr/bin/env python3
"""rclone de mentira, só para os testes: o "Drive" é uma pasta do computador (FAKE_DRIVE).

Entende o que o Subir no Drive usa: listremotes --long, config show/userinfo/update, lsjson
(--dirs-only, --stat, -R, --max-depth), mkdir, copyto/copy (com estatísticas em JSON, como o rclone
com --use-json-log). O id de cada pasta é derivado do caminho (para testar o link colado).

Variáveis: FAKE_DRIVE (pasta), FAKE_SPEED (bytes/s, padrão 50 MB/s), FAKE_FAIL (parte do nome de
arquivo que falha com "i/o timeout"), FAKE_SCOPE (escopo da conexão), FAKE_TEXT_STATS=1 (estatística
em texto, como rclone antigo).
"""
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("FAKE_DRIVE", "/tmp/fake_drive"))


def fid(rel: str) -> str:
    return "F" + hashlib.sha1(rel.encode()).hexdigest()[:24]


def resolve(spec: str) -> Path:
    remote, _, path = spec.partition(":")
    base = ROOT
    if ",root_folder_id=" in remote:
        want = remote.split(",root_folder_id=")[1]
        base = None
        for d in [ROOT] + [p for p in ROOT.rglob("*") if p.is_dir()]:
            if fid(str(d.relative_to(ROOT))) == want:
                base = d
                break
        if base is None:
            die("directory not found", 3)
    return base / path if path else base


def die(msg: str, code: int = 1):
    sys.stderr.write(f"ERROR : {msg}\n")
    sys.exit(code)


def entry(p: Path, rel: str) -> dict:
    return {"Path": rel, "Name": p.name, "Size": -1 if p.is_dir() else p.stat().st_size,
            "IsDir": p.is_dir(), "ID": fid(str(p.relative_to(ROOT)))}


def main(a: list[str]):
    if not a:
        die("sem comando")
    cmd = a[0]
    if cmd == "listremotes":
        print("drive:  drive\nfotos:  googlephotos")
        return
    if cmd == "config":
        sub = a[1]
        if sub == "show":
            sc = os.environ.get("FAKE_SCOPE", "drive")
            print(f"[{a[2]}]\ntype = drive\nscope = {sc}\ntoken = xxx")
        elif sub == "userinfo":
            print("Email:    conta@exemplo.edu\n")
        return
    if cmd == "lsjson":
        p = resolve(a[1])
        if not p.exists():
            die(f"error listing: directory not found: {a[1]}", 3)
        if "--stat" in a:
            print(json.dumps([entry(p, "")]))
            return
        dirs_only = "--dirs-only" in a
        depth = 1
        if "-R" in a:
            depth = 99
            for x in a:
                if x.startswith("--max-depth="):
                    depth = int(x.split("=")[1])
        out = []

        def walk(d: Path, rel: str, lvl: int):
            for c in sorted(d.iterdir()):
                if dirs_only and not c.is_dir():
                    continue
                r = f"{rel}/{c.name}" if rel else c.name
                out.append(entry(c, r))
                if c.is_dir() and lvl < depth:
                    walk(c, r, lvl + 1)
        walk(p, "", 1)
        time.sleep(float(os.environ.get("FAKE_LIST_DELAY", "0.05")))
        print(json.dumps(out))
        return
    if cmd == "mkdir":
        resolve(a[1]).mkdir(parents=True, exist_ok=True)
        return
    if cmd in ("copyto", "copy"):
        src, dst = Path(a[1]), resolve(a[2])
        if os.environ.get("FAKE_SCOPE") == "drive.readonly":
            die('Failed to copy: googleapi: Error 403: Request had insufficient authentication scopes., '
                'insufficientPermissions ACCESS_TOKEN_SCOPE_INSUFFICIENT')
        files = [src] if src.is_file() else [f for f in src.rglob("*") if f.is_file()]
        total = sum(f.stat().st_size for f in files)
        speed = float(os.environ.get("FAKE_SPEED", 50e6))
        fail = os.environ.get("FAKE_FAIL")
        done = 0
        t0 = time.time()
        text = os.environ.get("FAKE_TEXT_STATS") == "1"
        for f in files:
            target = dst if src.is_file() else dst / f.relative_to(src)
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".partial")
            with open(f, "rb") as r, open(tmp, "wb") as w:
                while True:
                    buf = r.read(1 << 20)
                    if not buf:
                        break
                    w.write(buf)
                    done += len(buf)
                    time.sleep(len(buf) / speed)
                    el = max(time.time() - t0, 1e-3)
                    sp = done / el
                    eta = (total - done) / sp if sp else None
                    if fail and fail in f.name and done > total / 2:
                        tmp.unlink()
                        die('Failed to copy: Post "https://www.googleapis.com/upload/drive/v3/files": dial tcp: i/o timeout')
                    if text:
                        sys.stderr.write(f"2026/11/23 15:00:00 NOTICE: {done/1048576:.3f} MiB / {total/1048576:.3f} MiB, "
                                         f"{int(done*100/max(total,1))}%, {sp/1048576:.3f} MiB/s, ETA {int(eta or 0)}s\n")
                    else:
                        sys.stderr.write(json.dumps({"level": "notice", "msg": "stats", "stats": {
                            "bytes": done, "totalBytes": total, "speed": sp, "eta": eta}}) + "\n")
                    sys.stderr.flush()
            tmp.replace(target)
        return
    die(f"comando não simulado: {cmd}")


if __name__ == "__main__":
    main(sys.argv[1:])
