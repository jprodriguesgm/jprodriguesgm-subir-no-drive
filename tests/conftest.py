import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def drive(tmp_path, monkeypatch):
    """Drive de mentira + rclone de mentira + pasta de configuração vazia."""
    d = tmp_path / "drive"
    (d / "Gravações IEC" / "26_701 Maria Clara Souza" / "2026 11 10" / "Saída").mkdir(parents=True)
    (d / "Gravações IEC" / "26_701 Maria Clara Souza" / "2026 11 10" / "Footage").mkdir()
    (d / "Gravações IEC" / "26_600 Professor Exemplo").mkdir()
    (d / "Fora" / "Outra").mkdir(parents=True)
    b = tmp_path / "bin"
    b.mkdir()
    shutil.copy(ROOT / "tools" / "fake_rclone.py", b / "rclone")
    (b / "rclone").chmod(0o755)
    monkeypatch.setenv("FAKE_DRIVE", str(d))
    monkeypatch.setenv("FAKE_SPEED", "200000000")
    monkeypatch.setenv("FAKE_LIST_DELAY", "0")
    monkeypatch.setenv("SUBIR_SUPPORT_DIR", str(tmp_path / "sup"))
    monkeypatch.setenv("SUBIR_WORK_DIR", str(tmp_path / "work"))
    return {"root": d, "rclone": str(b / "rclone"), "tmp": tmp_path}


@pytest.fixture
def videos(tmp_path):
    v = tmp_path / "videos"
    v.mkdir()
    out = []
    for name, size in (("01 Aula.mp4", 3_000_000), ("02 Aula.mp4", 2_000_000)):
        p = v / name
        p.write_bytes(os.urandom(size))
        out.append(str(p))
    return out
