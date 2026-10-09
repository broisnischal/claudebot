"""Things I say often enough that they shouldn't wait for the model.

Ending the call, the voice's speed and loudness, answer length, music, the system volume, the
time, "repeat that", "go on", the pet, and my answer to something the coordinator asked. Each one is
matched against the whole utterance, so a longer request that merely starts the same way still goes
to the model. A command runs at once, leaves a task the model is busy with alone, and tells the
model what happened, so the conversation stays in step.
"""

import asyncio
import json
import logging
import re
import time

from .brain import PET_NAMES, PET_WORDS, pc_binary, pet_name
from .speech import Chunker

log = logging.getLogger("claudebot_voice.commands")

LEAD = re.compile(r"^(?:(?:hey|ok|okay|so|um+|uh+|please|jarvis|can you|could you|would you)\s+)+")
TAIL = re.compile(r"(?:\s+(?:please|now|jarvis|for me|thanks|thank you))+$")
# pet words that mean something else on their own ("stop" is hush, "run the tests" isn't the pet)
NOT_PET = {"stop", "run", "search", "read", "type", "think", "build", "hammer", "look", "walk", "sit", "drop",
           "throw", "home", "come back", "relax", "hi", "say hi", "wake up", "spin"}


def norm(text: str) -> str:
    low = re.sub(r"[^\w' ]+", " ", text.lower())
    low = re.sub(r"\s+", " ", low).strip()
    for _ in range(3):
        low = TAIL.sub("", LEAD.sub("", low)).strip()
    return low


_can_record: bool | None = None


async def _pc(*args: str, timeout: float = 15) -> tuple[int, str]:
    pc = pc_binary()
    if not pc:
        return 127, "pc isn't installed"
    proc = await asyncio.create_subprocess_exec(pc, *args, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.kill()
        return 124, "pc timed out"
    return proc.returncode or 0, out.decode(errors="replace").strip()


async def can_record() -> bool:
    """Screen recording came to pc later than the rest; older ones don't have it."""
    global _can_record
    if _can_record is None:
        # `pc help record` exits 0 even without the command; asking for the status tells
        _, out = await _pc("record", "status", timeout=5)
        _can_record = "unknown command" not in out.lower() and "isn't installed" not in out
    return _can_record


async def _wpctl(*args: str) -> bool:
    try:
        proc = await asyncio.create_subprocess_exec("wpctl", *args, stdout=asyncio.subprocess.DEVNULL,
                                                    stderr=asyncio.subprocess.DEVNULL)
        return await proc.wait() == 0
    except FileNotFoundError:
        return False


def _sentences(text: str) -> list[str]:
    c = Chunker()
    return [s.strip() for s in c.feed(text) + c.flush() if s.strip()]


class Commands:
    def __init__(self, hub):
        self.hub = hub
        self.rules = [
            (r"(?:hang up|end (?:the )?call|stop listening|bye|good ?bye|that'?s all|that will be all)", self.hang_up),
            (r"mute (?:yourself|the mic(?:rophone)?|my mic(?:rophone)?)", self.mute),
            (r"(?:talk|speak) (?:a (?:bit|little) )?(slower|faster)|(slower|faster)", self.speed),
            (r"(?:speak|talk) (up|louder|quieter|softer|more quietly)", self.voice_volume),
            (r"(?:give me |use )?(longer|shorter|more detailed|briefer) (?:answers|replies)", self.length),
            (r"(?:pause|stop|resume|unpause)(?: the)? (?:music|song)|pause|resume|unpause|keep playing", self.music_pause),
            (r"(?:play the )?(next|previous)(?: song| track| one)?|skip(?: this)?(?: song| track)?", self.music_step),
            (r"(?:turn (?:it|the volume|the sound) |volume |turn it )(up|down)|(louder|quieter)|(?:a bit )?(louder|quieter)", self.volume),
            (r"what(?: is|'s|s)? the time|what time is it", self.time),
            (r"what(?: is|'s|s)? (?:the )?(?:date|day)(?: today)?|what day is it|what is today'?s date", self.date),
            (r"repeat(?: that| it)?|say (?:that|it) again|what did you (?:just )?say|come again|pardon", self.repeat),
            (r"go on|tell me more|keep going|and then|continue|more", self.go_on),
            (r"(?:yes |yeah |ok |okay )?(?:approve(?: it| that)?|allow it|let it(?: run| go ahead)?)", self.approve),
            (r"(?:no |nope )?(?:deny(?: it| that)?|reject(?: it| that)?|don'?t (?:let it|allow it)|block it)", self.deny),
            (r"(?:turn (?:the )?voice off|voice off|go quiet)", self.voice_off),
            (r"(?:start|begin) (?:a |the )?(?:screen )?recording|record (?:my |the )?screen", self.record_start),
            (r"(?:stop|end|finish) (?:the )?(?:screen )?recording", self.record_stop),
            (r"record (?:my |the )?screen for (\d+|a|one|two|three|five|ten|thirty) (seconds?|minutes?)", self.record_for),
        ]
        self.rules = [(re.compile(p), fn) for p, fn in self.rules]

    async def handle(self, text: str) -> bool:
        """Run a command if the utterance is one. True when it was handled."""
        low = norm(text)
        if not low:
            return False
        for pattern, fn in self.rules:
            m = pattern.fullmatch(low)
            if m:
                out = await fn(m)
                if out is not None:
                    self._done(text, *out)
                    return True
        name = self._pet(low)
        if name:
            self.hub.broadcast({"type": "pet", "action": name})
            self._done(text, "", f"the pet did {name}")
            return True
        return False

    def _done(self, text: str, say: str, did: str):
        hub = self.hub
        if say:
            hub._cut()  # a spoken answer takes the floor; a silent action leaves the reply going
            hub.log("assistant", say, turn=hub.turn, local=True)
            hub.say(say)
        record = f' and was answered "{say}"' if say else ""
        hub.brain.notes.append(f'(for the record, no reply needed: I said "{text.strip()}"{record}; {did})')
        del hub.brain.notes[:-12]
        end = hub.timing.get("speech_end")
        if end:
            log.info("latency: %.2fs from end of speech to a local command (%s)", time.monotonic() - end, did)

    # ---- the call and the voice ----

    async def hang_up(self, m):
        if not self.hub.call:
            return None
        await self.hub.end_call()
        return "", "ended the call"

    async def mute(self, m):
        self.hub.set_muted(True)
        return "", "muted the mic"

    async def speed(self, m):
        slower = "slower" in m.group(0)
        await self.hub._patch_settings({"speed": round(self.hub.settings["speed"] + (-0.1 if slower else 0.1), 2)})
        return "Like this?", f"voice speed set to {self.hub.settings['speed']}"

    async def voice_volume(self, m):
        down = m.group(1) in ("quieter", "softer", "more quietly")
        await self.hub._patch_settings({"volume": round(self.hub.settings["volume"] + (-0.1 if down else 0.1), 2)})
        return "Like this?", f"voice volume set to {self.hub.settings['volume']}"

    async def length(self, m):
        longer = m.group(1) in ("longer", "more detailed")
        await self.hub._patch_settings({"sentences": self.hub.settings.get("sentences", 1) + (1 if longer else -1)})
        n = self.hub.settings.get("sentences", 1)
        return "Okay.", f"answers now up to {n} sentence{'s' if n > 1 else ''}"

    async def voice_off(self, m):
        await self.hub._patch_settings({"enabled": False})
        return "", "turned the voice off"

    # ---- music and volume ----

    async def music_pause(self, m):
        music = self.hub.music
        st = music.state()
        if not (st["playing"] or st["paused"]):
            return None
        words = m.group(0)
        if "stop" in words and "music" in words:
            return "", await music.control("stop")
        action = "pause" if "pause" in words and "unpause" not in words else "resume"
        return "", await music.control(action)

    async def music_step(self, m):
        st = self.hub.music.state()
        if not (st["playing"] or st["paused"]):
            return None
        action = "previous" if m.group(1) == "previous" else "next"
        return "", await self.hub.music.control(action)

    async def volume(self, m):
        up = "up" in m.groups() or "louder" in m.groups()
        ok = await _wpctl("set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", "10%+" if up else "10%-")
        return ("", f"turned the system volume {'up' if up else 'down'}") if ok else None

    # ---- answers ----

    async def time(self, m):
        return f"It's {time.strftime('%-I:%M %p').lower().replace('am', 'a m').replace('pm', 'p m')}.", "told the time"

    async def date(self, m):
        return f"It's {time.strftime('%A, %-d %B')}.", "told the date"

    def _last_reply(self) -> dict | None:
        return next((e for e in reversed(self.hub.history) if e["role"] == "assistant" and not e.get("local")), None)

    async def repeat(self, m):
        hub = self.hub
        e = self._last_reply()
        if not e:
            return None
        said = hub.said.get(e.get("turn"), [])
        return (" ".join(said) or _sentences(e["text"])[0]), "repeated the last answer"

    async def go_on(self, m):
        hub = self.hub
        if hub.hold:
            hub._resume()
            return "", "went on with the paused answer"
        e = self._last_reply()
        if not e:
            return None
        said = {s.strip() for s in hub.said.get(e.get("turn"), [])}
        rest = [s for s in _sentences(e["text"]) if s not in said]
        if not rest:
            return None  # nothing left of it: "continue" probably means a task, the model's call
        more = " ".join(rest[:2])
        hub.said.setdefault(e.get("turn"), []).extend(rest[:2])
        return more, "said more of the last answer"

    # ---- screen recording (pc record) ----

    async def record_start(self, m):
        if not await can_record():
            return None
        rc, out = await _pc("record", "start", "--json")
        if rc:
            return f"I couldn't start recording: {out[:120]}", "failed to start a screen recording"
        path = _field(out, "path")
        return "Recording.", f"started a screen recording to {path}"

    async def record_stop(self, m):
        if not await can_record():
            return None
        rc, out = await _pc("record", "stop", "--json")
        if rc:
            return "Nothing is recording.", "found no recording to stop"
        secs = _field(out, "duration") or _field(out, "seconds")
        said = f"Saved, {round(float(secs))} seconds." if _number(secs) else "Saved."
        return said, (f"stopped the recording; video {_field(out, 'path')}, frames {_field(out, 'sheet')}")

    async def record_for(self, m):
        if not await can_record():
            return None
        words = {"a": 1, "one": 1, "two": 2, "three": 3, "five": 5, "ten": 10, "thirty": 30}
        n = int(m.group(1)) if m.group(1).isdigit() else words[m.group(1)]
        seconds = n * (60 if m.group(2).startswith("minute") else 1)
        hub = self.hub

        async def run():
            rc, out = await _pc("record", f"{seconds}s", "--json", timeout=seconds + 60)
            if rc:
                hub.toast(f"Recording failed: {out[:120]}", "error")
                return
            hub.toast(f"Recording saved: {_field(out, 'path')}")
            hub.brain.notes.append(f"(the {seconds}-second screen recording I asked for is saved at {_field(out, 'path')}, "
                                   f"frames at {_field(out, 'sheet')})")
        asyncio.create_task(run())
        return f"Recording for {seconds} seconds.", f"started a {seconds}-second screen recording"

    # ---- the coordinator ----

    def _one_pending(self) -> dict | None:
        pending = list(self.hub.coordinator.pending.values())
        return pending[0] if len(pending) == 1 else None

    async def approve(self, m):
        p = self._one_pending()
        if not p:
            return None
        out = await self.hub.coordinator.resolve(p["pane"], "approve")
        return out, f"approved what {p['agent']} was waiting on"

    async def deny(self, m):
        p = self._one_pending()
        if not p:
            return None
        out = await self.hub.coordinator.resolve(p["pane"], "deny")
        return out, f"denied what {p['agent']} was waiting on"

    # ---- the pet ----

    def _pet(self, low: str) -> str | None:
        low = re.sub(r"^(?:(?:make )?(?:the )?(?:pet|bot|claude bot) |do (?:a |the )?)", "", low).strip()
        if low in NOT_PET or not (low in PET_NAMES or low in PET_WORDS or low.startswith(("peek", "go to the"))):
            return None
        return pet_name(low)


def _field(out: str, key: str) -> str:
    """A field from pc's --json output, or "" when it isn't there."""
    try:
        return str(json.loads(out).get(key, "") or "")
    except (ValueError, AttributeError):
        return ""


def _number(v: str) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False
