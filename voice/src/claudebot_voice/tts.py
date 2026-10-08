"""Kokoro text to speech. fp32 runs at about 0.3x real time on my CPU, int8 was slower."""

from collections import OrderedDict

import numpy as np
from kokoro_onnx import Kokoro

from .config import MODELS

SAMPLE_RATE = 24000
LANG = {"a": "en-us", "b": "en-gb"}
# "jarvis": calm British male. George carries it, Fable smooths it, Lewis adds weight.
BLENDS = {"jarvis": {"bm_george": 0.5, "bm_fable": 0.3, "bm_lewis": 0.2}}


class TTS:
    def __init__(self):
        self.kokoro = Kokoro(str(MODELS / "kokoro-v1.0.onnx"), str(MODELS / "voices-v1.0.bin"))
        self.cache: OrderedDict[tuple, bytes] = OrderedDict()

    def voices(self) -> list[str]:
        return [*BLENDS, *sorted(v for v in self.kokoro.get_voices() if v[:1] in LANG and v[1:2] in "fm")]

    def _style(self, voice: str):
        if voice in BLENDS:
            return sum(self.kokoro.get_voice_style(v) * w for v, w in BLENDS[voice].items()).astype(np.float32)
        return voice if voice in self.kokoro.get_voices() else "bm_george"

    def synth(self, text: str, voice: str, speed: float) -> bytes:
        """16-bit little-endian mono PCM at 24 kHz."""
        key = (text, voice, speed)
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        samples, _ = self.kokoro.create(text, voice=self._style(voice), speed=speed, lang="en-gb" if voice in BLENDS else LANG.get(voice[0], "en-us"))
        pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
        if len(text) <= 60:  # greetings and acknowledgements come back often
            self.cache[key] = pcm
            if len(self.cache) > 64:
                self.cache.popitem(last=False)
        return pcm
