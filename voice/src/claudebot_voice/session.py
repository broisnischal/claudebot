"""The hub: one conversation shared by the pet and the panel.

Mic audio arrives from the sound card as 16 kHz PCM, already echo cancelled (audio.py). Silero VAD
cuts it into utterances, voxtype turns them into text, the brain answers, and Kokoro speaks each
sentence as soon as it is complete. Speaking over the assistant cuts it off. Windows only watch and
send commands; none of them touches audio.
"""

import asyncio
import difflib
import json
import logging
import re
import socket
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

from . import audio, policy, stt, tower
from .brain import Brain
from .config import MODELS_CHOICES, WEB, Settings
from .memory import Memory
from .music import Music
from .tts import TTS
from .vad import FRAME, SileroVAD

log = logging.getLogger("claudebot_voice")

FRAME_MS = FRAME / 16  # 32 ms
PREROLL = 16  # frames (about half a second) kept from before speech was confirmed, so first words survive
MAX_UTTERANCE = int(30_000 / FRAME_MS)
LEVEL_HZ = 20
GRACE = 0.6  # seconds after I stop before the assistant may start talking
TAIL = 0.5  # its own voice still hangs in the room this long after playback stops
CONTINUE_S = 10  # an unanswered request can still be extended by what I say next, this long
DANGLE_S = 1.3  # extra wait when I trail off mid-thought
PARTIAL_EVERY = 1.5  # seconds between live transcripts while I talk
# After this much silence the transcriber already runs on what I said. If that reads as a finished
# sentence, my turn ends right there instead of after the full pause length.
EARLY_MS = 480
FINISHED = re.compile(r"[.?!]['\")\]]*\s*$")
# A sentence ending on one of these isn't finished ("turn on the lights and", "send it to").
DANGLING = re.compile(r"(\b(and|or|but|so|because|then|to|the|a|an|of|with|for|from|in|on|at|into|my|your|"
                      r"if|um+|uh+|er+|also)|,)\W*$", re.I)

YES = re.compile(r"^(yes|yeah|yep|yup|sure|ok|okay|go|go ahead|do it|allow|approve|approved|confirm|"
                 r"affirmative|please|please do|run it|ship it|correct|right|fine|sounds good)\b")
NO = re.compile(r"^(no|nope|nah|don't|do not|stop|cancel|deny|denied|negative|wait|hold on|never ?mind)\b")
HUSH = re.compile(r"^(stop|stop talking|shut up|be quiet|quiet|cancel|never ?mind|hold on|wait|enough)\W*$")


def build_id() -> str:
    """Changes whenever a window file changes, so open windows can reload themselves in development."""
    try:
        return str(max(int(p.stat().st_mtime) for p in WEB.iterdir() if p.suffix in (".js", ".html", ".css")))
    except (OSError, ValueError):
        return ""


class Client:
    """One window. Sends go through a queue so tasks never write to the socket at once."""

    def __init__(self, ws):
        self.ws = ws
        self.q: asyncio.Queue = asyncio.Queue(maxsize=4000)
        self.task = asyncio.create_task(self._pump())

    def send(self, msg):
        try:
            self.q.put_nowait(msg)
        except asyncio.QueueFull:
            pass

    async def _pump(self):
        while True:
            msg = await self.q.get()
            try:
                await self.ws.send_text(json.dumps(msg, default=str))
            except Exception:
                return  # socket closed

    def close(self):
        self.task.cancel()


class Hub:
    def __init__(self):
        self.settings = Settings.load()
        self.clients: dict[object, Client] = {}
        self.tts: TTS | None = None
        self.vad = SileroVAD()
        self.memory = Memory()
        self.music = Music(self._on_music)
        self.device: audio.Device | None = None
        self.brain = Brain(self)
        self.pool = ThreadPoolExecutor(1, thread_name_prefix="tts")
        self.tts_q: asyncio.Queue = asyncio.Queue()
        self.fleet: list[dict] = []
        self.fleet_print = None
        self.history: deque = deque(maxlen=300)
        self.tasks: list[asyncio.Task] = []

        self.call = False
        self.call_started = 0.0
        self.muted = False
        self.ptt = False

        self.turn = 0  # only this turn may speak; bumping it silences everything older
        self.seq = 0
        self.thinking = False
        self.transcribing = 0
        self.tts_pending = 0
        self.playing = False
        self.current_tool = ""
        self.approval: dict | None = None
        self.always: set[str] = set()
        self.announcements: list[str] = []
        self.phase = "idle"
        self.mic_buf = np.zeros(0, dtype=np.int16)
        self.preroll: deque = deque(maxlen=PREROLL)
        self.hold = False  # a barge-in paused the assistant until it's confirmed or a false alarm
        self.heard_end = 0.0  # when my last utterance ended
        self.played_end = 0.0  # when the assistant's audio last went quiet
        # How much of what the speaker plays still reaches the mic after echo cancellation, as a
        # ratio of levels. Starts cautious and learns while the assistant talks and I don't.
        self.echo_ratio = 0.5
        self.out_env = 0.0
        self.draft: dict | None = None  # the request I'm making: {text, at, turn, answered}
        self.dispatch: asyncio.Task | None = None  # sending a draft that trailed off, after a beat
        self.said: dict[int, list[str]] = {}  # turn: sentences that actually played
        self.recent_said: deque = deque(maxlen=12)  # (time, sentence), to catch my mic hearing it
        self.partial_task: asyncio.Task | None = None
        self.partial_at = 0.0
        # Latency of the last spoken request, end of my speech to its first audible word, by stage.
        self.timing: dict = {}
        self.last_timing: dict = {}
        self._reset_ears()

    # ---- lifecycle -----------------------------------------------------------------------

    async def start(self):
        loop = asyncio.get_running_loop()
        self.device = audio.Device(loop, self.on_mic, self._on_play, self.settings, self.music)
        self.tts = await loop.run_in_executor(self.pool, TTS)
        asyncio.create_task(asyncio.to_thread(stt.warm, self.settings["stt_model"]))  # model in memory before I speak
        self.tasks = [
            asyncio.create_task(self._tts_worker()),
            asyncio.create_task(tower.Watcher(self._on_fleet).run()),
            asyncio.create_task(self.brain.warm()),
            asyncio.create_task(self._ticker()),
        ]
        for phrase in ("Shoot.", "Go ahead.", "What's up?", "Listening.", "Okay."):
            self.pool.submit(self.tts.synth, phrase, self.settings["voice"], self.settings["speed"])
        log.info("ready")

    async def _ticker(self):
        """Levels for the orbs, and opening or closing the sound card as needs change."""
        n = 0
        build = build_id()
        while True:
            await asyncio.sleep(1 / LEVEL_HZ)
            n += 1
            d = self.device
            if self.call or self.ptt or self.playing:
                self.broadcast({"type": "level", "mic": round(d.mic_level, 4), "out": round(d.out_level, 4)})
            if n % 5 == 0:
                self.update()  # time-based: the grace after my voice, music coming back up
                self._flush_announcements()
            if n % 10 == 0:
                d.reconcile()
            if n % 40 == 0 and build != (build := build_id()):
                self.broadcast({"type": "build", "build": build})

    async def stop(self):
        for t in self.tasks:
            t.cancel()
        await self.music.stop(quiet=True)
        if self.device:
            self.device.close()
        await self.brain.close()

    def device_error(self) -> str:
        return self.device.error if self.device else ""

    async def join(self, ws):
        client = Client(ws)
        self.clients[ws] = client
        client.send({
            "type": "hello",
            "build": build_id(),
            "host": socket.gethostname(),  # my hostname rotates, so read it live
            "settings": dict(self.settings),
            "voices": self.tts.voices() if self.tts else [],
            "models": MODELS_CHOICES,
            "devices": audio.devices(),
            "fleet": tower.view(self.fleet),
            "history": list(self.history),
            "call": {"active": self.call, "started": self.call_started},
            "phase": self.phase,
            "muted": self.muted,
            "approval": self._approval_view(),
            "memory": self.memory.items,
            "music": self.music.state(),
            "audio_error": self.device_error(),
        })

    def leave(self, ws):
        client = self.clients.pop(ws, None)
        if client:
            client.close()

    # ---- output to windows ---------------------------------------------------------------

    def broadcast(self, msg: dict):
        for client in self.clients.values():
            client.send(msg)

    def log(self, role: str, text: str, **extra):
        entry = {"role": role, "text": text, "ts": time.time(), **extra}
        self.history.append(entry)
        self.broadcast({"type": "log", "entry": entry})

    def toast(self, text: str, kind: str = "info"):
        self.broadcast({"type": "toast", "text": text, "kind": kind})

    def tool(self, name: str, text: str = ""):
        self.current_tool = name.removeprefix("mcp__").replace("__", " ")
        self.broadcast({"type": "tool", "name": self.current_tool, "text": text})

    def memory_changed(self):
        self.broadcast({"type": "memory", "items": self.memory.items})

    def _on_music(self):
        self.broadcast({"type": "music", "music": self.music.state()})
        if self.device:
            self.device.reconcile()

    def update(self):
        phase = self._phase()
        if self.device:
            # music sits under both voices, and stays down through the short gaps between my words
            now = time.monotonic()
            self.device.duck = (self.user_active(now) or now - self.heard_end < 1.0 or self.playing
                                or self.tts_pending > 0 or self.hold)
        if phase != self.phase:
            self.phase = phase
            self.broadcast({"type": "phase", "phase": phase})

    def _phase(self) -> str:
        speaking = self.playing or self.tts_pending
        if not (self.call or self.ptt or self.thinking or self.transcribing or speaking or self.approval):
            return "idle"
        if self.approval:
            return "approval"
        if self.ptt or self.in_speech:
            return "hearing"
        if self.transcribing:
            return "transcribing"
        if self.playing and not self.hold:
            return "speaking"
        if self.thinking or self.tts_pending or self.dispatch:
            return "thinking"
        return "muted" if self.muted else "listening"

    def user_active(self, now: float | None = None) -> bool:
        """Am I talking, about to (voice building up), or did I only just stop?"""
        now = now or time.monotonic()
        return self.in_speech or self.ptt or self.hot >= 2 or now - self.heard_end < GRACE

    def engaged(self) -> bool:
        """Is the assistant doing anything for the current turn that my voice would cut into?"""
        return bool(self.playing or self.tts_pending or self.thinking or self.dispatch
                    or (self.device and self.device.busy))

    # ---- speaking ------------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return bool(self.settings.get("enabled", True))

    def say(self, text: str, turn: int | None = None):
        turn = self.turn if turn is None else turn
        if turn != self.turn or not text.strip() or not self.enabled:
            return
        self.seq += 1
        self.tts_pending += 1
        self.tts_q.put_nowait((turn, self.seq, text))
        self.update()

    def new_turn(self) -> int:
        """Silence whatever is queued or playing and hand the floor to a new turn."""
        self.turn += 1
        self.hold = False
        while not self.tts_q.empty():
            self.tts_q.get_nowait()
            self.tts_pending -= 1
        if self.device:
            self.device.stop()
        self.broadcast({"type": "stop", "turn": self.turn})
        self.playing = False
        self.update()
        return self.turn

    def _render(self, text: str):
        s = self.settings
        return audio.render(self.tts.synth(text, s["voice"], s["speed"]), s["effect"])

    async def _tts_worker(self):
        loop = asyncio.get_running_loop()
        while True:
            turn, seq, text = await self.tts_q.get()
            try:
                if turn != self.turn:
                    continue
                samples = await loop.run_in_executor(self.pool, self._render, text)
                self.mark("tts", turn)
                # Never start talking over me: wait while I speak (or a barge-in holds the floor)
                # and for a short grace after. A confirmed barge-in moves the turn on and this
                # sentence is dropped; a false alarm lets it through.
                while turn == self.turn and (self.hold or self.user_active()):
                    await asyncio.sleep(0.04)
                if turn != self.turn:
                    continue
                self.device.play(turn, samples, text)
                if self.device.stream is None:  # no speaker: show the words instead
                    self._started(turn, text)
                else:
                    self.playing = True
            except Exception:
                log.exception("tts failed for %r", text)
            finally:
                self.tts_pending = max(0, self.tts_pending - 1)
                self.update()

    def _on_play(self, event: str, turn: int, text: str):
        """From the sound card: a sentence started, or everything queued has played."""
        if event == "start" and turn == self.turn:
            self.playing = True
            self._started(turn, text)
        elif event == "idle":
            self.playing = self.device.busy  # a stale "done" from a cut-off turn must not end this one
            self.played_end = time.monotonic()
        self.update()

    def mark(self, stage: str, turn: int | None = None):
        """Timestamp a stage of the current request (the first time it happens)."""
        t = self.timing
        if turn is not None and t.get("turn") != turn:
            return
        t.setdefault(stage, time.monotonic())
        if stage == "first_audio" and "speech_end" in t:
            order = ["speech_end", "endpoint", "stt", "send", "first_token", "first_chunk", "tts", "first_audio"]
            seen = [s for s in order if s in t]
            parts = [f"{b} +{t[b] - t[a]:.2f}s" for a, b in zip(seen, seen[1:])]
            total = t["first_audio"] - t["speech_end"]
            log.info("latency: %.2fs from end of speech to first word (%s)", total, ", ".join(parts))
            self.last_timing = {**t, "total": total}
            self.broadcast({"type": "latency", "total": round(total, 2),
                            "stages": {b: round(t[b] - t[a], 2) for a, b in zip(seen, seen[1:])}})

    def _started(self, turn: int, text: str):
        self.mark("first_audio", turn)
        self.said.setdefault(turn, []).append(text)
        if len(self.said) > 50:
            del self.said[min(self.said)]
        self.recent_said.append((time.monotonic(), text))
        if self.draft and self.draft.get("turn") == turn:
            self.draft["answered"] = True  # what I say next is a new request, not a continuation
        self.broadcast({"type": "caption", "text": text, "turn": turn})

    # ---- listening -----------------------------------------------------------------------

    def _reset_ears(self):
        self.spec = None  # {"n": frames covered, "task": transcription} started at the early mark
        self.in_speech = False
        self.over_voice = False
        self.frames: list[np.ndarray] = []
        self.hot = 0
        self.quiet = 0
        self.voiced = 0

    def _listen(self):
        if self.device:
            self.device.set_input(self.call or self.ptt)

    def on_mic(self, pcm: np.ndarray):
        if self.muted or not (self.call or self.ptt) or not self.enabled:
            self.mic_buf = pcm[:0]
            return
        self.mic_buf = np.concatenate([self.mic_buf, pcm])
        while len(self.mic_buf) >= FRAME:
            frame, self.mic_buf = self.mic_buf[:FRAME], self.mic_buf[FRAME:]
            self._frame(frame)

    def _frame(self, pcm: np.ndarray):
        now = time.monotonic()
        self.preroll.append(pcm)  # always: the opening words come from here, PTT and barge-in too
        if self.ptt:
            self.frames.append(pcm)
            return
        if self.settings["input"] == "ptt":
            return
        x = pcm.astype(np.float32) / 32768
        p = self.vad(x)
        rms = float(np.sqrt(np.mean(x * x)))
        # While its own voice (or music) is in the room, and a moment after, the echo it should leave
        # in the mic sets a floor: only a voice clearly louder than that counts as me. The ratio
        # follows quiet stretches down quickly and creeps up slowly, so my talking doesn't teach it.
        level = getattr(self.device, "total_level", 0.0)
        self.out_env += (level - self.out_env) * 0.3
        audible = self.playing or now - self.played_end < TAIL or self.out_env > 0.01
        if audible and not self.in_speech and self.hot == 0 and self.out_env > 0.005:
            r = rms / self.out_env
            self.echo_ratio += (r - self.echo_ratio) * (0.1 if r < self.echo_ratio else 0.01)
        floor = max(0.004, 2.5 * self.echo_ratio * self.out_env) if audible else 0.0
        voice = p >= (0.7 if audible else 0.5) and rms >= floor
        if not self.in_speech:
            self.hot = self.hot + 1 if voice else max(0, self.hot - 2)
            if self.hot < (5 if audible else 3):
                if self.hot == 2:
                    self.update()  # "maybe me": hold new sentences back and duck the music
                return
            if audible and not self.settings["barge_in"]:
                self.hot = 0
                return
            self.in_speech, self.over_voice = True, audible
            self.frames, self.quiet, self.voiced = list(self.preroll), 0, self.hot
            self.partial_at = now
            self._barge_in()
            self.update()
            return
        self.frames.append(pcm)
        if p < 0.35:
            self.quiet += 1
        else:
            self.quiet = 0
            self.voiced += p >= 0.5
            self.spec = None  # I went on talking: the early guess is stale
        if self.quiet * FRAME_MS >= EARLY_MS and self.spec is None and self.voiced >= 8:
            n = max(1, len(self.frames) - self.quiet + 6)
            self.spec = {"n": n, "at": now, "task": asyncio.create_task(
                stt.transcribe(np.concatenate(self.frames[:n]), self.settings["stt_model"]))}
        early = self.spec and self.spec["task"].done() and not self.spec["task"].exception()
        if early:
            text = self.spec["task"].result()
            if not (text and FINISHED.search(text) and not DANGLING.search(text)):
                early = False
        if (len(self.frames) * FRAME_MS >= 1200 and now - self.partial_at >= PARTIAL_EVERY
                and self.partial_task is None):
            self.partial_at = now
            self.partial_task = asyncio.create_task(self._partial(np.concatenate(self.frames)))
        if early or self.quiet * FRAME_MS >= self.settings["endpoint_ms"] or len(self.frames) >= MAX_UTTERANCE:
            frames = self.frames[: max(1, len(self.frames) - self.quiet + 6)]
            enough = self.voiced >= 8  # about a quarter second of real speech
            over = self.over_voice
            # the early transcription covers exactly these frames when I stayed quiet since
            spec = self.spec["task"] if self.spec and self.spec["n"] == len(frames) else None
            self.timing = {"speech_end": now - self.quiet * FRAME_MS / 1000, "endpoint": now}
            self._reset_ears()
            self.heard_end = now
            self.update()
            asyncio.create_task(self._utterance(np.concatenate(frames), enough, over, spec))

    def _barge_in(self):
        """I started talking. Whatever the assistant had going holds still until we know whether
        I really said something (then it's cut) or it was a cough or its own echo (then it resumes)."""
        if self.dispatch:
            self.dispatch.cancel()  # a request waiting for its end: my new words may finish it
            self.dispatch = None
        if self.engaged() and not self.hold:
            self.hold = True
            if self.device:
                self.device.pause()

    def ptt_start(self):
        if self.ptt or not self.enabled:
            return
        self._barge_in()
        self._reset_ears()
        self.frames = list(self.preroll)[-6:]  # the key often goes down a beat after I start
        self.ptt = True
        self._listen()
        self.broadcast({"type": "ptt", "down": True})
        self.update()

    def ptt_stop(self):
        if not self.ptt:
            return
        self.ptt = False
        frames = self.frames
        self._reset_ears()
        self.heard_end = time.monotonic()
        self._listen()
        self.broadcast({"type": "ptt", "down": False})
        self.update()
        if len(frames) * FRAME_MS >= 300:
            asyncio.create_task(self._utterance(np.concatenate(frames), True, False))
        else:
            self._resume()

    async def _partial(self, pcm: np.ndarray):
        """My words so far, while I'm still talking, for the transcript and the HUD."""
        try:
            text = await stt.transcribe(pcm, self.settings["stt_model"])
        except Exception:
            text = ""
        finally:
            self.partial_task = None
        if text and self.in_speech:
            self.broadcast({"type": "partial", "text": text})

    async def _utterance(self, pcm: np.ndarray, enough: bool, over_voice: bool, spec=None):
        text = ""
        if enough:
            self.transcribing += 1
            self.update()
            try:
                text = await (spec if spec is not None else stt.transcribe(pcm, self.settings["stt_model"]))
                self.mark("stt")
            except Exception as e:
                log.warning("transcription failed: %s", e)
                self.log("system", f"Transcription failed: {e}")
            finally:
                self.transcribing -= 1
                self.update()
        if text and over_voice and self._echo(text):
            log.info("ignored my own voice: %r", text)
            text = ""
        if not text:
            self.broadcast({"type": "partial", "text": ""})
            self._resume()  # a cough, a click or its own echo: carry on where it stopped
            return
        await self.handle_text(text)

    def _echo(self, text: str) -> bool:
        """Is this transcript just the assistant's own words coming back through the mic?"""
        now = time.monotonic()
        recent = [t for at, t in self.recent_said if now - at < 20]
        if not recent:
            return False
        norm = lambda s: re.sub(r"[^a-z0-9 ]", "", s.lower()).split()
        heard = " ".join(norm(text))
        said = " ".join(w for t in recent for w in norm(t))
        if len(heard.split()) < 3:
            return False
        if heard in said:
            return True
        return any(difflib.SequenceMatcher(None, heard, " ".join(norm(t))).ratio() > 0.75 for t in recent[-4:])

    def _resume(self):
        if self.hold:
            self.hold = False
            if self.device:
                self.device.resume()
        d = self.draft
        if d and d.get("turn") is None and not self.dispatch:
            self._schedule(0.3)  # the request that was waiting for its end goes out after all
        self.update()

    # ---- conversation --------------------------------------------------------------------

    async def handle_text(self, text: str, typed: bool = False):
        text = text.strip()
        if not text:
            return
        self.log("user", text, typed=typed)
        self.broadcast({"type": "heard", "text": text, "typed": typed})
        low = text.lower().strip(" .!?,")
        if self.approval:
            # the brain's turn is waiting on this answer, so stop the question without moving on
            self._hush()
            self._answer_by_voice(text, low)
            return
        if HUSH.match(low):
            self._cut()
            self.draft = None
            await self.brain.interrupt()
            return
        now = time.monotonic()
        d = self.draft
        if not typed and d and not d["answered"] and now - d["at"] < CONTINUE_S:
            # I was still finishing the same request: one request, not two replies
            d["text"] = f"{d['text']} {text}"
            d["at"], d["turn"] = now, None
        else:
            self.draft = d = {"text": text, "at": now, "turn": None, "answered": False}
        self._cut()
        if self.brain.busy:
            await self.brain.interrupt()
        if not typed and DANGLING.search(text):
            self._schedule(DANGLE_S)  # it trails off ("... and"): give me a moment to go on
        else:
            self._send()

    def _schedule(self, delay: float):
        async def later():
            await asyncio.sleep(delay)
            if self.user_active():
                return  # still talking; the next utterance merges or resumes this
            self.dispatch = None
            self._send()
        if self.dispatch:
            self.dispatch.cancel()
        self.dispatch = asyncio.create_task(later())
        self.update()

    def _send(self):
        d = self.draft
        if not d or d["turn"] is not None:
            return
        self.dispatch = None
        d["turn"] = self.turn
        self.mark("send")
        self.timing["turn"] = self.turn
        asyncio.create_task(self._run_turn(d["text"], self.turn))

    def _cut(self):
        """Move on from whatever the assistant was doing. A reply already partly spoken (or written)
        gets marked as cut off in the transcript, and nothing more of it is shown or said."""
        old = self.turn
        busy = self.hold or self.playing or self.tts_pending or self.thinking or (self.device and self.device.busy)
        self.new_turn()
        if not busy:
            return
        marked = False
        for e in self.history:
            if e.get("turn") == old and e["role"] == "assistant":
                e["cut"] = marked = True
        if not marked and self.said.get(old):
            self.log("assistant", " ".join(self.said[old]), turn=old, cut=True)
        if marked or self.said.get(old):
            self.broadcast({"type": "cut", "turn": old})

    def _hush(self):
        """Stop the audio of the current turn (and anything held or queued) but keep the turn."""
        self.hold = False
        while not self.tts_q.empty():
            self.tts_q.get_nowait()
            self.tts_pending -= 1
        if self.device:
            self.device.stop()
        self.playing = False
        self.update()

    def reply(self, turn: int, text: str):
        """The brain's finished text for a turn. A turn I cut off stays cut: its late text is dropped."""
        if turn != self.turn:
            return
        self.log("assistant", text, turn=turn)

    async def _run_turn(self, text: str, turn: int):
        self.thinking = True
        self.update()
        try:
            await self.brain.turn(text, turn)
        finally:
            self.thinking = self.brain.busy
            # Answered once I've heard some of it (see _started), or it finished and nothing of it
            # is being held back while I talk. A reply held during my interjection was never heard,
            # so what I'm saying still extends this request.
            if self.draft and self.draft.get("turn") == turn and not self.hold:
                self.draft["answered"] = True
            self.update()

    async def interrupt(self):
        self._cut()
        self.draft = None
        await self.brain.interrupt()

    # ---- calls ---------------------------------------------------------------------------

    async def start_call(self, quiet: bool = False):
        if self.call:
            return
        if not self.enabled:
            self.toast("Voice is off. Turn it on to talk.")
            return
        self.call, self.call_started, self.muted = True, time.time(), False
        self.vad.reset()
        self._reset_ears()
        self._listen()
        if self.device and self.device.error:
            self.log("system", f"No microphone: {self.device.error}")
        self.broadcast({"type": "call", "active": True, "started": self.call_started})
        self.broadcast({"type": "muted", "value": False})
        self.new_turn()
        if quiet:
            return
        hello = tower.greeting(self.fleet)
        self.log("assistant", hello, turn=self.turn)
        self.say(hello)

    async def end_call(self):
        if not self.call:
            return
        self.call = False
        self.ptt = False
        self._reset_ears()
        if self.dispatch:
            self.dispatch.cancel()
            self.dispatch = None
        self.new_turn()  # hang up: the current answer keeps going, silently, into the transcript
        self._listen()
        self._resolve_approval("deny", "The call ended before I answered.")
        self.announcements.clear()
        self.broadcast({"type": "call", "active": False, "started": 0})
        self.update()

    async def toggle_call(self):
        await (self.end_call() if self.call else self.start_call())

    def set_muted(self, value: bool):
        self.muted = value
        self._reset_ears()
        self.broadcast({"type": "muted", "value": value})
        self.update()

    # ---- approvals -----------------------------------------------------------------------

    async def permit(self, tool: str, inp: dict, ctx):
        if policy.decide(tool, inp, self.settings["autonomy"], self.always) == "allow":
            return PermissionResultAllow()
        title, spoken = policy.describe(tool, inp)
        key = policy.always_key(tool, inp)
        fut = asyncio.get_running_loop().create_future()
        self.approval = {"id": uuid.uuid4().hex[:8], "tool": tool, "title": title,
                         "detail": policy.detail(tool, inp), "fut": fut}
        self.broadcast({"type": "approval", "approval": self._approval_view()})
        self.log("approval", title)
        self.say(f"Okay to {spoken}?")
        self.update()
        try:
            decision, note = await fut
        finally:
            self.approval = None
            self.broadcast({"type": "approval", "approval": None})
            self.update()
        if decision == "always":
            self.always.add(key)
            decision = "allow"
        self.log("approval", f"{'allowed' if decision == 'allow' else 'denied'}: {title}")
        if decision == "allow":
            return PermissionResultAllow()
        return PermissionResultDeny(message=note or "I said no.")

    def _approval_view(self):
        if not self.approval:
            return None
        return {k: self.approval[k] for k in ("id", "tool", "title", "detail")}

    def _resolve_approval(self, decision: str, note: str = "", id: str | None = None):
        a = self.approval
        if not a or (id and a["id"] != id) or a["fut"].done():
            return
        a["fut"].set_result((decision, note))

    def _answer_by_voice(self, text: str, low: str):
        if re.search(r"\balways\b", low):
            self._resolve_approval("always")
        elif YES.match(low):
            self._resolve_approval("allow")
        elif NO.match(low):
            self._resolve_approval("deny", "I said no.")
        else:
            self._resolve_approval("deny", f"Not approved. Instead I said: {text}")

    # ---- fleet ---------------------------------------------------------------------------

    async def _on_fleet(self, items, events, fingerprint):
        self.fleet = items
        if fingerprint != self.fleet_print:
            self.fleet_print = fingerprint
            self.broadcast({"type": "fleet", "agents": tower.view(items)})
        for kind, a in events:
            name = tower.say_name(a["name"])
            text = {"finished": f"{name} finished.", "waiting": f"{name} needs you.",
                    "new": f"{name} is up.", "gone": f"{name} closed."}[kind]
            self.toast(text, kind)
            self.log("event", text)
            self.brain.notes.append(text)
            del self.brain.notes[:-12]
            if kind in ("finished", "waiting") and self.call and self.settings["announce"]:
                self.announcements.append(text)
        self._flush_announcements()

    def _flush_announcements(self):
        """Fleet news waits for a real lull: not while either of us talks, not while a reply is
        coming, and not right after I stopped (I may be about to go on)."""
        if not self.enabled:
            self.announcements.clear()
        quiet = time.monotonic() - max(self.heard_end, self.played_end) > 1.5
        if self.announcements and self.phase == "listening" and quiet and not self.user_active() and not self.engaged():
            text = " ".join(self.announcements[-3:])
            self.announcements.clear()
            self.say(text)

    # ---- messages from windows -----------------------------------------------------------

    async def on_message(self, msg: dict, ws):
        kind = msg.get("type")
        if kind == "text":
            await self.handle_text(str(msg.get("text", ""))[:4000], typed=True)
        elif kind == "call":
            action = msg.get("action")
            if action == "start":
                await self.start_call(quiet=bool(msg.get("quiet")))
            elif action == "end":
                await self.end_call()
            else:
                await self.toggle_call()
        elif kind == "ptt":
            if msg.get("down"):
                self.ptt_start()
            else:
                self.ptt_stop()
        elif kind == "mute":
            self.set_muted(bool(msg.get("value")))
        elif kind == "interrupt":
            await self.interrupt()
        elif kind == "approve":
            self._resolve_approval(msg.get("decision", "deny"), "", msg.get("id"))
        elif kind == "settings":
            await self._patch_settings(msg.get("patch") or {})
        elif kind == "reset":
            self.new_turn()
            await self.brain.reset()
            self.always.clear()
            self.history.clear()
            self.broadcast({"type": "history", "history": []})
            self.toast("New conversation")
        elif kind == "announce":
            # a desktop notification the pet wants read out: said at the next lull, only in a call
            text = str(msg.get("text", "")).strip()
            if text and self.call and self.settings["announce"]:
                self.announcements.append(text)
                del self.announcements[:-3]
        elif kind == "voice":
            on = not self.enabled if msg.get("action") == "toggle" else bool(msg.get("on"))
            await self._patch_settings({"enabled": on})
        elif kind == "preview":
            self.new_turn()
            self.say(f"This is {self.settings['name']}. This is how I sound.")
        elif kind == "music":
            action = msg.get("action", "")
            if action == "play" and msg.get("query"):
                self.toast(await self.music.play(str(msg["query"])[:200]))
            else:
                await self.music.control(action)
        elif kind == "memory":
            if msg.get("action") == "forget" and self.memory.remove(str(msg.get("id", ""))):
                self.memory_changed()
            elif msg.get("action") == "clear":
                self.memory.clear()
                self.memory_changed()
        elif kind == "client_error":
            log.warning("window error: %s", str(msg.get("message", ""))[:2000])
        elif kind == "agent" and msg.get("action") == "show":
            await tower.run("jump", str(msg.get("pane", "")))

    async def set_voice(self, on: bool | None = None):
        """On, off, or (None) the other way round. From the panel, the pet, the menu and the hotkey."""
        await self._patch_settings({"enabled": (not self.enabled) if on is None else on})

    async def _voice_switched(self):
        if not self.enabled:
            # stop everything I hear and say; a reply already in progress finishes silently
            if self.dispatch:
                self.dispatch.cancel()
                self.dispatch = None
            self.draft = None
            await self.end_call()
            self.ptt = False
            self._reset_ears()
            self.new_turn()
            self._listen()
            self.announcements.clear()
        self.toast("Voice on" if self.enabled else "Voice off: not listening, not speaking")
        self.update()

    async def _patch_settings(self, patch: dict):
        applied = self.settings.patch(patch)
        if not applied:
            return
        self.broadcast({"type": "settings", "settings": dict(self.settings)})
        if "model" in applied:
            await self.brain.set_model(applied["model"])
            self.toast(f"Model: {applied['model']}")
        if "name" in applied or "memory" in applied:
            await self.brain.restart()  # the system prompt carries both
        if "enabled" in applied:
            await self._voice_switched()
        if {"input_device", "output_device"} & applied.keys() and self.device:
            self.device._close()
            self.device.reconcile()
