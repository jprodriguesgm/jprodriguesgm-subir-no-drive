import json
import re

from subir import config
from subir.rclone import (DriveError, Loc, Rclone, folder_id_from_link, friendly, is_saida, is_transcricoes,
                          parse_stats_line)


def test_links():
    assert folder_id_from_link("https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOp?usp=sharing") == "1AbCdEfGhIjKlMnOp"
    assert folder_id_from_link("https://drive.google.com/open?id=1AbCdEfGhIjKlMnOpQr") == "1AbCdEfGhIjKlMnOpQr"
    assert folder_id_from_link("https://drive.google.com/drive/u/1/folders/1AbCdEfGhIjKlMnOp") == "1AbCdEfGhIjKlMnOp"
    assert folder_id_from_link("isso não é link") is None


def test_nomes():
    for n in ("Saída", "Saida", "SAÍDA", " saída "):
        assert is_saida(n)
    assert not is_saida("Saídas antigas")
    for n in ("Transcrições", "Transcricoes", "transcrições"):
        assert is_transcricoes(n)


def test_progresso_json_e_texto():
    line = json.dumps({"level": "notice", "msg": "x", "stats": {"bytes": 50, "totalBytes": 100, "speed": 10.0, "eta": 5}})
    assert parse_stats_line(line) == (50.0, 100.0, 10.0, 5.0)
    t = parse_stats_line("2026/11/23 15:00:00 NOTICE:    1.100 GiB / 1.800 GiB, 61%, 24.000 MiB/s, ETA 1m2s")
    assert t is not None
    assert round(t[0] / 1024 ** 3, 2) == 1.1 and round(t[1] / 1024 ** 3, 2) == 1.8
    assert round(t[2] / 1024 ** 2) == 24 and t[3] == 62
    assert parse_stats_line('{"level":"error","msg":"Failed to copy"}') is None
    assert parse_stats_line("") is None


def test_mensagens():
    e = friendly("googleapi: Error 403: Request had insufficient authentication scopes. ACCESS_TOKEN_SCOPE_INSUFFICIENT")
    assert e.kind == "escopo"
    assert friendly("oauth2: cannot fetch token: invalid_grant").kind == "token"
    assert friendly('Post "https://x": dial tcp: lookup www.googleapis.com: no such host').kind == "internet"
    assert friendly("googleapi: Error 403: The user's Drive storage quota has been exceeded., storageQuotaExceeded").kind == "cheio"


def test_config_formato_da_versao_4(drive):
    sup = drive["tmp"] / "sup"
    sup.mkdir()
    rdir = drive["rclone"].rsplit("/", 1)[0]
    # exatamente como o instalador .command da versão 4 grava
    (sup / "env.sh").write_text(f'export PATH="{rdir}:$PATH"\nexport RCLONE_CONFIG="/x/rclone.conf"\n')
    (sup / "config.txt").write_text("drive\nGravações IEC\nconta@exemplo.edu\n")
    c = config.load()
    assert c.rclone == drive["rclone"] and c.rclone_config == "/x/rclone.conf"
    assert c.remote == "drive" and c.root == "Gravações IEC" and c.email == "conta@exemplo.edu"
    assert c.complete


def test_config_salva_no_formato_que_o_revisor_le(drive):
    config.save(drive["rclone"], "drive", "/Gravações IEC/", "conta@exemplo.edu")
    sup = drive["tmp"] / "sup"
    env = (sup / "env.sh").read_text()
    lines = (sup / "config.txt").read_text().splitlines()
    assert lines[:3] == ["drive", "Gravações IEC", "conta@exemplo.edu"]
    # mesmas expressões do Revisor de Vídeos (revisor/drive.py → _subir_files)
    found = None
    for line in env.splitlines():
        m = re.match(r'\s*export\s+PATH="([^"]+)"', line)
        if m:
            for d in m.group(1).split(":"):
                if d and "$" not in d and (__import__("pathlib").Path(d) / "rclone").is_file():
                    found = str(__import__("pathlib").Path(d) / "rclone")
    assert found and found.endswith("/rclone")
    assert "RCLONE_CONFIG" not in env
    assert config.load().complete


def test_pastas_link_e_id(drive):
    rc = Rclone(drive["rclone"], "drive", None, "Gravações IEC")
    assert rc.list_dirs(Loc()) == ["26_600 Professor Exemplo", "26_701 Maria Clara Souza"]
    day = Loc(["26_701 Maria Clara Souza", "2026 11 10"])
    assert rc.list_dirs(day) == ["Footage", "Saída"]
    fid = rc.folder_id(day.child("Saída"))
    assert fid and fid.startswith("F")
    assert rc.find_by_id(fid) == ["26_701 Maria Clara Souza", "2026 11 10", "Saída"]
    # pasta fora da pasta inicial: não acha (vira pasta "pelo link")
    out = Rclone(drive["rclone"], "drive", None, "").folder_id(Loc(["Fora", "Outra"]))
    assert rc.find_by_id(out) is None
    assert rc.base_name(out) == "Outra"
    assert rc.list_dirs(Loc([], out, "Outra")) == []
    rc.mkdir(day.child("Nova"))
    assert "Nova" in rc.list_dirs(day)
    assert rc.can_upload()


def test_escopo_so_leitura(drive, monkeypatch):
    monkeypatch.setenv("FAKE_SCOPE", "drive.readonly")
    rc = Rclone(drive["rclone"], "drive", None, "Gravações IEC")
    assert not rc.can_upload()


def test_rclone_inexistente():
    try:
        Rclone("/nao/existe/rclone", "drive")
    except DriveError as e:
        assert e.kind == "sem_rclone"
    else:
        raise AssertionError
