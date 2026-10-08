"""End of my speech to the first audible word, with the real pieces: Silero VAD, the transcriber,
the Claude session and Kokoro. Only the sound card is fake (it plays in real time) and my voice is
synthesized. Prints the stages for each question.

    uv run python tests/latency.py [--endpoint MS] [--model haiku|sonnet|opus] [--rounds N]
"""

import argparse
import asyncio
import os
import tempfile
import time

os.environ.setdefault("XDG_CONFIG_HOME", tempfile.mkdtemp())
os.environ.setdefault("XDG_DATA_HOME", tempfile.mkdtemp())
os.environ.setdefault("CLAUDEBOT_VOICE_RUNTIME", tempfile.mkdtemp())

import numpy as np  # noqa: E402
from scipy import signal  # noqa: E402

from claudebot_voice import session  # noqa: E402
from claudebot_voice.tts import TTS  # noqa: E402

import sim_turns as sim  # noqa: E402  (FakeDevice and the mic feeder)

QUESTIONS = ["What's two plus two?", "What day is it today?", "What are my agents doing?"]


async def main(args):
    hub = session.Hub()
    hub.settings["endpoint_ms"] = args.endpoint
    hub.settings["model"] = args.model
    hub.settings["volume"] = 0.0
    if args.speed:
        hub.settings["speed"] = args.speed
    hub.tts = sim.tts
    hub.device = sim.FakeDevice(hub)
    hub.call = True
    await hub.brain.connect()
    s = sim.Sim.__new__(sim.Sim)
    s.hub, s.mic, s.echo, s.echo_gain, s.user_onsets, s.clips = hub, __import__("collections").deque(), None, 0.0, [], []
    await asyncio.to_thread(__import__("claudebot_voice.stt", fromlist=["warm"]).warm, "")
    tasks = [asyncio.create_task(hub._tts_worker()), asyncio.create_task(hub.device.run()),
             asyncio.create_task(hub._ticker()), asyncio.create_task(s._feed())]
    rows = []
    for r in range(args.rounds):
        for q in QUESTIONS:
            audio = sim.speech16k(q, "af_heart")
            hub.last_timing = {}
            s.say_into_mic(audio, at=0.1)
            t0 = time.monotonic()
            while not hub.last_timing and time.monotonic() - t0 < 60:
                await asyncio.sleep(0.05)
            t = hub.last_timing
            while hub.brain.busy or hub.engaged():
                await asyncio.sleep(0.1)
            said = " ".join(hub.said.get(t.get("turn"), []))[:90] if t else ""
            if not t:
                print(f"  {q!r}: no answer within 60 s")
                continue
            stages = {k: t[k] for k in ("speech_end", "endpoint", "stt", "send", "first_token", "first_chunk", "tts", "first_audio") if k in t}
            names = list(stages)
            parts = ", ".join(f"{b} {stages[b] - stages[a]:.2f}" for a, b in zip(names, names[1:]))
            print(f"  {q!r}: {t['total']:.2f}s  ({parts})  -> {said!r}")
            rows.append(t)
            await asyncio.sleep(1.0)
    totals = [t["total"] for t in rows]
    print(f"\nmodel {args.model}, endpoint {args.endpoint} ms: median {np.median(totals):.2f}s, best {min(totals):.2f}s, worst {max(totals):.2f}s")
    for t in tasks:
        t.cancel()
    await hub.brain.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--endpoint", type=int, default=1100)
    p.add_argument("--model", default="haiku")
    p.add_argument("--rounds", type=int, default=1)
    p.add_argument("--speed", type=float, default=0)
    asyncio.run(main(p.parse_args()))
