import json
import shutil
import subprocess

import numpy as np
import pytest

from subir import fala


def test_pedacos_cortam_na_pausa():
    dur = 400.0
    env = [-20] * int(dur / 0.1)
    for i in range(1150, 1160):        # pausa em 115–116 s (dentro dos 20 s antes do alvo de 120 s)
        env[i] = -70
    ch = fala.plan_chunks((0.0, dur), env, 0.1)
    assert ch[0][0] == 0.0 and abs(ch[0][1] - 115.5) < 0.2
    assert ch[-1][1] == dur
    assert all(b > a for a, b in ch)
    assert fala.plan_chunks((0.0, 100.0), env, 0.1) == [(0.0, 100.0)]


def test_envelope():
    s = np.zeros(fala.SAMPLE_RATE * 2, dtype=np.int16)
    s[fala.SAMPLE_RATE:] = 16384
    e = fala.envelope_db(s)
    assert len(e) == 20 and e[0] == -90 and -7 <= e[-1] <= -5


def test_palavras_do_whisper():
    raw = {"transcription": [{"offsets": {"from": 0, "to": 2000}, "text": " Olá, pessoal.", "tokens": [
        {"text": "[_BEG_]", "offsets": {"from": 0, "to": 0}},
        {"text": " Ol", "offsets": {"from": 100, "to": 300}, "p": 0.9},
        {"text": "á", "offsets": {"from": 300, "to": 500}, "p": 0.8},
        {"text": ",", "offsets": {"from": 500, "to": 520}, "p": 0.9},
        {"text": " pessoal", "offsets": {"from": 600, "to": 1100}, "p": 0.95, "t_dtw": 62},
        {"text": ".", "offsets": {"from": 1100, "to": 1150}, "p": 0.99}]}]}
    w = [x.to_list() for x in fala.words_from_whisper_json(raw, offset=100.0)]
    assert w == [[100.1, 100.52, "Olá,", 0.87], [100.62, 101.15, "pessoal.", 0.97]]


def test_formato_igual_ao_do_revisor(tmp_path):
    d = fala.build("01 Aula.mp4", 1002.3745, [[1, 2, "a", 0.5]], [[1, 2, "a"]], model=fala.MODEL_NAME)
    assert set(d) == {"formato", "versao", "video", "motor", "aproximada", "criado", "words", "segments"}
    assert d["video"] == {"arquivo": "01 Aula.mp4", "duracao": 1002.375}
    p = fala.write(tmp_path / "Transcrições", "01 Aula.mp4", d)
    assert p.name == "01 Aula.transcricao.json"
    assert json.loads(p.read_text(encoding="utf-8"))["words"] == [[1.0, 2.0, "a", 0.5]]


def voz_pt() -> str | None:
    """Uma voz em português do Mac (para o "say"), se houver."""
    if not shutil.which("say"):
        return None
    out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if "pt_BR" in line or "pt-BR" in line:
            return line.split("  ")[0].strip()
    return None


@pytest.mark.skipif(not (fala.available() and voz_pt()), reason="só no Mac com o motor montado e voz em português")
def test_transcreve_de_verdade(tmp_path):
    """No Mac da montagem: fala gerada pelo "say", vídeo de teste, transcrição de verdade."""
    aiff = tmp_path / "fala.aiff"
    subprocess.run(["say", "-v", voz_pt(), "-o", str(aiff),
                    "Olá, pessoal. Nessa aula a gente vai ver o conceito de gestão de projetos."], check=True)
    mp4 = tmp_path / "01 Aula.mp4"
    subprocess.run([fala.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=320x240:d=8",
                    "-i", str(aiff), "-c:v", "mpeg4", "-c:a", "aac", "-shortest", str(mp4)], check=True)
    d = fala.transcribe_video(str(mp4))
    text = " ".join(w[2] for w in d["words"]).lower()
    assert "pessoal" in text and "projetos" in text
    assert abs(d["video"]["duracao"] - fala.probe(str(mp4))["duration"]) < 0.01
