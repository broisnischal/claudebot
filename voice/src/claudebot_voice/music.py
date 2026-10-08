"""Music: YouTube audio through yt-dlp and mpv, mixed into my own speaker stream.

mpv decodes to raw 48 kHz mono PCM on a pipe instead of opening its own audio output. That way the
music goes through the same stream as the voice, so the echo canceller hears it as far end (a song's
vocals never pass for me talking), and ducking is just a gain ramp in the mixer. The pipe paces mpv:
it only decodes as fast as the speaker drains it.
"""

import asyncio
import json
import logging
import os
import threading
import time
from collections import deque

import numpy as np

from .config import RUNTIME_DIR

log = logging.getLogger("claudebot_voice.music")

SOCK = RUNTIME_DIR / "mpv.sock"
BUFFER = 48000 // 2  # half a second of samples ahead of the speaker; mpv blocks beyond that


async def search(query: str, n: int = 6) -> list[tuple[str, str]]:
    """(video id, title) for the top YouTube results."""
    proc = await asyncio.create_subprocess_exec(
        "yt-dlp", "--no-warnings", "--flat-playlist", "--match-filters", "live_status!=is_live",  # live can't pipe
        "--print", "%(id)s\t%(title)s", f"ytsearch{n}:{query}",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), 15)
    except TimeoutError:
        proc.kill()
        return []
    hits = []
    for line in out.decode(errors="replace").splitlines():
        if "\t" in line:
            vid, title = line.split("\t", 1)
            hits.append((vid.strip(), title.strip()))
    return hits


# YouTube's default client for yt-dlp (android_vr) answers 403 on the media itself these days; the
# mobile web client still streams.
YTDL = ["yt-dlp", "-q", "--no-warnings", "--no-part", "--extractor-args", "youtube:player_client=mweb",
        "-f", "bestaudio/best", "-o", "-"]
MPV = ["mpv", "--no-video", "--no-terminal", "--idle=no", "--ao=pcm", "--ao-pcm-file=/dev/stdout",
       "--ao-pcm-waveheader=no", "--audio-channels=mono", "--audio-samplerate=48000", "--audio-format=s16"]


class Music:
    """A queue of search results. yt-dlp downloads the current one into mpv, mpv decodes it for the mixer."""

    def __init__(self, on_change):
        self.on_change = on_change  # () -> None, whenever the state the panel shows changes
        self.proc: asyncio.subprocess.Process | None = None  # mpv for the current track
        self.fetch: asyncio.subprocess.Process | None = None  # yt-dlp feeding it
        self.writer: asyncio.StreamWriter | None = None
        self.buf: deque = deque()  # int16 chunks
        self.buffered = 0
        self.cond = threading.Condition()
        self.queue: list[tuple[str, str]] = []
        self.index = 0
        self.query = ""
        self.title = ""
        self.paused = False
        self.pending: dict[int, asyncio.Future] = {}
        self.req = 0

    @property
    def active(self) -> bool:
        return self.proc is not None

    def state(self) -> dict:
        return {"playing": self.active and not self.paused, "paused": self.active and self.paused,
                "title": self.title if self.active else "", "query": self.query if self.active else ""}

    # ---- control (loop thread) ----

    async def play(self, query: str) -> str:
        hits = await search(query)
        if not hits:
            return f"Found nothing on YouTube for {query}."
        await self.stop(quiet=True)
        self.queue, self.index, self.query = hits, 0, query
        await self._start()
        return f"Starting \"{hits[0][1]}\". YouTube takes about ten seconds before the sound comes in."

    async def _start(self):
        """Start the track at self.index, replacing whatever plays."""
        await self._kill()
        vid, self.title = self.queue[self.index]
        self.paused = False
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        SOCK.unlink(missing_ok=True)
        # Plain OS pipes on both sides: uvicorn runs on uvloop, whose subprocess pipes are socket
        # pairs, and mpv can't open a socket as /dev/stdout.
        feed_r, feed_w = os.pipe()
        pcm_r, pcm_w = os.pipe()
        try:
            self.fetch = await asyncio.create_subprocess_exec(
                *YTDL, f"https://www.youtube.com/watch?v={vid}",
                stdin=asyncio.subprocess.DEVNULL, stdout=feed_w, stderr=asyncio.subprocess.DEVNULL)
            self.proc = await asyncio.create_subprocess_exec(
                *MPV, f"--input-ipc-server={SOCK}", "-",
                stdin=feed_r, stdout=pcm_w, stderr=asyncio.subprocess.DEVNULL)
        except OSError:
            os.close(pcm_r)
            raise
        finally:
            for fd in (feed_r, feed_w, pcm_w):
                os.close(fd)
        loop = asyncio.get_running_loop()
        threading.Thread(target=self._pump, args=(pcm_r, self.proc, self.fetch, loop), daemon=True).start()
        asyncio.create_task(self._ipc(self.proc))
        self.on_change()

    async def control(self, action: str) -> str:
        if not self.active:
            return "Nothing is playing."
        if action in ("pause", "resume", "toggle"):
            self.paused = {"pause": True, "resume": False, "toggle": not self.paused}[action]
            await self._command("set_property", "pause", self.paused)
            self.on_change()
            return "Paused." if self.paused else "Playing again."
        if action in ("next", "previous"):
            step = 1 if action == "next" else -1
            if not 0 <= self.index + step < len(self.queue):
                return "That was the last one." if step > 0 else "This is the first one."
            self.index += step
            await self._start()
            return f"Playing \"{self.title}\"."
        if action == "stop":
            await self.stop()
            return "Stopped."
        return f"Unknown action {action}."

    async def _kill(self):
        proc, fetch, self.proc, self.fetch = self.proc, self.fetch, None, None
        if self.writer:
            self.writer.close()
            self.writer = None
        for p in (fetch, proc):
            if p and p.returncode is None:
                p.kill()
                try:
                    await asyncio.wait_for(p.wait(), 3)
                except TimeoutError:
                    pass
        self._drop()

    async def stop(self, quiet: bool = False):
        await self._kill()
        self.title = ""
        self.queue = []
        if not quiet:
            self.on_change()

    def _drop(self):
        with self.cond:
            self.buf.clear()
            self.buffered = 0
            self.cond.notify_all()

    # ---- mpv's PCM and IPC ----

    def _pump(self, fd, proc, fetch, loop):
        """Thread: copy decoded PCM into the mixer's buffer, waiting while it is full so mpv stays paced."""
        started = time.monotonic()
        first = True
        carry = b""
        with os.fdopen(fd, "rb", buffering=0) as pcm:
            while True:
                data = pcm.read(9600)
                if not data or proc is not self.proc:
                    break
                if first:
                    first = False
                    log.info("music: %s started after %.1fs", self.title, time.monotonic() - started)
                data = carry + data
                cut = len(data) - len(data) % 2
                carry = data[cut:]
                chunk = np.frombuffer(data[:cut], dtype="<i2").copy()
                self._wait_room(proc)
                if proc is not self.proc:
                    break
                with self.cond:
                    self.buf.append(chunk)
                    self.buffered += len(chunk)
        asyncio.run_coroutine_threadsafe(self._ended(proc, fetch, first), loop)

    async def _ended(self, proc, fetch, silent: bool):
        await proc.wait()
        if proc is not self.proc:
            return  # replaced or stopped on purpose
        if fetch.returncode is None:
            fetch.kill()
        if silent:
            log.warning("music: %s did not play", self.title)
        # the track ended (or failed to load): on to the next one, or done
        if self.index + 1 < len(self.queue):
            self.index += 1
            await self._start()
        else:
            self.proc = None
            self.title = ""
            self.on_change()

    def _wait_room(self, proc):
        with self.cond:
            self.cond.wait_for(lambda: self.buffered < BUFFER or self.proc is not proc)

    async def _ipc(self, proc):
        for _ in range(100):
            if proc is not self.proc:
                return
            try:
                reader, self.writer = await asyncio.open_unix_connection(str(SOCK))
                break
            except OSError:
                await asyncio.sleep(0.1)
        else:
            log.warning("mpv ipc never came up")
            return
        while True:
            line = await reader.readline()
            if not line:
                return
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            fut = self.pending.pop(msg.get("request_id"), None)
            if fut and not fut.done():
                fut.set_result(msg)

    async def _command(self, *args):
        if not self.writer:
            return None
        self.req += 1
        fut = asyncio.get_running_loop().create_future()
        self.pending[self.req] = fut
        try:
            self.writer.write(json.dumps({"command": list(args), "request_id": self.req}).encode() + b"\n")
            await self.writer.drain()
            return await asyncio.wait_for(fut, 2)
        except (OSError, TimeoutError):
            return None
        finally:
            self.pending.pop(self.req, None)

    # ---- mixer side (audio thread) ----

    def take(self, frames: int) -> np.ndarray | None:
        """Up to `frames` samples of music as float32, or None when there is nothing to play."""
        if self.paused or not self.buffered:
            return None
        out = np.zeros(frames, dtype=np.float32)
        filled = 0
        with self.cond:
            while filled < frames and self.buf:
                chunk = self.buf[0]
                take = min(frames - filled, len(chunk))
                out[filled:filled + take] = chunk[:take] / 32768
                filled += take
                if take == len(chunk):
                    self.buf.popleft()
                else:
                    self.buf[0] = chunk[take:]
                self.buffered -= take
            self.cond.notify_all()
        return out
