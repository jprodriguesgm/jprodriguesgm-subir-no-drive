import json
import time
from pathlib import Path

from subir import fala
from subir.job import Job, make_items, transcription_dest
from subir.rclone import Loc, Rclone

SAIDA = Loc(["26_701 Maria Clara Souza", "2026 11 10", "Saída"])


def fake(step=0.05, n=3, fail=None):
    def tr(path, progress=None, cancel=None, proc_holder=None):
        if fail and fail in Path(path).name:
            raise fala.SpeechError(fail)
        for k in range(n):
            if cancel is not None and cancel.is_set():
                raise fala.Cancelled()
            if progress:
                progress(k / n, k + 1, n)
            time.sleep(step)
        return fala.build(Path(path).name, 12.5, [[0.5, 0.9, "Olá", 0.9]], [[0.5, 0.9, "Olá"]],
                          model=fala.MODEL_NAME)
    return tr


def run_job(rc, items, dest, tr, transcriber):
    j = Job(rc, items, dest, tr, transcriber=transcriber)
    j.start()
    j.wait(60)
    for _ in range(100):
        if not j.busy:
            break
        time.sleep(0.05)
    return j


def test_vai_para_transcricoes_ao_lado_da_saida(drive, videos):
    rc = Rclone(drive["rclone"], "drive", None, "Gravações IEC")
    tr, why = transcription_dest(rc, SAIDA)
    assert why == "" and tr.parts == ["26_701 Maria Clara Souza", "2026 11 10", "Transcrições"]
    j = run_job(rc, make_items(videos, True), SAIDA, tr, fake())
    day = drive["root"] / "Gravações IEC" / "26_701 Maria Clara Souza" / "2026 11 10"
    assert sorted(p.name for p in (day / "Saída").iterdir()) == ["01 Aula.mp4", "02 Aula.mp4"]
    got = sorted(p.name for p in (day / "Transcrições").iterdir())
    assert got == ["01 Aula.transcricao.json", "02 Aula.transcricao.json"]
    data = json.loads((day / "Transcrições" / "01 Aula.transcricao.json").read_text(encoding="utf-8"))
    assert data["formato"] == "revisor-transcricao" and data["versao"] == 1
    assert data["video"]["arquivo"] == "01 Aula.mp4"
    assert all(it.up == "ok" and it.tr == "ok" for it in j.items)
    j.cleanup()


def test_usa_pasta_transcricoes_que_ja_existe_sem_acento(drive):
    day = drive["root"] / "Gravações IEC" / "26_701 Maria Clara Souza" / "2026 11 10"
    (day / "Transcricoes").mkdir()
    rc = Rclone(drive["rclone"], "drive", None, "Gravações IEC")
    tr, _ = transcription_dest(rc, SAIDA)
    assert tr.parts[-1] == "Transcricoes"


def test_pasta_que_nao_e_saida_tambem_vai_ao_lado(drive):
    rc = Rclone(drive["rclone"], "drive", None, "Gravações IEC")
    tr, _ = transcription_dest(rc, Loc(["26_701 Maria Clara Souza", "2026 11 10"]))
    assert tr.parts == ["26_701 Maria Clara Souza", "Transcrições"]


def test_sem_pasta_ao_lado(drive):
    rc = Rclone(drive["rclone"], "drive", None, "Gravações IEC")
    assert transcription_dest(rc, Loc())[0] is None
    assert transcription_dest(rc, Loc([], "Fxyz", "Pasta do link"))[0] is None


def test_transcricao_nao_atrasa_o_envio(drive, videos, monkeypatch):
    """Os vídeos sobem enquanto a transcrição (lenta) ainda roda."""
    rc = Rclone(drive["rclone"], "drive", None, "Gravações IEC")
    tr, _ = transcription_dest(rc, SAIDA)
    j = Job(rc, make_items(videos, True), SAIDA, tr, transcriber=fake(step=0.6, n=3))
    j.start()
    t0 = time.time()
    while not j.videos_done and time.time() - t0 < 20:
        time.sleep(0.05)
    assert j.videos_done and time.time() - t0 < 1.8      # 2 transcrições levariam ~3,6 s
    assert all(it.up == "ok" for it in j.items)
    assert any(it.tr in ("ouvindo", "fila") for it in j.items)
    j.wait(30)
    for _ in range(100):
        if not j.busy:
            break
        time.sleep(0.05)
    assert all(it.tr == "ok" for it in j.items)


def test_video_que_falha_e_tentar_de_novo(drive, videos, monkeypatch):
    monkeypatch.setenv("FAKE_FAIL", "02 Aula")
    rc = Rclone(drive["rclone"], "drive", None, "Gravações IEC")
    tr, _ = transcription_dest(rc, SAIDA)
    j = run_job(rc, make_items(videos, True), SAIDA, tr, fake())
    a, b = j.items
    assert a.up == "ok" and a.tr == "ok"
    assert b.up == "erro" and b.up_kind == "internet" and b.tr == "pronta"   # espera o vídeo subir
    day = drive["root"] / "Gravações IEC" / "26_701 Maria Clara Souza" / "2026 11 10"
    assert not (day / "Transcrições" / "02 Aula.transcricao.json").exists()
    monkeypatch.delenv("FAKE_FAIL")
    j.retry()
    j.wait(60)
    for _ in range(100):
        if not j.busy:
            break
        time.sleep(0.05)
    assert b.up == "ok" and b.tr == "ok"
    assert (day / "Saída" / "02 Aula.mp4").exists()
    assert (day / "Transcrições" / "02 Aula.transcricao.json").exists()


def test_sem_fala_nao_sobe_transcricao(drive, videos):
    rc = Rclone(drive["rclone"], "drive", None, "Gravações IEC")
    tr, _ = transcription_dest(rc, SAIDA)
    j = run_job(rc, make_items(videos, True), SAIDA, tr, fake(fail="sem_fala"))
    # "fail" só pega o nome: aqui nenhum vídeo tem "sem_fala" no nome → tudo ok
    assert all(it.tr == "ok" for it in j.items)
    j2 = run_job(rc, make_items(videos[:1], True), SAIDA, tr, fake(fail="01 Aula"))
    assert j2.items[0].tr == "erro"


def test_cancelar(drive, videos, monkeypatch):
    monkeypatch.setenv("FAKE_SPEED", "1000000")
    rc = Rclone(drive["rclone"], "drive", None, "Gravações IEC")
    tr, _ = transcription_dest(rc, SAIDA)
    j = Job(rc, make_items(videos, True), SAIDA, tr, transcriber=fake(step=0.5))
    j.start()
    time.sleep(0.8)
    j.cancel()
    j.wait(20)
    assert all(it.up in ("cancelado", "ok") for it in j.items)
    assert j.items[1].up == "cancelado"
    assert not j.busy
    day = drive["root"] / "Gravações IEC" / "26_701 Maria Clara Souza" / "2026 11 10"
    assert not (day / "Saída" / "02 Aula.mp4").exists()


def test_transcricao_desligada_e_arquivo_que_nao_e_video(drive, videos, tmp_path):
    rc = Rclone(drive["rclone"], "drive", None, "Gravações IEC")
    doc = tmp_path / "videos" / "roteiro.pdf"
    doc.write_bytes(b"%PDF")
    items = make_items(videos + [str(doc)], False)
    assert [it.tr for it in items] == ["desligada", "desligada", "nao_se_aplica"]
    j = run_job(rc, items, SAIDA, None, fake())
    assert all(it.up == "ok" for it in j.items)
    day = drive["root"] / "Gravações IEC" / "26_701 Maria Clara Souza" / "2026 11 10"
    assert not (day / "Transcrições").exists()


def test_pasta_inteira(drive, videos, tmp_path):
    rc = Rclone(drive["rclone"], "drive", None, "Gravações IEC")
    folder = tmp_path / "videos"
    items = make_items([str(folder)], True)
    assert items[0].is_dir and items[0].tr == "nao_se_aplica"
    j = run_job(rc, items, SAIDA, None, fake())
    day = drive["root"] / "Gravações IEC" / "26_701 Maria Clara Souza" / "2026 11 10"
    assert (day / "Saída" / "videos" / "01 Aula.mp4").exists()


def test_progresso_texto_rclone_antigo(drive, videos, monkeypatch):
    monkeypatch.setenv("FAKE_TEXT_STATS", "1")
    monkeypatch.setenv("FAKE_SPEED", "4000000")
    rc = Rclone(drive["rclone"], "drive", None, "Gravações IEC")
    seen = []
    rc.copy(videos[0], SAIDA, progress=lambda b, t, s, e: seen.append((b, t)))
    assert seen and seen[-1][1] > 2_500_000
