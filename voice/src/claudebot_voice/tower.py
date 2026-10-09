"""The fleet: Claude Code agents in my tmux panes, read and driven through the tower CLI."""

import asyncio
import difflib
import json
import os
import random
import re
import time
from pathlib import Path

STATE_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "tower"
HOME = str(Path.home())


async def run(*args: str, timeout: float = 15.0) -> tuple[int, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            "tower", *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except FileNotFoundError:
        return 127, "tower is not installed"
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.kill()
        return 124, f"tower {args[0]} timed out after {timeout:.0f}s"
    return proc.returncode, out.decode(errors="replace").strip()


_flags: dict[tuple[str, str], bool] = {}


async def supports(command: str, flag: str) -> bool:
    """Whether this tower's `command` takes `flag` (attachments arrived in a later tower)."""
    key = (command, flag)
    if key not in _flags:
        _, out = await run(command, "--help", timeout=5)
        _flags[key] = re.search(rf"-{re.escape(flag)}\b", out) is not None
    return _flags[key]


async def tmux(*args: str) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        "tmux", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    out, _ = await proc.communicate()
    return proc.returncode, out.decode(errors="replace").strip()


# Claude Code's folder-trust dialog, all of it: a shell that merely shows the words must never get keys.
TRUST_LINES = ("Yes, I trust this folder", "No, exit", "Enter to confirm")
TRUST_YES = re.compile(r"❯\s*(\d\.\s*)?Yes, I trust this folder")


# Any of Claude Code's dialogs (a permission prompt, a question, the trust question) at the bottom of a pane.
DIALOG = re.compile(r"Esc to cancel|\(esc\)|Do you want to proceed|Would you like to proceed|Enter to (select|confirm)|"
                    r"Tab/Arrow keys|❯ \d+\. (Yes|No)\b")


def bottom(screen: str, n: int = 12) -> str:
    """The last n non-blank lines: what is live on the screen, not what scrolled up above a prompt."""
    return "\n".join([line for line in screen.splitlines() if line.strip()][-n:])


async def screen(pane: str) -> str:
    rc, out = await tmux("capture-pane", "-p", "-t", pane)
    return "" if rc else out


async def dialog_open(pane: str) -> bool:
    return bool(DIALOG.search(bottom(await screen(pane))))


def _trust_live(screen: str) -> bool:
    # the dialog must be what the pane shows now: Claude may have exited and left it above a shell prompt
    return all(line in screen for line in TRUST_LINES) and "Enter to confirm" in bottom(screen, 3)


async def trust_dialog(pane: str) -> bool:
    return _trust_live(await screen(pane))


async def accept_trust(pane: str) -> bool:
    """Pick "Yes, I trust this folder" on Claude Code's trust dialog. The highlighted first option is
    "No, exit", and Down and Enter sent together arrive as one chunk that confirms "No, exit". So: one
    key at a time, and Enter only once the pointer is seen on Yes."""
    for _ in range(3):
        rc, shown = await tmux("capture-pane", "-p", "-t", pane)
        if rc or not _trust_live(shown):
            return False
        if TRUST_YES.search(shown):
            rc, _ = await tmux("send-keys", "-t", pane, "Enter")
            return rc == 0
        await tmux("send-keys", "-t", pane, "Down")
        await asyncio.sleep(0.5)
    return False


def _state_file(session_id: str) -> dict:
    if not session_id:
        return {}
    try:
        return json.loads((STATE_DIR / f"{Path(session_id).name}.json").read_text())
    except (OSError, ValueError):
        return {}


async def agents() -> list[dict]:
    rc, out = await run("ls", "--json", timeout=8)
    if rc:
        return []
    try:
        items = json.loads(out) or []
    except ValueError:
        return []
    for a in items:
        st = _state_file(a.get("session_id", ""))
        for key in ("turn_started", "finished", "updated", "started"):
            a[key] = st.get(key) or 0
    return items


async def threads() -> list[dict]:
    rc, out = await run("threads", "--json", timeout=8)
    if rc:
        return []
    try:
        return json.loads(out) or []
    except ValueError:
        return []


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def resolve(query: str, items: list[dict]) -> dict | None:
    """Match a (possibly misheard) agent name, index or pane id."""
    q, raw = _norm(query), query.strip()
    for a in items:
        if raw in (str(a.get("index")), a.get("pane"), a.get("where")) or _norm(a["name"]) == q:
            return a
    if not q:
        return None
    # Speech to text mishears names ("claudia bot" for claudebot, about 0.84 alike), but a loose match
    # can hit the wrong agent ("voicetest" and "voiceagent" are 0.63 alike), and that agent then gets
    # my message. So: close matches only, and nothing at all when two names fit about as well.
    by_name = {_norm(a["name"]): a for a in items}
    scored = sorted(((difflib.SequenceMatcher(None, q, key).ratio(), key) for key in by_name), reverse=True)
    if scored and scored[0][0] >= 0.75 and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.06):
        return by_name[scored[0][1]]
    inside = [a for key, a in by_name.items() if q in key or key in q]
    return inside[0] if len(inside) == 1 else None


def ago(ts: float) -> str:
    if not ts:
        return ""
    s = max(0, int(time.time() - ts))
    if s < 90:
        return f"{s}s"
    if s < 5400:
        return f"{round(s / 60)}m"
    if s < 172800:
        return f"{round(s / 3600)}h"
    return f"{round(s / 86400)}d"


def short_path(p: str) -> str:
    return "~" + p[len(HOME):] if p.startswith(HOME) else p


def clip(s: str, n: int) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[: n - 3] + "..."


def view(items: list[dict]) -> list[dict]:
    """What the UI's fleet panel needs."""
    out = []
    for a in items:
        since = a["turn_started"] if a["state"] == "working" else a["finished"] or a["updated"]
        out.append({
            "name": a["name"],
            "pane": a["pane"],
            "where": a.get("where", ""),
            "state": a["state"],
            "activity": clip(a.get("activity", ""), 140),
            "prompt": clip(a.get("prompt", ""), 240),
            "cwd": short_path(a.get("cwd", "")),
            "since": since,
        })
    return out


def report(items: list[dict], headless: list[dict]) -> str:
    """Fleet summary for the model to read (not spoken verbatim)."""
    if not items and not headless:
        return "No agents are running in tmux right now."
    counts = {s: sum(a["state"] == s for a in items) for s in ("working", "waiting", "done", "idle")}
    lines = [f"{len(items)} agents: " + ", ".join(f"{n} {s}" for s, n in counts.items() if n)]
    for a in items:
        st = a["state"]
        when = ago(a["turn_started"]) if st == "working" else ago(a["finished"] or a["updated"])
        state = {"working": f"working for {when}", "waiting": "WAITING ON ME (permission prompt or question)",
                 "done": f"finished {when} ago, unread", "idle": f"idle, last active {when} ago"}.get(st, st)
        line = f"- {a['name']} [{a['pane']}]: {state}, in {short_path(a.get('cwd', ''))}."
        if st in ("working", "waiting") and a.get("activity"):
            line += f" Now: {clip(a['activity'], 160)}."
        if a.get("prompt"):
            line += f" Task: \"{clip(a['prompt'], 220)}\""
        lines.append(line)
    for t in headless:
        lines.append(f"- headless thread {t.get('name') or t.get('id')}: {t.get('state') or t.get('status', '')}")
    return "\n".join(lines)


def say_name(name: str) -> str:
    return re.sub(r"[-_.]+", " ", name)


def _join(names: list[str]) -> str:
    names = [say_name(n) for n in names]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def greeting(items: list[dict]) -> str:
    """Short spoken status for the moment a call starts. No model involved, so it is instant."""
    closer = random.choice(["Shoot.", "Go ahead.", "What's up?", "Listening."])
    if not items:
        return f"Got it. {closer}"
    groups = {s: [a["name"] for a in items if a["state"] == s] for s in ("waiting", "working", "done")}
    parts = []
    for state, (one, many) in {"waiting": ("needs you", "need you"), "working": ("is working", "are working"),
                               "done": ("finished", "finished")}.items():
        names = groups[state]
        if len(names) > 3:
            parts.append(f"{len(names)} agents {many}")
        elif names:
            parts.append(f"{_join(names)} {one if len(names) == 1 else many}")
    if not parts:
        return f"All quiet. {closer}"
    return "Hey. " + ", ".join(parts) + f". {closer}"


class Watcher:
    """Polls the fleet and reports transitions worth telling me about."""

    def __init__(self, on_update, interval: float = 2.5):
        self.on_update = on_update
        self.interval = interval

    async def run(self):
        prev: dict[str, dict] | None = None
        while True:
            try:
                items = await agents()
                cur = {a.get("session_id") or a["pane"]: a for a in items}
                events = []
                if prev is not None:
                    for key, a in cur.items():
                        p = prev.get(key)
                        if p is None:
                            events.append(("new", a))
                        elif p["state"] != a["state"]:
                            if a["state"] == "waiting":
                                events.append(("waiting", a))
                            elif p["state"] == "working" and a["state"] in ("done", "idle"):
                                events.append(("finished", a))
                    events += [("gone", p) for key, p in prev.items() if key not in cur]
                fingerprint = [(a["pane"], a["state"], a.get("activity"), a["name"]) for a in items]
                await self.on_update(items, events, fingerprint)
                prev = cur
            except Exception:  # keep polling whatever happens
                import logging
                logging.getLogger("claudebot_voice.tower").exception("fleet poll failed")
            await asyncio.sleep(self.interval)
