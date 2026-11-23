"""Transcrição do vídeo, com o MESMO motor do Revisor de Vídeos.

Copiado do Revisor (revisor/speech.py, revisor/media.py e revisor/transcricao.py, GPL-3.0) só o necessário:
- whisper.cpp (whisper-cli, Metal no Mac) + modelo ggml-small-q5_1.bin, em português;
- o mesmo "prompt" inicial ao pé da letra (sem ele o Whisper "limpa" a fala e some com "errei",
  hesitação e repetição) e as mesmas opções do whisper-cli;
- áudio em WAV 16 kHz mono (FFmpeg); pedaços de ~120 s cortados na pausa mais longa (até 20 s antes do
  alvo); JSON completo do whisper-cli (-ojf); tokens juntados em palavras (words_from_whisper_json).

Diferença: aqui o vídeo inteiro é transcrito (o Revisor transcreve só o trecho entre as vinhetas e filtra
esse trecho sozinho quando lê a transcrição pronta). Tempos em segundos do vídeo inteiro.

Saída: "<nome do vídeo sem extensão>.transcricao.json", no formato que o Revisor lê (formato
"revisor-transcricao", versão 1). Não mudar o formato sem mudar o Revisor.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

MODEL_NAME = "ggml-small-q5_1.bin"
CHUNK_S = 120.0          # tamanho alvo do pedaço
CHUNK_SEARCH_S = 20.0    # procura a pausa mais longa até 20 s antes do alvo
SAMPLE_RATE = 16000      # o Whisper trabalha em 16 kHz mono
ENV_STEP = 0.1           # envelope do áudio: pico a cada 100 ms

# "Prompt" inicial: exemplo de fala transcrita AO PÉ DA LETRA (igual ao do Revisor).
PROMPT = ("Olá, pessoal. Então, é... nessa aula a gente vai, a gente vai ver... "
          "Errei, vou voltar. Deixa eu repetir: nessa aula a gente vai ver o conceito.")

FORMAT = "revisor-transcricao"
VERSION = 1
SUFFIX = ".transcricao.json"
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".mxf", ".webm", ".mts", ".m2ts"}


class SpeechError(RuntimeError):
    pass


class Cancelled(Exception):
    pass


# ------------------------------------------------------------------ programas dentro do app

def _bundled_dirs() -> list[Path]:
    dirs = []
    if os.environ.get("SUBIR_FFMPEG_DIR"):
        dirs.append(Path(os.environ["SUBIR_FFMPEG_DIR"]))
    base = getattr(sys, "_MEIPASS", None)  # app empacotado (PyInstaller)
    if base:
        dirs.append(Path(base) / "bin")
    dirs.append(Path(__file__).resolve().parent.parent / "bin")
    return dirs


def find_tool(name: str) -> str | None:
    exe = name + (".exe" if platform.system() == "Windows" else "")
    for d in _bundled_dirs():
        p = d / exe
        if p.is_file():
            return str(p)
    return shutil.which(name)


def ffmpeg() -> str:
    p = find_tool("ffmpeg")
    if not p:
        raise SpeechError("FFmpeg não encontrado dentro do app")
    return p


def ffprobe() -> str:
    p = find_tool("ffprobe")
    if not p:
        raise SpeechError("FFprobe não encontrado dentro do app")
    return p


def find_cli() -> str | None:
    for name in ("whisper-cli", "whisper-cpp"):
        p = find_tool(name)
        if p:
            return p
    return None


def find_model() -> str | None:
    if os.environ.get("SUBIR_WHISPER_MODEL") and Path(os.environ["SUBIR_WHISPER_MODEL"]).is_file():
        return os.environ["SUBIR_WHISPER_MODEL"]
    for d in _bundled_dirs():
        for p in (d.parent / "models" / MODEL_NAME, d / MODEL_NAME):
            if p.is_file():
                return str(p)
    return None


def available() -> bool:
    return bool(find_cli() and find_model() and find_tool("ffmpeg") and find_tool("ffprobe"))


def threads() -> int:
    n = os.cpu_count() or 4
    return max(1, min(8, n))


def is_video(path: str | Path) -> bool:
    return Path(path).suffix.lower() in VIDEO_EXT


# ------------------------------------------------------------------ vídeo

def probe(path: str) -> dict:
    """{"duration": s, "has_audio": bool} do arquivo (a duração é a que o Revisor confere, ±0,5 s)."""
    cmd = [ffprobe(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise SpeechError("não consegui ler o vídeo: " + r.stderr.decode(errors="ignore")[-300:])
    data = json.loads(r.stdout.decode("utf-8", errors="replace") or "{}")
    dur = None
    try:
        dur = float(data.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        pass
    streams = data.get("streams", [])
    if dur is None:
        for s in streams:
            try:
                dur = max(dur or 0.0, float(s.get("duration")))
            except (TypeError, ValueError):
                pass
    return {"duration": dur, "has_audio": any(s.get("codec_type") == "audio" for s in streams)}


def extract_wav(video_path: str, dst: str, proc_holder: list | None = None) -> None:
    cmd = [ffmpeg(), "-hide_banner", "-nostdin", "-loglevel", "error", "-y", "-i", str(video_path),
           "-map", "0:a:0", "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le", dst]
    p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if proc_holder is not None:
        proc_holder.append(p)
    _, err = p.communicate()
    if p.returncode != 0:
        raise SpeechError("não consegui ler o áudio: " + (err or b"").decode(errors="ignore")[-400:])


def read_wav(path: str) -> np.ndarray:
    with wave.open(path, "rb") as w:
        data = w.readframes(w.getnframes())
    return np.frombuffer(data, dtype=np.int16)


def write_wav(path: str, samples: np.ndarray) -> None:
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(samples.astype(np.int16).tobytes())


def envelope_db(samples: np.ndarray, step: float = ENV_STEP) -> list[int]:
    """Pico a cada 100 ms em dB (como o envelope do Revisor), para achar as pausas."""
    n = int(SAMPLE_RATE * step)
    if samples.size == 0:
        return []
    m = (samples.size // n) * n
    a = np.abs(samples.astype(np.float32)) / 32768.0
    peaks = a[:m].reshape(-1, n).max(axis=1) if m else np.zeros(0, np.float32)
    if samples.size > m:
        peaks = np.concatenate([peaks, [a[m:].max()]])
    dbv = 20 * np.log10(np.maximum(peaks, 1e-9))
    return [int(max(-90, round(float(v)))) for v in dbv]


# ------------------------------------------------------------------ pedaços (igual ao Revisor)

def plan_chunks(content: tuple[float, float], env_db: list[int] | None, env_step: float) -> list[tuple[float, float]]:
    """Divide o conteúdo em pedaços de ~CHUNK_S, cortando no meio da pausa mais longa."""
    a, b = content
    if b - a <= CHUNK_S * 1.3:
        return [(a, b)]
    quiet = None
    if env_db:
        e = np.asarray(env_db, dtype=np.float32)
        quiet = e < -50.0
    chunks = []
    start = a
    while b - start > CHUNK_S * 1.3:
        target = start + CHUNK_S
        cut = target
        if quiet is not None:
            i0 = int((target - CHUNK_SEARCH_S) / env_step)
            i1 = int(target / env_step)
            best, best_len, run = None, 0, 0
            for i in range(max(i0, 0), min(i1 + 1, quiet.size)):
                run = run + 1 if quiet[i] else 0
                if run >= best_len and run > 0:
                    best_len, best = run, i - run // 2
            if best is not None and best_len >= 2:     # pelo menos 200 ms de pausa
                cut = best * env_step
        chunks.append((start, cut))
        start = cut
    chunks.append((start, b))
    return chunks


# ------------------------------------------------------------------ whisper (igual ao Revisor)

@dataclass
class Word:
    start: float
    end: float
    text: str
    p: float = 1.0

    def to_list(self):
        return [round(self.start, 2), round(self.end, 2), self.text, round(self.p, 2)]


def _norm(word: str) -> str:
    import unicodedata
    w = unicodedata.normalize("NFKD", word.lower())
    w = "".join(c for c in w if not unicodedata.combining(c))
    return re.sub(r"[^0-9a-z]+", "", w)


def words_from_whisper_json(data: dict, offset: float = 0.0) -> list[Word]:
    """Junta os tokens do JSON completo do whisper-cli em palavras com tempo."""
    out: list[Word] = []
    for seg in data.get("transcription", []):
        cur: list[dict] = []

        def flush():
            if not cur:
                return
            text = "".join(t["text"] for t in cur).strip()
            if not _norm(text):
                # pontuação solta: gruda na palavra anterior
                if out and text:
                    out[-1].text += text
                return
            t0 = _tok_start(cur[0])
            t1 = _tok_end(cur[-1])
            p = float(np.mean([t.get("p", 1.0) for t in cur]))
            out.append(Word(offset + t0, offset + max(t1, t0), text, p))

        for tok in seg.get("tokens", []):
            txt = tok.get("text", "")
            if txt.startswith("[_") or txt.startswith("<|"):
                continue          # tokens especiais (início, tempo…)
            if txt.startswith(" ") and cur:
                flush()
                cur = []
            cur.append(tok)
        flush()
    return out


def _tok_start(t: dict) -> float:
    d = t.get("t_dtw", -1)
    if isinstance(d, (int, float)) and d >= 0:
        return d / 100.0           # t_dtw vem em centésimos de segundo
    return t["offsets"]["from"] / 1000.0


def _tok_end(t: dict) -> float:
    return t["offsets"]["to"] / 1000.0


def backend_of(log: str) -> str:
    m = re.search(r"init_gpu: using (\S+) backend", log)
    dev = (m.group(1) if m else "").upper()
    return "Metal" if dev.startswith(("METAL", "MTL")) else "Vulkan" if dev.startswith("VULKAN") else "CPU"


def run_whisper(cli: str, model: str, wav: str, out: str, proc_holder: list | None = None) -> tuple[dict, str]:
    cmd = [cli, "-m", model, "-f", wav, "-l", "pt", "-t", str(threads()),
           "-mc", "0",            # não usa o texto anterior: evita "loop" e não alisa repetições
           "-bs", "1", "-bo", "1",  # guloso: 2–3× mais rápido; a diferença no texto é pequena
           "-sns",
           "--prompt", PROMPT,
           "-ojf", "-of", out]
    if "small" in Path(model).name:
        cmd[cmd.index("-ojf"):cmd.index("-ojf")] = ["-dtw", "small"]
    try:
        os.remove(out + ".json")
    except OSError:
        pass
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except OSError as e:
        raise SpeechError(f"{Path(cli).name} não abriu: {e}")
    if proc_holder is not None:
        proc_holder.append(p)
    _, err = p.communicate()
    log = (err or b"").decode(errors="ignore")
    if p.returncode != 0 or not os.path.exists(out + ".json"):
        raise SpeechError(f"{Path(cli).name} (código {p.returncode}): {log[-600:]}")
    raw = json.loads(Path(out + ".json").read_text(encoding="utf-8", errors="replace"))
    return raw, backend_of(log)


# ------------------------------------------------------------------ o vídeo inteiro

def transcribe_video(video_path: str, progress=None, cancel: threading.Event | None = None,
                     proc_holder: list | None = None, info: dict | None = None) -> dict:
    """Transcreve o vídeo inteiro. `progress(fração, pedaço, total)`. Devolve o conteúdo do
    .transcricao.json (dicionário). Sem fala nenhuma: SpeechError("sem_fala")."""
    cli, model = find_cli(), find_model()
    if not cli or not model:
        raise SpeechError("o motor de transcrição não está dentro do app")
    info = info or probe(video_path)
    dur = info.get("duration")
    if not dur:
        raise SpeechError("não consegui ler a duração do vídeo")
    if not info.get("has_audio"):
        raise SpeechError("sem_audio")

    def check():
        if cancel is not None and cancel.is_set():
            raise Cancelled()

    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix="subir_fala_") as tmp:
        full = os.path.join(tmp, "audio.wav")
        extract_wav(video_path, full, proc_holder)
        check()
        samples = read_wav(full)
        env = envelope_db(samples)
        chunks = plan_chunks((0.0, float(dur)), env, ENV_STEP)
        if progress:
            progress(0.0, 0, len(chunks))
        words: list[list] = []
        segs: list[list] = []
        backend = None
        for k, (a, b) in enumerate(chunks):
            check()
            if progress:
                progress(k / len(chunks), k + 1, len(chunks))
            i0, i1 = int(round(a * SAMPLE_RATE)), int(round(b * SAMPLE_RATE))
            piece = samples[i0:i1]
            if piece.size < SAMPLE_RATE // 10:
                continue
            wav = os.path.join(tmp, f"p{k:03d}.wav")
            write_wav(wav, piece)
            raw, backend = run_whisper(cli, model, wav, os.path.join(tmp, f"o{k:03d}"), proc_holder)
            os.remove(wav)
            words += [w.to_list() for w in words_from_whisper_json(raw, offset=a)]
            segs += [[round(a + s["offsets"]["from"] / 1000, 2), round(a + s["offsets"]["to"] / 1000, 2),
                      s.get("text", "").strip()] for s in raw.get("transcription", [])]
        if progress:
            progress(1.0, len(chunks), len(chunks))
    if not words:
        raise SpeechError("sem_fala")
    data = build(Path(video_path).name, float(dur), words, segs, model=MODEL_NAME)
    data["segundos"] = round(time.time() - t0, 1)
    if backend:
        data["motor"]["onde"] = backend
    return data


# ------------------------------------------------------------------ arquivo (igual ao Revisor)

def file_name(video_file: str) -> str:
    return Path(video_file).stem + SUFFIX


def build(video_file: str, duration: float, words: list, segments: list, model: str | None = None,
          program: str = "whisper.cpp", approx: bool = False) -> dict:
    return {"formato": FORMAT, "versao": VERSION,
            "video": {"arquivo": video_file, "duracao": round(float(duration), 3)},
            "motor": {"programa": program, "modelo": model},
            "aproximada": bool(approx), "criado": time.strftime("%Y-%m-%d %H:%M:%S"),
            "words": [[round(float(w[0]), 2), round(float(w[1]), 2), str(w[2]),
                       round(float(w[3]) if len(w) > 3 else 1.0, 2)] for w in words],
            "segments": [[round(float(s[0]), 2), round(float(s[1]), 2), str(s[2])] for s in segments]}


def write(folder: Path, video_file: str, data: dict) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / file_name(video_file)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)
    return p
