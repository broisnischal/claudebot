"""Speech to text with whisper.cpp, in process, on the same model file voxtype uses for my dictation.

The model loads once (at startup) instead of on every utterance, and short utterances get a short
audio context: whisper normally encodes a full 30 s window, so a two-second question cost as much
as a long one. Together that takes a typical request from 1.5 to 2.5 s (voxtype as a fresh
process each time) down to about 0.2 s. If whisper.cpp or the model is missing, it falls back to
`voxtype transcribe`.
"""

import asyncio
import logging
import os
import re
import tempfile
import threading
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from .config import RUNTIME_DIR

log = logging.getLogger("claudebot_voice.stt")

MODELS = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "voxtype" / "models"
THREADS = max(2, min(6, (os.cpu_count() or 4) - 2))  # leave room for the TTS and the audio callback
CTX_FLOOR = 512  # below this whisper starts cutting short phrases off after a word

# voxtype prints these progress lines on stdout ahead of the transcript.
PROGRESS = ("Loading audio file:", "Audio format:", "Processing ")
ANSI = re.compile(r"\x1b\[[0-9;]*m")
LOGLINE = re.compile(r"^\d{4}-\d\d-\d\dT\S+\s+(TRIGGER|TRACE|DEBUG|INFO|WARN|ERROR)\b")
# What whisper says when it heard nothing worth answering.
NOISE = re.compile(r"^\W*(\[[^\]]*\]|\([^)]*\)|you|\.+|uh+|um+|hmm+)?\W*$", re.I)

# Words whisper should expect: the assistant's name and my agents' names, which it mishears most.
hints = "Jarvis, Claude Bot, tower"

_pool = ThreadPoolExecutor(1, thread_name_prefix="stt")
_lock = threading.Lock()
_models: dict[str, object] = {}


def _model_file(name: str) -> Path | None:
    for candidate in ([name] if name else []) + ["base.en", "small.en", "tiny.en", "base", "small", "tiny"]:
        path = MODELS / f"ggml-{candidate}.bin"
        if path.exists():
            return path
    return None


def _load(name: str):
    with _lock:
        if name in _models:
            return _models[name]
        model = None
        try:
            from pywhispercpp.model import Model

            path = _model_file(name)
            if path:
                model = Model(str(path), n_threads=THREADS, print_progress=False, print_realtime=False,
                              redirect_whispercpp_logs_to=None)
                log.info("whisper.cpp ready: %s, %d threads", path.name, THREADS)
        except Exception:
            log.warning("whisper.cpp unavailable, using voxtype", exc_info=True)
        _models[name] = model
        return model


def warm(name: str = ""):
    """Load the model now, so the first utterance doesn't pay for it."""
    model = _load(name)
    if model is not None:
        model.transcribe(np.zeros(16000, dtype=np.float32), language="en", single_segment=True, audio_ctx=CTX_FLOOR)


def _whisper(model, pcm: np.ndarray) -> str:
    x = pcm.astype(np.float32) / 32768
    ctx = min(1500, max(CTX_FLOOR, int(len(x) / 16000 * 50) + 64))  # 50 encoder frames a second
    segments = model.transcribe(x, language="en", single_segment=len(x) < 16000 * 20, no_context=True,
                                audio_ctx=ctx, initial_prompt=hints)
    return " ".join(s.text for s in segments).strip()


async def transcribe(pcm: np.ndarray, model: str = "") -> str:
    loop = asyncio.get_running_loop()
    engine = await loop.run_in_executor(_pool, _load, model)
    if engine is not None:
        text = await loop.run_in_executor(_pool, _whisper, engine, pcm)
    else:
        text = await _voxtype(pcm, model)
    return "" if NOISE.match(text) else text


async def _voxtype(pcm: np.ndarray, model: str) -> str:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=RUNTIME_DIR, prefix="utt-", suffix=".wav") as f:
        with wave.open(f.name, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(pcm.astype("<i2").tobytes())
        cmd = ["voxtype", "-q", *(["--model", model] if model else []), "transcribe", f.name]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), 60)
        except TimeoutError:
            proc.kill()
            raise RuntimeError("voxtype timed out")
    if proc.returncode:
        tail = err.decode(errors="replace").strip().splitlines()[-1:] or ["no output"]
        raise RuntimeError(f"voxtype exited {proc.returncode}: {tail[0]}")
    lines = [ANSI.sub("", line).strip() for line in out.decode(errors="replace").splitlines()]
    return " ".join(line for line in lines if line and not line.startswith(PROGRESS) and not LOGLINE.match(line)).strip()
