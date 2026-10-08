"""Simulated conversations against the real hub: real Silero VAD, real synthesized speech on the
"mic", a fake speaker that plays in real time, a fake brain and scripted transcripts.

    uv run python tests/sim_turns.py

Each scenario prints what happened and PASS or FAIL. Nothing touches the sound card, Claude or tower.
"""

import asyncio
import os
import sys
import tempfile
import time
from collections import deque

os.environ.setdefault("XDG_CONFIG_HOME", tempfile.mkdtemp())  # default settings, not mine
os.environ.setdefault("XDG_DATA_HOME", tempfile.mkdtemp())
os.environ.setdefault("CLAUDEBOT_VOICE_RUNTIME", tempfile.mkdtemp())

import numpy as np  # noqa: E402
from scipy import signal  # noqa: E402

from claudebot_voice import session, stt  # noqa: E402
from claudebot_voice.tts import TTS  # noqa: E402

FRAME = 512  # 32 ms at 16 kHz
tts = TTS()


def speech16k(text: str, voice: str) -> np.ndarray:
    pcm = np.frombuffer(tts.synth(text, voice, 1.0), dtype="<i2").astype(np.float32) / 32768
    return signal.resample_poly(pcm, 2, 3).astype(np.float32)


class FakeDevice:
    """Plays queued sentences in real time (10 ms ticks) and reports to the hub like the real one."""

    def __init__(self, hub):
        self.hub = hub
        self.queue: deque = deque()
        self.paused = False
        self.stream = object()
        self.duck = False
        self.mic_level = self.out_level = 0.0
        self.error = ""
        self.playing_turn = None
        self.events: list[tuple[float, str]] = []
        self.audible_log: list[tuple[float, bool]] = []
        self.level = 0.1

    @property
    def busy(self):
        return bool(self.queue)

    @property
    def audible(self):
        return bool(self.queue) and not self.paused

    @property
    def total_level(self):
        # what the speaker puts out right now; the feeder sets it from the voice it is playing
        return self.level if self.audible else 0.0

    def play(self, turn, samples, text):
        self.queue.append([turn, len(samples), text, 0])

    def stop(self):
        self.events.append((time.monotonic(), "stop"))
        self.queue.clear()
        self.paused = False
        if self.playing_turn is not None:
            was, self.playing_turn = self.playing_turn, None
            self.hub._on_play("idle", was, "")

    def pause(self):
        self.events.append((time.monotonic(), "pause"))
        self.paused = True
        if self.queue:
            self.queue[0][3] = 0

    def resume(self):
        self.events.append((time.monotonic(), "resume"))
        self.paused = False

    def set_input(self, on):
        pass

    def reconcile(self):
        pass

    def close(self):
        pass

    async def run(self):
        while True:
            await asyncio.sleep(0.01)
            self.audible_log.append((time.monotonic(), self.audible))
            if self.paused or not self.queue:
                continue
            item = self.queue[0]
            if item[3] == 0:
                self.playing_turn = item[0]
                self.hub._on_play("start", item[0], item[2])
            item[3] += 480
            if item[3] >= item[1]:
                self.queue.popleft()
                if not self.queue:
                    was, self.playing_turn = self.playing_turn, None
                    self.hub._on_play("idle", was, "")


class FakeBrain:
    """Thinks for a moment, then speaks a few sentences. Interrupt ends it early."""

    def __init__(self, hub, think=0.8):
        self.hub = hub
        self.think = think
        self.busy = False
        self.client = object()
        self.turns: list[tuple[int, str]] = []
        self.stop = False
        self.notes: list[str] = []
        self.script = ["Here is a fairly long answer to that.", "It goes on for a while so you can cut in.",
                       "And then it keeps going a little longer."]

    async def turn(self, text, turn_id):
        self.turns.append((turn_id, text))
        self.busy, self.stop = True, False
        try:
            t0 = time.monotonic()
            while time.monotonic() - t0 < self.think:
                if self.stop:
                    return
                await asyncio.sleep(0.02)
            for line in self.script:
                if self.stop:
                    return
                self.hub.say(line, turn_id)
                await asyncio.sleep(0.05)
            self.hub.reply(turn_id, " ".join(self.script))
        finally:
            self.busy = False

    async def interrupt(self):
        if self.busy:
            self.stop = True

    async def close(self):
        pass


class Sim:
    def __init__(self, think=0.8):
        self.hub = hub = session.Hub()
        hub.tts = tts
        hub.device = FakeDevice(hub)
        hub.brain = FakeBrain(hub, think)
        hub.call = True
        hub.settings["barge_in"] = True
        self.transcripts: deque = deque()
        self.messages: list[dict] = []
        hub.broadcast = lambda m: self.messages.append({**m, "_t": time.monotonic()})

        async def fake_transcribe(pcm, model=""):
            # Like real speech to text: the words are whatever was said in the audio it gets. The
            # audio ends (give or take the trailing frames) when the call is made.
            t, dur = time.monotonic(), len(pcm) / 16000
            self.finals.append(dur)
            if hub.in_speech:
                self.partials += 1
            await asyncio.sleep(0.2)
            heard = [text for start, end, text in self.clips if start < t and end > t - dur - 0.2]
            if heard:
                return " ".join(h for h in heard if h)
            return self.transcripts.popleft() if self.transcripts else ""

        stt.transcribe = fake_transcribe
        self.mic: deque = deque()  # (start time, audio) to play into the mic
        self.echo = None  # the assistant's own voice, leaking back at this gain while it plays
        self.echo_gain = 0.0
        self.user_onsets: list[float] = []
        self.partials = 0
        self.clips: list[tuple[float, float, str]] = []  # what I said, when, for the fake transcriber
        self.finals: list[float] = []  # seconds of audio handed to the transcriber per utterance
        self.ducked: list[tuple[float, bool]] = []

    async def start(self):
        h = self.hub
        self.tasks = [asyncio.create_task(h._tts_worker()), asyncio.create_task(h.device.run()),
                      asyncio.create_task(h._ticker()), asyncio.create_task(self._feed())]

    def stop(self):
        for t in self.tasks:
            t.cancel()

    def say_into_mic(self, audio: np.ndarray, at: float, text: str = ""):
        self.mic.append((time.monotonic() + at, audio))
        voiced = np.flatnonzero(np.abs(audio) > 0.02)
        if len(voiced):
            t0 = time.monotonic() + at
            self.clips.append((t0 + voiced[0] / 16000, t0 + voiced[-1] / 16000, text))
        # synthesized speech starts with a little silence; the onset is the first loud frame
        loud = np.flatnonzero(np.sqrt(np.convolve(audio**2, np.ones(160) / 160, "same")) > 0.02)
        self.user_onsets.append(time.monotonic() + at + (loud[0] / 16000 if len(loud) else 0))

    async def _feed(self):
        """32 ms frames in real time: my voice (when scheduled), its echo, a little room noise."""
        rng = np.random.default_rng(1)
        current, pos, echo_pos = None, 0, 0
        while True:
            t = time.monotonic()
            frame = rng.normal(0, 0.002, FRAME).astype(np.float32)
            if current is None and self.mic and self.mic[0][0] <= t:
                current, pos = self.mic.popleft()[1], 0
            if current is not None:
                chunk = current[pos:pos + FRAME]
                frame[: len(chunk)] += chunk
                pos += FRAME
                if pos >= len(current):
                    current = None
            if self.echo is not None and self.hub.device.audible:
                chunk = self.echo[echo_pos:echo_pos + FRAME]
                if len(chunk) < FRAME:
                    echo_pos, chunk = 0, self.echo[:FRAME]
                frame[: len(chunk)] += chunk * self.echo_gain
                self.hub.device.level = float(np.sqrt(np.mean(chunk**2)))  # what the speaker played
                echo_pos += FRAME
            self.hub.on_mic(np.clip(frame * 32767, -32768, 32767).astype(np.int16))
            await asyncio.sleep(max(0, t + 0.032 - time.monotonic()))

    def overlap(self) -> float:
        """Seconds the assistant was audible while I was mid-utterance (phase 'hearing')."""
        hearing, last, total = False, None, 0.0
        phases = [(m["_t"], m["phase"]) for m in self.messages if m["type"] == "phase"]
        for t, audible in self.hub.device.audible_log:
            while phases and phases[0][0] <= t:
                hearing = phases.pop(0)[1] == "hearing"
            if hearing and audible and last is not None:
                total += t - last
            last = t
        return total

    def kinds(self, kind):
        return [m for m in self.messages if m["type"] == kind]


async def wait_until(cond, timeout=15.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if cond():
            return True
        await asyncio.sleep(0.05)
    return False


RESULTS = []


def check(name, ok, detail=""):
    ok = bool(ok)
    RESULTS.append(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{('  (' + detail + ')') if detail else ''}")


async def barge_in(me, bot):
    print("1. I talk over a long reply")
    s = Sim()
    await s.start()
    await s.hub.handle_text("Tell me a long story.", typed=True)
    await wait_until(lambda: s.hub.playing)
    played_at = time.monotonic()
    s.say_into_mic(me, at=0.6, text="Actually, what time is it?")
    await wait_until(lambda: len(s.hub.brain.turns) == 2)
    await wait_until(lambda: not s.hub.engaged() and not s.hub.thinking, 12)
    pauses = [t for t, e in s.hub.device.events if e == "pause"]
    onset = s.user_onsets[0]
    lag = (pauses[0] - onset) if pauses else None
    check("the reply pauses as soon as I start", lag is not None and lag < 0.35, f"{lag:.2f}s after onset" if lag else "no pause")
    check("the old reply is marked cut off", any(m["type"] == "cut" for m in s.messages))
    check("my new question becomes the next turn", s.hub.brain.turns[-1][1] == "Actually, what time is it?", repr(s.hub.brain.turns))
    check("no voice over mine", s.overlap() < 0.1, f"{s.overlap():.2f}s overlap")
    first_words = [m for m in s.messages if m["type"] == "partial" or m["type"] == "heard"]
    check("the reply started before I cut in", played_at < onset)
    voiced = (len(me) - np.flatnonzero(np.abs(me) > 0.02)[0]) / 16000
    check("my first words reach the transcriber", s.finals and max(s.finals) >= voiced,
          f"{max(s.finals) if s.finals else 0:.2f}s sent for {voiced:.2f}s of speech")
    check("my words show up while I'm still talking", s.partials >= 1, f"{s.partials} live transcripts")
    s.stop()


async def false_alarm(cough, uh):
    print("2. A cough, then a short 'uh', during the reply")
    s = Sim()
    await s.start()
    await s.hub.handle_text("Tell me a long story.", typed=True)
    await wait_until(lambda: s.hub.playing)
    s.say_into_mic(cough, at=0.5)
    await asyncio.sleep(1.5)
    ev = [e for _, e in s.hub.device.events]
    check("a cough doesn't even pause it", "pause" not in ev, str(ev))
    s.say_into_mic(uh, at=0.0, text="")  # a murmur the transcriber makes nothing of
    await asyncio.sleep(3.0)
    ev = [e for _, e in s.hub.device.events]
    check("a murmur pauses it, then it resumes", "pause" in ev and "resume" in ev, str(ev))
    check("nothing was cut", not s.kinds("cut"))
    check("still one turn", len(s.hub.brain.turns) == 1)
    s.stop()


async def continuation(part1, part2):
    print("3. I trail off and finish the sentence")
    s = Sim()
    await s.start()
    s.say_into_mic(part1, at=0.2, text="Turn on the lights and")
    s.say_into_mic(part2, at=0.2 + len(part1) / 16000 + 1.35, text="the fan in the bedroom.")  # a long pause mid-thought
    await wait_until(lambda: s.hub.brain.turns, 12)
    await asyncio.sleep(1.0)
    turns = s.hub.brain.turns
    check("one request, merged", len(turns) == 1 and turns[0][1] == "Turn on the lights and the fan in the bedroom.", repr(turns))
    s.stop()


async def continuation_while_thinking(part1, part2):
    print("4. I add to my question while it is thinking")
    s = Sim(think=3.0)
    await s.start()
    s.say_into_mic(part1, at=0.2, text="What's the weather in Lisbon.")
    s.say_into_mic(part2, at=0.2 + len(part1) / 16000 + 2.2, text="And tomorrow too.")
    await wait_until(lambda: len(s.hub.brain.turns) >= 2, 15)
    await wait_until(lambda: not s.hub.engaged() and not s.hub.thinking, 15)
    turns = s.hub.brain.turns
    check("the half question was dropped for the whole one",
          len(turns) == 2 and turns[-1][1] == "What's the weather in Lisbon. And tomorrow too.", repr(turns))
    spoken = [m for m in s.messages if m["type"] == "caption"]
    stale = [m for m in spoken if m["turn"] == turns[0][0]]
    check("only the merged request was answered out loud", not stale and spoken, f"{len(stale)} stale sentences")
    s.stop()


async def echo(bot_voice):
    print("5. Its own voice leaks into the mic")
    s = Sim()
    s.echo, s.echo_gain = bot_voice, 0.08  # residue after echo cancellation, about -22 dB
    await s.start()
    await s.hub.handle_text("Tell me a long story.", typed=True)
    await wait_until(lambda: s.hub.playing)
    await wait_until(lambda: not s.hub.engaged(), 20)
    check("its echo never counted as me", "pause" not in [e for _, e in s.hub.device.events], str(s.hub.device.events))
    s.stop()


async def echo_transcript():
    print("6. Its own words come back as a transcript")
    s = Sim()
    await s.start()
    await s.hub.handle_text("Tell me a long story.", typed=True)
    await wait_until(lambda: len(s.hub.said.get(s.hub.turn, [])) >= 1)
    s.hub.over_voice = True
    s.transcripts.append("Here is a fairly long answer to that.")
    await s.hub._utterance(np.zeros(16000, dtype=np.int16), True, True)
    check("ignored, no new turn", len(s.hub.brain.turns) == 1)
    s.stop()


async def gate(me):
    print("7. A reply is ready while I'm still talking")
    s = Sim(think=0.2)
    await s.start()
    s.hub.draft = {"text": "x", "at": time.monotonic(), "turn": s.hub.turn, "answered": False}
    s.say_into_mic(me, at=0.0)
    await asyncio.sleep(0.6)  # I'm mid-sentence now
    s.hub.say("Something I wanted to tell you.")
    for _ in range(int(len(me) / 16000 / 0.1)):
        s.ducked.append((time.monotonic(), s.hub.device.duck, s.hub.in_speech))
        await asyncio.sleep(0.1)
    await asyncio.sleep(1.5)
    check("nothing played while I talked", s.overlap() < 0.05, f"{s.overlap():.2f}s overlap")
    talking = [d for _, d, sp in s.ducked if sp]
    check("music stays down while I talk", talking and all(talking), f"{sum(talking)}/{len(talking)} samples ducked")
    s.stop()


async def announcement(me):
    print("8. Fleet news arrives while I'm talking")
    s = Sim()
    await s.start()
    s.say_into_mic(me, at=0.0, text="Can you check something for me.")
    await asyncio.sleep(0.5)
    s.hub.announcements.append("tower finished.")
    await asyncio.sleep(len(me) / 16000 + 0.2)
    early = [m for m in s.messages if m["type"] == "caption" and "tower" in m.get("text", "")]
    check("it waits for a lull", not early)
    s.stop()


async def main():
    me = speech16k("Actually, wait, what time is it right now?", "af_heart")
    cough = (np.random.default_rng(3).normal(0, 0.25, 3200) * np.hanning(3200)).astype(np.float32)
    part1 = speech16k("Turn on the lights and", "af_heart")
    part2 = speech16k("the fan in the bedroom.", "af_heart")
    w1 = speech16k("What's the weather in Lisbon.", "af_heart")
    w2 = speech16k("And tomorrow too.", "af_heart")
    bot = speech16k("Here is a fairly long answer to that. It goes on for a while so you can cut in.", "bm_george")
    long_me = speech16k("Let me finish this thought before you say anything at all, please.", "af_heart")
    await barge_in(me, bot)
    await false_alarm(cough, speech16k("Mm hmm, okay.", "af_heart"))
    await continuation(part1, part2)
    await continuation_while_thinking(w1, w2)
    await echo(bot)
    await echo_transcript()
    await gate(long_me)
    await announcement(long_me)
    print(f"\n{sum(RESULTS)}/{len(RESULTS)} passed")
    sys.exit(0 if all(RESULTS) else 1)


if __name__ == "__main__":
    asyncio.run(main())
