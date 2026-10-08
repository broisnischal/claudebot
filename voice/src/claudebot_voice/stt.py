"""Speech to text through `voxtype transcribe`, so it uses the same engine and model as my dictation."""

import asyncio
import re
import tempfile
import wave

import numpy as np

from .config import RUNTIME_DIR

# voxtype prints these progress lines on stdout ahead of the transcript.
PROGRESS = ("Loading audio file:", "Audio format:", "Processing ")
# Log lines voxtype writes to stdout when stdout is not a terminal.
ANSI = re.compile(r"\x1b\[[0-9;]*m")
LOGLINE = re.compile(r"^\d{4}-\d\d-\d\dT\S+\s+(TRACE|DEBUG|INFO|WARN|ERROR)\b")
# What whisper says when it heard nothing worth answering.
NOISE = re.compile(r"^\W*(\[[^\]]*\]|\([^)]*\)|you|\.+|uh+|um+|hmm+)?\W*$", re.I)


async def transcribe(pcm: np.ndarray, model: str = "") -> str:
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
    lines = [ANSI.sub("", l).strip() for l in out.decode(errors="replace").splitlines()]
    text = " ".join(l for l in lines if l and not l.startswith(PROGRESS) and not LOGLINE.match(l)).strip()
    return "" if NOISE.match(text) else text
