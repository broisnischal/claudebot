"""Native sound: the mic and the speaker, with WebRTC echo cancellation between them.

The pet's webview (WebKitGTK) has no echo canceller, and without one the voice hears itself and cuts
itself off. So audio never touches a window. One PortAudio stream runs at 48 kHz in 10 ms blocks:
whatever goes to the speaker is fed to the WebRTC audio processing module as the far end, the mic
block is cleaned against it, decimated to 16 kHz and handed to the hub for voice detection.

The stream only runs while something needs it: duplex during a call or push to talk, output only
while a reply plays outside a call, nothing otherwise (so the mic indicator stays off).
"""

import logging
import threading
import time
from collections import deque

import numpy as np
import sounddevice as sd
from scipy import signal

log = logging.getLogger("claudebot_voice.audio")

RATE = 48000
BLOCK = 480  # 10 ms, the frame size the audio processing module takes
# Headroom for the callback: it needs the GIL, and TTS and the Claude session share this process.
# PortAudio's "low" latency is a few ms, which underruns (crackles) whenever Python is busy.
LATENCY = 0.05
TTS_RATE = 24000
DECIMATE = RATE // 16000
LOWPASS = signal.firwin(63, 7000, fs=RATE)


def devices() -> dict:
    """Input and output device names for the settings panel."""
    ins, outs = [], []
    try:
        for d in sd.query_devices():
            if d["max_input_channels"] > 0:
                ins.append(d["name"])
            if d["max_output_channels"] > 0:
                outs.append(d["name"])
    except Exception:
        log.debug("could not list devices", exc_info=True)
    return {"input": ins, "output": outs}


def _device(name: str, kind: str):
    if not name:
        return None
    try:
        for i, d in enumerate(sd.query_devices()):
            if d["name"] == name and d[f"max_{kind}_channels"] > 0:
                return i
    except Exception:
        pass
    return None


# ---- the Jarvis voice treatment ---------------------------------------------------------------
# The browser version was a Web Audio graph. Each sentence is rendered in one go here, so the same
# chain runs offline: EQ, compressor, a short bright room and a faint drifting double.


def _biquad(kind: str, f0: float, fs: float, gain_db: float = 0.0, q: float = 0.8):
    """RBJ cookbook coefficients, the same formulas Web Audio uses."""
    a = 10 ** (gain_db / 40)
    w = 2 * np.pi * f0 / fs
    cw, sw = np.cos(w), np.sin(w)
    if kind == "highpass":
        al = sw / (2 * q)
        b = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]
        den = [1 + al, -2 * cw, 1 - al]
    elif kind == "peaking":
        al = sw / (2 * q)
        b = [1 + al * a, -2 * cw, 1 - al * a]
        den = [1 + al / a, -2 * cw, 1 - al / a]
    else:  # shelves with slope 1, as Web Audio does
        al = sw / 2 * np.sqrt(2)
        sa = 2 * np.sqrt(a) * al
        if kind == "lowshelf":
            b = [a * ((a + 1) - (a - 1) * cw + sa), 2 * a * ((a - 1) - (a + 1) * cw), a * ((a + 1) - (a - 1) * cw - sa)]
            den = [(a + 1) + (a - 1) * cw + sa, -2 * ((a - 1) + (a + 1) * cw), (a + 1) + (a - 1) * cw - sa]
        else:
            b = [a * ((a + 1) + (a - 1) * cw + sa), -2 * a * ((a - 1) + (a + 1) * cw), a * ((a + 1) + (a - 1) * cw - sa)]
            den = [(a + 1) - (a - 1) * cw + sa, 2 * ((a - 1) - (a + 1) * cw), (a + 1) - (a - 1) * cw - sa]
    return np.array(b) / den[0], np.array(den) / den[0]


EQ = [("highpass", 75, 0, 0.7), ("lowshelf", 190, 3), ("peaking", 420, -1.5, 1.1),
      ("peaking", 3300, -2.5, 1.1), ("highshelf", 9500, 2.5)]


def _room(fs: int) -> np.ndarray:
    rng = np.random.default_rng(7)
    n, gap = int(fs * 0.7), int(fs * 0.008)
    ir = rng.uniform(-1, 1, n) * (1 - np.arange(n) / n) ** 3.2
    ir[:gap] = 0
    return ir / np.sqrt(np.sum(ir**2))  # unit energy: the wet signal sits at the dry level


ROOM = _room(TTS_RATE)
SOS = [_biquad(*spec[:2], TTS_RATE, *spec[2:]) for spec in EQ]


def _compress(x: np.ndarray, fs: int, threshold=-24.0, knee=14.0, ratio=3.2, attack=0.004, release=0.16) -> np.ndarray:
    hop = fs // 1000
    n = len(x) // hop + 1
    pad = np.pad(np.abs(x), (0, n * hop - len(x)))
    level = 20 * np.log10(np.maximum(pad.reshape(n, hop).max(axis=1), 1e-6))
    over = level - threshold
    reduce = np.where(over <= -knee / 2, 0.0,
                      np.where(over >= knee / 2, over * (1 - 1 / ratio),
                               (1 - 1 / ratio) * (over + knee / 2) ** 2 / (2 * knee)))
    ka, kr = np.exp(-1 / (attack * 1000)), np.exp(-1 / (release * 1000))
    env = np.empty(n)
    e = 0.0
    for i, r in enumerate(reduce):  # 1 ms steps, so a sentence is a few thousand iterations
        e = (ka if r > e else kr) * e + (1 - (ka if r > e else kr)) * r
        env[i] = e
    gain = 10 ** (-np.repeat(env, hop)[: len(x)] / 20)
    return x * gain


def jarvis(x: np.ndarray, fs: int = TTS_RATE) -> np.ndarray:
    dry_rms = np.sqrt(np.mean(x**2)) + 1e-9
    y = x
    for b, a in SOS:
        y = signal.lfilter(b, a, y)
    y = _compress(y, fs)
    y *= dry_rms / (np.sqrt(np.mean(y**2)) + 1e-9)  # makeup gain back to the dry loudness
    room = signal.fftconvolve(y, ROOM)[: len(y) + int(fs * 0.25)]
    t = np.arange(len(room)) / fs
    delay = (0.013 + 0.0018 * np.sin(2 * np.pi * 0.21 * t)) * fs
    idx = np.arange(len(room)) - delay
    yy = np.pad(y, (0, len(room) - len(y)))
    double = np.interp(idx, np.arange(len(yy)), yy, left=0, right=0)
    return yy + room * 0.023 + double * 0.14


def render(pcm: bytes, effect: str) -> np.ndarray:
    """Kokoro's 24 kHz int16 sentence to 48 kHz float32 ready for the speaker."""
    x = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
    if effect == "jarvis" and len(x):
        x = jarvis(x)
    y = signal.resample_poly(x, RATE // TTS_RATE, 1)
    return np.clip(y, -1, 1).astype(np.float32)


# ---- the device ------------------------------------------------------------------------------


class Device:
    """Owns the PortAudio stream. Callbacks run on PortAudio's thread and post back to the loop."""

    def __init__(self, loop, on_mic, on_play, settings, music):
        self.loop = loop
        self.music = music  # mixed under the voice, see music.py
        self.on_mic = on_mic  # (int16 array at 16 kHz)
        self.on_play = on_play  # (event, turn, text): "start" when a sentence starts, "idle" when all is played
        self.settings = settings
        self.lock = threading.Lock()
        self.queue: deque = deque()  # [turn, float32 samples, text, position]
        self.stream = None
        self.mode = None  # "duplex" | "output"
        self.want_input = False
        self.apm = None
        self.zi = np.zeros(len(LOWPASS) - 1)
        self.phase = 0
        self.mic_level = 0.0
        self.out_level = 0.0
        self.playing_turn = None
        self.idle_since = 0.0
        self.error = ""
        self.duck = False  # the hub sets it while either of us talks
        self.music_gain = 0.0

    # ---- playback queue (loop thread) ----

    def play(self, turn: int, samples: np.ndarray, text: str):
        with self.lock:
            self.queue.append([turn, samples, text, 0])
        self.reconcile()

    def stop(self):
        with self.lock:
            self.queue.clear()
            was = self.playing_turn
            self.playing_turn = None
            self.idle_since = time.monotonic()
        if was is not None:
            self.loop.call_soon_threadsafe(self.on_play, "idle", was, "")

    @property
    def busy(self) -> bool:
        return bool(self.queue)

    # ---- stream lifecycle (loop thread) ----

    def set_input(self, on: bool):
        self.want_input = on
        self.reconcile()

    def reconcile(self):
        now = time.monotonic()
        if self.want_input:
            want = "duplex"
        elif self.queue or self.playing_turn is not None or self.music.active:
            want = "output"
        elif self.mode == "output" and now - self.idle_since < 3:
            want = "output"  # keep the speaker warm briefly between sentences
        else:
            want = None
        if want == self.mode or (want == "output" and self.mode == "duplex" and self.queue):
            return  # never cut a reply off just because the call ended mid-sentence
        self._close()
        if want:
            self._open(want)

    def _open(self, mode: str):
        from livekit import rtc

        s = self.settings
        try:
            if mode == "duplex":
                if self.apm is None:
                    self.apm = rtc.AudioProcessingModule(echo_cancellation=True, noise_suppression=True,
                                                         high_pass_filter=True, auto_gain_control=True)
                self._rtc = rtc
                self.zi = np.zeros(len(LOWPASS) - 1)
                self.phase = 0
                self.stream = sd.Stream(samplerate=RATE, blocksize=BLOCK, channels=1, dtype="int16",
                                        device=(_device(s.get("input_device", ""), "input"),
                                                _device(s.get("output_device", ""), "output")),
                                        latency=LATENCY, callback=self._duplex)
            else:
                self.stream = sd.OutputStream(samplerate=RATE, blocksize=BLOCK, channels=1, dtype="int16",
                                              device=_device(s.get("output_device", ""), "output"),
                                              latency=LATENCY, callback=self._output)
            self.stream.start()
            self.mode = mode
            self.error = ""
            log.info("audio %s open", mode)
        except Exception as e:
            self.stream = None
            self.mode = None
            self.error = str(e)
            log.exception("could not open audio (%s)", mode)

    def _close(self):
        stream, self.stream, self.mode = self.stream, None, None
        if stream:
            try:
                stream.stop()
                stream.close()
            except Exception:
                log.debug("closing audio failed", exc_info=True)
        self.mic_level = self.out_level = 0.0

    def close(self):
        self.stop()
        self._close()

    # ---- callbacks (PortAudio thread) ----

    def _next_out(self, frames: int) -> np.ndarray:
        out = np.zeros(frames, dtype=np.float32)
        filled = 0
        started = None
        with self.lock:
            while filled < frames and self.queue:
                item = self.queue[0]
                turn, samples, text, pos = item
                if pos == 0:
                    started = (turn, text)
                take = min(frames - filled, len(samples) - pos)
                out[filled:filled + take] = samples[pos:pos + take]
                filled += take
                item[3] = pos + take
                if item[3] >= len(samples):
                    self.queue.popleft()
            empty = not self.queue
            playing = self.playing_turn
            if started:
                self.playing_turn = started[0]
            elif empty and filled == 0 and playing is not None:
                self.playing_turn = None
        if started:
            self.loop.call_soon_threadsafe(self.on_play, "start", started[0], started[1])
        elif empty and filled == 0 and playing is not None:
            self.idle_since = time.monotonic()
            self.loop.call_soon_threadsafe(self.on_play, "idle", playing, "")
        out *= float(self.settings.get("volume", 0.8))
        self.out_level = float(np.sqrt(np.mean(out**2)))
        music = self.music.take(frames)
        if music is not None:
            s = self.settings
            target = float(s.get("music_volume", 0.6)) * (float(s.get("duck", 0.2)) if self.duck else 1.0)
            g0 = self.music_gain
            # down fast (about 60 ms) so my first word is clear, back up slowly (about a third of a second)
            g1 = g0 + (target - g0) * (0.15 if target < g0 else 0.03)
            self.music_gain = g1
            out += music * np.linspace(g0, g1, frames, dtype=np.float32)
        return (np.clip(out, -1, 1) * 32767).astype(np.int16)

    def _output(self, outdata, frames, time_info, status):
        outdata[:, 0] = self._next_out(frames)

    def _duplex(self, indata, outdata, frames, time_info, status):
        out = self._next_out(frames)
        outdata[:, 0] = out
        mic = indata[:, 0].copy()
        if self.apm is not None and frames == BLOCK:
            rtc = self._rtc
            self.apm.process_reverse_stream(rtc.AudioFrame(out.tobytes(), RATE, 1, BLOCK))
            near = rtc.AudioFrame(mic.tobytes(), RATE, 1, BLOCK)
            self.apm.process_stream(near)
            mic = np.frombuffer(bytes(near.data), dtype=np.int16)
        x = mic.astype(np.float32)
        self.mic_level = float(np.sqrt(np.mean((x / 32768) ** 2)))
        y, self.zi = signal.lfilter(LOWPASS, 1.0, x, zi=self.zi)
        start = (-self.phase) % DECIMATE
        dec = y[start::DECIMATE]
        self.phase = (self.phase + frames) % DECIMATE
        pcm = np.clip(dec, -32768, 32767).astype(np.int16)
        self.loop.call_soon_threadsafe(self.on_mic, pcm)
