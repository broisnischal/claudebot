"""The hub: one conversation shared by the pet and the panel.

Mic audio arrives from the sound card as 16 kHz PCM, already echo cancelled (audio.py). Silero VAD
cuts it into utterances, voxtype turns them into text, the brain answers, and Kokoro speaks each
sentence as soon as it is complete. Speaking over the assistant cuts it off. Windows only watch and
send commands; none of them touches audio.
"""

import asyncio
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
PREROLL = 10  # frames kept from before speech started
MAX_UTTERANCE = int(30_000 / FRAME_MS)
LEVEL_HZ = 20

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
        self._reset_ears()

    # ---- lifecycle -----------------------------------------------------------------------

    async def start(self):
        loop = asyncio.get_running_loop()
        self.device = audio.Device(loop, self.on_mic, self._on_play, self.settings, self.music)
        self.tts = await loop.run_in_executor(self.pool, TTS)
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

    def log(self, role: str, text: str):
        entry = {"role": role, "text": text, "ts": time.time()}
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
            self.device.duck = self.in_speech or self.ptt or self.playing or self.tts_pending > 0
        if phase != self.phase:
            self.phase = phase
            self.broadcast({"type": "phase", "phase": phase})
            if phase == "listening":
                self._flush_announcements()

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
        if self.playing:
            return "speaking"
        if self.thinking or self.tts_pending:
            return "thinking"
        return "muted" if self.muted else "listening"

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
                if turn != self.turn:
                    continue
                self.device.play(turn, samples, text)
                if self.device.stream is None:  # no speaker: show the words instead
                    self.broadcast({"type": "caption", "text": text, "turn": turn})
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
            self.broadcast({"type": "caption", "text": text, "turn": turn})
        elif event == "idle":
            self.playing = self.device.busy  # a stale "done" from a cut-off turn must not end this one
        self.update()

    # ---- listening -----------------------------------------------------------------------

    def _reset_ears(self):
        self.in_speech = False
        self.frames: list[np.ndarray] = []
        self.preroll: deque = deque(maxlen=PREROLL)
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
        if self.ptt:
            self.frames.append(pcm)
            return
        if self.settings["input"] == "ptt":
            return
        p = self.vad(pcm.astype(np.float32) / 32768)
        talking = self.playing or self.tts_pending > 0
        if not self.in_speech:
            self.preroll.append(pcm)
            # while I am talking, demand more confidence so leftover echo does not cut me off
            self.hot = self.hot + 1 if p >= (0.8 if talking else 0.5) else 0
            if self.hot < (8 if talking else 3):
                return
            if talking and not self.settings["barge_in"]:
                self.hot = 0
                return
            self.in_speech, self.frames, self.quiet, self.voiced = True, list(self.preroll), 0, self.hot
            if talking:
                self.new_turn()
            self.update()
            return
        self.frames.append(pcm)
        if p < 0.35:
            self.quiet += 1
        else:
            self.quiet = 0
            self.voiced += p >= 0.5
        if self.quiet * FRAME_MS >= self.settings["endpoint_ms"] or len(self.frames) >= MAX_UTTERANCE:
            frames = self.frames[: max(1, len(self.frames) - self.quiet + 6)]
            enough = self.voiced >= 8  # about a quarter second of real speech
            self._reset_ears()
            self.update()
            if enough:
                asyncio.create_task(self._utterance(np.concatenate(frames)))

    def ptt_start(self):
        if self.ptt or not self.enabled:
            return
        if self.playing or self.tts_pending:
            self.new_turn()
        self._reset_ears()
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
        self._listen()
        self.broadcast({"type": "ptt", "down": False})
        self.update()
        if len(frames) * FRAME_MS >= 300:
            asyncio.create_task(self._utterance(np.concatenate(frames)))

    async def _utterance(self, pcm: np.ndarray):
        self.transcribing += 1
        self.update()
        try:
            text = await stt.transcribe(pcm, self.settings["stt_model"])
        except Exception as e:
            log.warning("transcription failed: %s", e)
            self.log("system", f"Transcription failed: {e}")
            text = ""
        finally:
            self.transcribing -= 1
            self.update()
        if text:
            await self.handle_text(text)

    # ---- conversation --------------------------------------------------------------------

    async def handle_text(self, text: str, typed: bool = False):
        text = text.strip()
        if not text:
            return
        self.log("user", text)
        self.broadcast({"type": "heard", "text": text, "typed": typed})
        low = text.lower().strip(" .!?,")
        if self.approval:
            self._answer_by_voice(text, low)
            return
        if HUSH.match(low):
            self.new_turn()
            await self.brain.interrupt()
            self.say("Okay.")
            return
        turn = self.new_turn()
        if self.brain.busy:
            await self.brain.interrupt()
        asyncio.create_task(self._run_turn(text, turn))

    async def _run_turn(self, text: str, turn: int):
        self.thinking = True
        self.update()
        try:
            await self.brain.turn(text, turn)
        finally:
            self.thinking = self.brain.busy
            self.update()

    async def interrupt(self):
        self.new_turn()
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
        self.log("assistant", hello)
        self.say(hello)

    async def end_call(self):
        if not self.call:
            return
        self.call = False
        self.ptt = False
        self._reset_ears()
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
        if not self.enabled:
            self.announcements.clear()
        if self.announcements and self.phase == "listening":
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
