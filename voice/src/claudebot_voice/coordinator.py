"""The coordinator: watches every Claude Code agent in my tmux panes and keeps them moving.

It works from what tower reports (the hub polls it every 2.5 s) and from each agent's transcript:
- A permission prompt: Claude reads the pending tool call against the agent's task. In scope and
  safe, it approves. Risky, out of scope or unclear, it waits for me and I hear about it.
- A question (AskUserQuestion): answered from the agent's task once I've had a while to answer it
  myself, picking the recommended option when that's the sensible call. Unsure, it asks me.
- A turn that ends on "want me to ...?" where the next step is plainly part of the task: go ahead.
- Stalls and errors: a turn that died on an API error is retried, a full context compacted, a turn
  silent for too long looked at and interrupted when it hangs, a folder-trust question accepted.
- Agents working against each other: two editing the same file are told about each other, and a
  look over the whole fleet now and then passes along what one needs from another.

It also keeps a profile of every agent, refreshed as its transcript moves: the task, what it has
done so far, what's next, what blocks it and what it needs. That is how the voice can tell me what
everyone is doing without reading their screens.

It leaves alone the pane I'm working in, agents I put hands-off, and anything it already handled.
Every action goes in a log with its reason; it only speaks up when it needs me.
"""

import asyncio
import json
import logging
import re
import time
from collections import deque
from pathlib import Path

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, query

from . import models, tower
from .config import DATA_DIR

log = logging.getLogger("claudebot_voice.coordinator")

LOG_FILE = DATA_DIR / "coordinator.json"
# Seconds an agent waits before the coordinator steps in, so I can answer first when I'm around.
GRACE = {"approve": 4, "question": 40, "turn": 75}
STALL_S = 10 * 60  # a turn with no transcript progress for this long gets a look
REVIEW_S = 10 * 60  # how often it looks over the whole fleet for agents that need each other (on Opus)
OVERLAP_S = 30 * 60  # edits to one file by two agents within this window are a clash
FOCUS_S = 120  # I count as working in my focused pane while tmux saw me within this long
TURN_WINDOW = 20 * 60  # a turn that ended longer ago than this was left alone on purpose
GO_AHEAD_MAX = 3  # automatic "go ahead"s per task before it leaves the decision to me
RETRY_MAX = 3  # retries after API errors per agent per hour
SHELLS = {"claude", "node", "zsh", "bash", "sh", "fish"}
API_ERROR = re.compile(r"API Error|Overloaded|overloaded_error|Internal server error|Connection error|"
                       r"Request timed out|fetch failed", re.I)
USAGE_LIMIT = re.compile(r"usage limit|limit reached|resets at|out of (extra )?usage", re.I)
# My own Claude calls hitting the plan's limit: no point trying again every few seconds.
LIMIT_HIT = re.compile(r"hit your .*limit|session limit|usage limit|limit reached|out of (extra )?usage", re.I)
LIMIT_PAUSE_S = 10 * 60
CONTEXT_FULL = re.compile(r"Prompt is too long|Context low|context window.*(full|exceeded)|auto-compact", re.I)
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

JUDGE = """You are the coordinator of my Claude Code agents. They run in tmux panes on my Linux \
workstation while I do other things. You decide on my behalf, the way I would, so that they keep \
making progress without doing anything I would not want. You reply with one JSON object and nothing \
else: no prose, no code fences."""

PERMISSION = """Agent "{name}" works in {cwd}.
What I asked it (its task): {task}

What it said and did most recently:
{context}

It is waiting for my permission to run this tool call:
{tool}: {input}

Approve when the call serves its task and is safe: reading, searching, listing, building, running \
tests or linters, running or serving the project locally, editing files inside its project, \
installing dev dependencies into the project, git commands that don't rewrite shared history, \
reading web pages. Ask me when it deletes or overwrites anything outside its project or in bulk, \
touches system configuration or other projects, uses sudo, force-pushes, pushes to a main or \
shared branch, deploys or publishes, spends money, sends messages, emails or posts, reads or \
changes secrets, keys or credentials, or does anything you can't tell is safe or that isn't part \
of its task. ExitPlanMode means accepting its plan, after which it starts working: approve when the \
plan does what the task asks and stays inside it, ask me when the plan goes further or is risky.

Reply: {{"decision": "approve" or "ask", "reason": "one short sentence"}}"""

QUESTION = """Agent "{name}" works in {cwd}.
What I asked it (its task): {task}

What it said and did most recently:
{context}

It asks me these questions (JSON):
{questions}

I haven't answered for a while, so answer for me where the right answer follows from the task and \
the context, or where one option is marked recommended and nothing argues against it. If an answer \
is a real decision only I can make (product direction, money, anything irreversible or outside the \
task), don't guess.

Reply: {{"answer": true or false, "answers": [{{"question": "...", "choice": "the option label, \
or your own short answer"}}], "reason": "one short sentence"}}"""

TURN = """Agent "{name}" works in {cwd}.
What I asked it (its task): {task}

Its turn just ended with this reply, and I haven't responded:
{reply}

Decide whether to tell it to carry on. "continue" only when it asks a yes-or-no question about the \
single next step of its task and that step is safe ("want me to run the tests?", "shall I apply the \
fix?", "should I continue with part 2?"); the message is just the go-ahead, e.g. "Yes, go ahead." \
"ask" when it offers a choice between options, or needs a real decision only I can make (direction, \
deploying, deleting, spending, anything risky or outside the task). "none" when it is simply done \
or reports something without asking.

Reply: {{"action": "continue" or "ask" or "none", "message": "...", "reason": "one short sentence"}}"""

STALL = """Agent "{name}" works in {cwd}.
What I asked it (its task): {task}

Its current turn has made no progress for {minutes} minutes. The bottom of its terminal:
{screen}

Decide what to do. "wait" when it is legitimately busy (a long build, a test suite, a download, \
waiting on a subagent). "interrupt" when it is stuck: a command hanging on input, a pager or \
editor, a server started in the foreground, an endless loop. The message tells it what went wrong \
and how to go on. "compact" when its context is full. "ask" when only I can unblock it (a login, a \
password, hardware).

Reply: {{"action": "wait" or "interrupt" or "compact" or "ask", "message": "...", "reason": "one short sentence"}}"""

REVIEW = """These are my Claude Code agents right now (JSON):
{fleet}

Look for agents that need something from each other: one waiting on or asking for a result \
another has produced, two doing the same work twice, one about to undo another's work. For each \
real case, write a short message to send to the agent that should act, naming the other agent \
and what to do (they can reach each other with `tower send <name> "..."`). Most of the time \
nothing is needed: then return no messages. At most two messages.

Reply: {{"messages": [{{"to": "agent name", "text": "...", "reason": "one short sentence"}}]}}"""


PROFILE = """Agent "{name}" works in {cwd}.
What I asked it (its task): {task}
State: {state}. Right now: {doing}

Its recent transcript, oldest first:
{context}

Its last reply:
{reply}

Sum it up for my voice assistant, who will tell me about it. Plain words, no file paths unless they \
matter, no code. Reply: {{"summary": "what it has done so far and where it stands, one or two \
sentences", "next": "what it is doing or about to do next, short", "blocked_on": "what actually stops \
it from going on right now (an error, a prompt, a missing input), or empty when nothing does; busy is \
not blocked", "needs": "a specific thing it is waiting for from me or another agent before \
it can go on, or empty. An agent that finished and simply awaits its next task needs nothing."}}"""

SUMMARY_S = 3 * 60  # a working agent's profile is refreshed at most this often


def _json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group())
    except ValueError:
        return {}


def clip(text: str, n: int) -> str:
    text = str(text or "")
    return text if len(text) <= n else text[: n - 1] + "…"


class Transcript:
    """The tail of an agent's transcript: its pending tool call, what it said lately, what it edited."""

    def __init__(self, path: str, tail_bytes: int = 400_000):
        self.pending: dict | None = None  # {id, name, input}: a tool call with no result yet
        self.context: list[str] = []
        self.edits: list[tuple[float, str]] = []  # (time, file path)
        self.model = ""  # the model behind its latest reply
        self.mtime = 0.0
        try:
            p = Path(path)
            self.mtime = p.stat().st_mtime
            with p.open("rb") as f:
                start = max(0, p.stat().st_size - tail_bytes)
                f.seek(start)
                lines = f.read().decode(errors="replace").splitlines()[1 if start else 0:]
        except (OSError, TypeError, ValueError):
            return
        calls: dict[str, dict] = {}
        done: set[str] = set()
        for line in lines:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            msg = e.get("message") or {}
            if e.get("type") == "assistant" and str(msg.get("model", "")).startswith("claude-"):
                self.model = msg["model"]
            content = msg.get("content")
            if not isinstance(content, list):
                if e.get("type") == "user" and isinstance(content, str):
                    self.context.append(f"Me: {clip(content, 300)}")
                continue
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use":
                    calls[b.get("id", "")] = {"id": b.get("id", ""), "name": b.get("name", ""), "input": b.get("input") or {}}
                    self.context.append(f"It called {b.get('name')}: {clip(json.dumps(b.get('input'), ensure_ascii=False), 300)}")
                    if b.get("name") in EDIT_TOOLS:
                        target = (b.get("input") or {}).get("file_path") or (b.get("input") or {}).get("notebook_path")
                        if target:
                            self.edits.append((_ts(e.get("timestamp")), target))
                elif b.get("type") == "tool_result":
                    done.add(b.get("tool_use_id", ""))
                    out = b.get("content")
                    if isinstance(out, list):
                        out = " ".join(x.get("text", "") for x in out if isinstance(x, dict))
                    self.context.append(f"Result: {clip(out, 200)}")
                elif b.get("type") == "text" and b.get("text", "").strip():
                    who = "It said" if e.get("type") == "assistant" else "Me"
                    self.context.append(f"{who}: {clip(b['text'].strip(), 500)}")
        open_calls = [c for cid, c in calls.items() if cid not in done]
        self.pending = open_calls[-1] if open_calls else None
        self.context = self.context[-14:]


async def read(path: str, tail_bytes: int = 400_000) -> Transcript:
    """Parsing a transcript takes a while; keep it off the event loop the audio runs on."""
    return await asyncio.to_thread(Transcript, path, tail_bytes)


def _ts(stamp) -> float:
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


class Coordinator:
    def __init__(self, hub):
        self.hub = hub
        self.items: list[dict] = []
        self.since: dict[str, tuple[str, float]] = {}  # agent key: (state, when it entered it)
        self.handled: deque = deque(maxlen=500)  # keys of prompts, questions and turns already dealt with
        self.busy: set[str] = set()  # agents being handled right now
        self.pending: dict[str, dict] = {}  # pane: what it needs from me
        self.go_aheads: dict[str, tuple[str, int]] = {}  # agent key: (task, automatic go-aheads so far)
        self.retries: dict[str, list[float]] = {}
        self.warned: set = set()  # file clashes already pointed out
        self.reviewed_at = time.monotonic()
        self.clashed_at = 0.0
        self.review_print = None
        self.ticking = False
        self.tasks: dict[str, str] = {}  # agent key: the last task I gave it myself
        self.sent: dict[str, set[str]] = {}  # pane: what the coordinator typed into it
        self.cost = 0.0
        self.judging = asyncio.Semaphore(2)
        self.paused_until = 0.0  # its own Claude calls hit the usage limit: none until then
        self.profiling = asyncio.Semaphore(1)  # summaries never hold up an approval
        self.profiles: dict[str, dict] = {}  # agent key: what it's doing, blocked on and needs
        self.profiled: set[str] = set()  # agents being summed up right now
        self.log: deque = deque(maxlen=200)
        try:
            self.log.extend(json.loads(LOG_FILE.read_text()))
        except (OSError, ValueError):
            pass

    # ---- state ---------------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return bool(self.hub.settings.get("coordinator", True))

    def view(self) -> dict:
        return {"enabled": self.enabled, "pending": list(self.pending.values()), "log": list(self.log)[-60:],
                "skip": self.hub.settings.get("coordinator_skip", []), "cost": round(self.cost, 4)}

    def _changed(self):
        self.hub.broadcast({"type": "coordinator", "coordinator": self.view()})

    def record(self, a: dict, action: str, reason: str, detail: str = ""):
        entry = {"ts": time.time(), "agent": a.get("name", "?"), "pane": a.get("pane", ""), "action": action,
                 "reason": clip(reason, 240), "detail": clip(detail, 400)}
        self.log.append(entry)
        log.info("%s: %s (%s)", entry["agent"], action, reason)
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            LOG_FILE.write_text(json.dumps(list(self.log)))
        except OSError:
            log.debug("could not save the coordinator log", exc_info=True)
        # routine approvals stay in the log; the voice hears about answers, nudges, fixes and asks
        if action != "approved":
            self.hub.brain.notes.append(f"The coordinator {action} for {entry['agent']}: {entry['reason']}")
            del self.hub.brain.notes[:-12]
        self._changed()

    def escalate(self, a: dict, kind: str, text: str, detail: str = ""):
        """Something only I can decide: it stays put, and I hear about it once."""
        pane = a.get("pane", "")
        if self.pending.get(pane, {}).get("text") == text:
            return
        self.pending[pane] = {"pane": pane, "agent": a.get("name", "?"), "kind": kind, "text": text,
                              "detail": clip(detail, 600), "ts": time.time(), "state": a.get("state", "")}
        self.record(a, "asked me", text, detail)
        hub = self.hub
        hub.toast(text, "waiting")
        hub.log("event", text)
        if hub.call and hub.settings.get("announce", True):
            hub.announcements.append(text)
            del hub.announcements[:-3]

    def _skip(self, a: dict, focused: str | None) -> bool:
        skip = {s.lower() for s in self.hub.settings.get("coordinator_skip", [])}
        return a.get("name", "").lower() in skip or a.get("pane") == focused

    @staticmethod
    def key(a: dict) -> str:
        return a.get("session_id") or a.get("pane", "")

    # ---- the loop --------------------------------------------------------------------------

    def observe(self, items: list[dict]):
        """Called with every fleet poll. Starts work for agents that need something; never blocks."""
        self.items = items
        now = time.monotonic()
        live = {a.get("pane") for a in items}
        for pane in [p for p in self.pending if p not in live]:
            del self.pending[pane]
        for a in items:
            k = self.key(a)
            state = a.get("state", "")
            if self.since.get(k, ("",))[0] != state:
                self.since[k] = (state, now)
            raised = self.pending.get(a.get("pane"))
            if raised and raised.get("state") != state:
                del self.pending[a["pane"]]
                self._changed()
        for k in [k for k in self.profiles if k not in {self.key(a) for a in items}]:
            del self.profiles[k]
        asyncio.create_task(self._profile_all(items))
        if not self.enabled:
            return
        asyncio.create_task(self._tick(items))

    async def _tick(self, items: list[dict]):
        if self.ticking:
            return  # the last one is still going; polls come every 2.5 s
        self.ticking = True
        try:
            focused = await self._focused()
            now = time.monotonic()
            for a in items:
                k = self.key(a)
                if k in self.busy or self._skip(a, focused):
                    continue
                state, since = self.since.get(k, ("", now))
                waited = now - since
                job = None
                if state == "waiting":
                    question = str(a.get("activity", "")).endswith("AskUserQuestion")
                    if waited >= GRACE["question" if question else "approve"]:
                        job = self._waiting(a)
                elif state in ("done", "idle") and a.get("finished"):
                    # tower calls a turn "idle" once its pane has been on screen, which says little
                    # about whether I read it; go by when it ended instead
                    ended = time.time() - a["finished"]
                    if GRACE["turn"] <= ended <= TURN_WINDOW:
                        job = self._turn_end(a)
                elif state == "working" and waited >= STALL_S:
                    job = self._maybe_stalled(a)
                if job:
                    self.busy.add(k)
                    asyncio.create_task(self._run(k, job))
            await self._trust_prompts(items)
            if time.monotonic() - self.clashed_at > 60:
                self.clashed_at = time.monotonic()
                await self._clashes(items, focused)
            if time.monotonic() - self.reviewed_at > REVIEW_S:
                self.reviewed_at = time.monotonic()
                asyncio.create_task(self._review(items, focused))
        except Exception:
            log.exception("coordinator tick failed")
        finally:
            self.ticking = False

    async def _run(self, k: str, job):
        try:
            await job
        except Exception:
            log.exception("coordinator job failed")
        finally:
            self.busy.discard(k)

    async def _focused(self) -> str | None:
        """The pane I'm working in: the active pane of the tmux client I used most recently."""
        rc, out = await tower.tmux("list-clients", "-F", "#{client_activity} #{pane_id}")
        if rc:
            return None
        best = max((line.split() for line in out.splitlines() if len(line.split()) == 2),
                   key=lambda p: int(p[0]) if p[0].isdigit() else 0, default=None)
        if best and best[0].isdigit() and time.time() - int(best[0]) < FOCUS_S:
            return best[1]
        return None

    # ---- judging ---------------------------------------------------------------------------

    async def judge(self, prompt: str, model: str | None = None, gate: asyncio.Semaphore | None = None) -> dict:
        opts = ClaudeAgentOptions(
            model=model or self.hub.settings.get("coordinator_model") or models.ROLES["judge"],
            system_prompt=JUDGE,
            tools=[],
            setting_sources=[],
            strict_mcp_config=True,
            max_turns=1,
            thinking={"type": "disabled"},
            cwd=str(Path.home()),
            env={"TMUX_PANE": ""},  # tower must not take the judge for one of my agents
        )
        if time.time() < self.paused_until:
            return {}
        text = ""
        try:
            async with gate or self.judging:
                async for m in query(prompt=prompt, options=opts):
                    if isinstance(m, AssistantMessage):
                        text += "".join(b.text for b in m.content if isinstance(b, TextBlock))
                    elif isinstance(m, ResultMessage):
                        self.cost += m.total_cost_usd or 0
        except Exception as e:
            if LIMIT_HIT.search(str(e)):
                if time.time() >= self.paused_until:
                    log.warning("hit the usage limit; the coordinator's own Claude calls pause for %d minutes",
                                LIMIT_PAUSE_S // 60)
                self.paused_until = time.time() + LIMIT_PAUSE_S
                return {}
            raise
        out = _json(text)
        if not out:
            log.warning("the judge didn't answer in JSON: %r", text[:300])
        return out

    def task(self, a: dict) -> str:
        """What I last asked the agent. Tower records the latest prompt, which may be the
        coordinator's own "go ahead"; those don't replace the task."""
        k = self.key(a)
        prompt = (a.get("prompt") or "").strip()
        ours = prompt in self.sent.get(a.get("pane", ""), set()) or prompt.startswith(
            ("[answered by my coordinator", "[note from my coordinator", "[from my coordinator"))
        if prompt and not ours:
            self.tasks[k] = prompt
        return self.tasks.get(k, prompt)

    def _brief(self, a: dict) -> dict:
        return {"name": a.get("name", "?"), "cwd": tower.short_path(a.get("cwd", "")),
                "task": clip(self.task(a) or "(no task recorded)", 1500)}

    # ---- profiles: what every agent is doing, blocked on and needs --------------------------------

    async def _profile_all(self, items: list[dict]):
        for a in items:
            k = self.key(a)
            if k in self.profiled:
                continue
            p = self.profiles.get(k)
            try:
                mtime = Path(a.get("transcript", "")).stat().st_mtime
            except (OSError, TypeError):
                mtime = 0.0
            if p:
                # cheap fields follow every poll; the summary only when the transcript moved
                p.update(state=a.get("state", ""), doing=clip(a.get("activity", ""), 200), task=clip(self.task(a), 600))
                p["blocked_on"] = self._blocker(a, p)
                moved = mtime > p["mtime"]
                fresh_state = p.get("summed_state") != p["state"]
                if not moved or (not fresh_state and time.time() - p["updated"] < SUMMARY_S):
                    continue
            self.profiled.add(k)
            asyncio.create_task(self._profile(a, mtime))

    def _blocker(self, a: dict, p: dict) -> str:
        if a.get("state") == "waiting":
            mine = self.pending.get(a.get("pane", ""))
            return mine["text"] if mine else f"waiting on me: {a.get('activity', '')}"
        return p.get("judged_blocker", "")

    async def _profile(self, a: dict, mtime: float):
        k = self.key(a)
        try:
            t = await read(a.get("transcript", ""))
            rc, reply = await tower.run("last", a["pane"])
            v = await self.judge(PROFILE.format(
                **self._brief(a), state=a.get("state", ""), doing=clip(a.get("activity", ""), 200),
                context="\n".join(t.context) or "(nothing yet)", reply=clip(reply[-2000:] if not rc else "", 2000)),
                model=models.ROLES["profile"], gate=self.profiling)
            old = self.profiles.get(k, {})
            for field in ("blocked_on", "needs"):
                if re.fullmatch(r"\W*(none|nothing|n/?a|empty|no\b.*)\W*", str(v.get(field, "")), re.I):
                    v[field] = ""  # "nothing", "no blocker yet": the model's way of saying empty
            files = sorted({tower.short_path(path) for _, path in t.edits[-12:]})
            p = {"name": a.get("name", "?"), "pane": a.get("pane", ""), "cwd": tower.short_path(a.get("cwd", "")),
                 "state": a.get("state", ""), "summed_state": a.get("state", ""), "doing": clip(a.get("activity", ""), 200),
                 "task": clip(self.task(a), 600), "summary": v.get("summary", old.get("summary", "")),
                 "next": v.get("next", ""), "judged_blocker": v.get("blocked_on", ""), "needs": v.get("needs", ""),
                 "files": files, "updated": time.time(), "mtime": mtime, "model": short_model(t.model)}
            p["blocked_on"] = self._blocker(a, p)
            self.profiles[k] = p
            # the voice hears about new blockers and needs between my messages, while they hold it up
            for field, what in (("blocked_on", "is blocked on"), ("needs", "needs")):
                if p[field] and p[field] != old.get(field) and p["state"] in ("waiting", "working"):
                    self.hub.brain.notes.append(f"{p['name']} {what}: {clip(p[field], 160)}")
                    del self.hub.brain.notes[:-12]
            self.hub.broadcast({"type": "profiles", "profiles": self.profile_list()})
        except Exception:
            log.exception("could not profile %s", a.get("name"))
        finally:
            self.profiled.discard(k)

    def profile_list(self) -> list[dict]:
        return [{k: v for k, v in p.items() if k not in ("mtime", "summed_state", "judged_blocker")}
                for p in self.profiles.values()]

    def fleet_text(self) -> str:
        """Every agent in a few lines: task, progress, next, blockers, needs."""
        if not self.profiles:
            return ""
        out = []
        for p in sorted(self.profiles.values(), key=lambda p: {"waiting": 0, "working": 1, "done": 2}.get(p["state"], 3)):
            on = f", on {p['model']}" if p.get("model") else ""
            line = f"{p['name']} ({p['state']}{on}, in {p['cwd']}). Task: {clip(p['task'], 200)}."
            if p.get("summary"):
                line += f" So far: {p['summary']}"
            if p.get("next"):
                line += f" Next: {p['next']}."
            if p.get("blocked_on"):
                line += f" Blocked on: {p['blocked_on']}."
            if p.get("needs"):
                line += f" Needs: {p['needs']}."
            out.append(line)
        return "\n".join(out)

    async def context_of(self, a: dict) -> str:
        """Everything about one agent, for when I ask about it in detail."""
        t = await read(a.get("transcript", ""))
        rc, reply = await tower.run("last", a["pane"])
        p = self.profiles.get(self.key(a), {})
        parts = [f"{a['name']} is {a.get('state')} in {tower.short_path(a.get('cwd', ''))}"
                 + (f", running on {short_model(t.model)}." if t.model else "."),
                 f"Task: {self.task(a) or '(none recorded)'}",
                 f"Right now: {a.get('activity', '')}"]
        for field, label in (("summary", "So far"), ("next", "Next"), ("blocked_on", "Blocked on"), ("needs", "Needs")):
            if p.get(field):
                parts.append(f"{label}: {p[field]}")
        if t.pending:
            parts.append(f"Pending tool call: {t.pending['name']} {clip(json.dumps(t.pending['input'], ensure_ascii=False), 800)}")
        if t.edits:
            parts.append("Files it edited lately: " + ", ".join(sorted({tower.short_path(x) for _, x in t.edits[-15:]})))
        mine = [e for e in self.log if e.get("pane") == a.get("pane")][-4:]
        if mine:
            parts.append("What the coordinator did for it: " + "; ".join(f"{e['action']} ({e['reason']})" for e in mine))
        parts.append("Recent transcript:\n" + "\n".join(t.context))
        parts.append("Last reply:\n" + (reply[-3000:] if not rc else "(none)"))
        return "\n".join(parts)

    # ---- waiting: permission prompts and questions --------------------------------------------

    async def _waiting(self, a: dict):
        t = await read(a.get("transcript", ""))
        call = t.pending
        if call is None:
            # Claude Code doesn't always write a tool call to the transcript before it asks about it.
            # Then tower's activity ("permission: Bash rm -rf ...") and the dialog on screen tell.
            # No dialog on screen: the folder-trust question, or tower's state is stale (a question
            # closed with Esc leaves it on "waiting").
            if await self._trust(a["pane"], a) or not await tower.dialog_open(a["pane"]):
                return
            call = _from_screen(a, await tower.screen(a["pane"]))
        if call is None:
            key = ("waiting", a["pane"], a.get("activity"), int(t.mtime))
            if key not in self.handled:
                self.handled.append(key)
                self.escalate(a, "waiting", f"{tower.say_name(a['name'])} is waiting on something I can't read.",
                              str(a.get("activity", "")))
            return
        key = ("call", call["id"])
        if key in self.handled:
            return
        self.handled.append(key)
        if call["name"] == "AskUserQuestion":
            await self._question(a, t, call)
        else:
            await self._permission(a, t, call)

    async def _permission(self, a: dict, t: Transcript, call: dict):
        b = self._brief(a)
        verdict = await self.judge(PERMISSION.format(
            **b, context="\n".join(t.context) or "(nothing)", tool=call["name"],
            input=clip(json.dumps(call["input"], ensure_ascii=False), 3000)))
        what = f"{call['name']} {clip(_describe(call), 160)}"
        if verdict.get("decision") == "approve":
            if not await self._still_waiting(a, call):
                log.info("%s: someone answered %s first", a.get("name"), call["name"])
                return
            rc, out = await tower.tmux("send-keys", "-t", a["pane"], "Enter")
            if rc:
                self.record(a, "failed to approve", out, what)
            else:
                self.record(a, "approved", verdict.get("reason", ""), what)
            return
        if verdict:
            self.escalate(a, "permission", f"{tower.say_name(a['name'])} wants to run {clip(_describe(call), 80)}. "
                                           f"{verdict.get('reason', '')}", what)
        else:
            self.escalate(a, "permission", f"{tower.say_name(a['name'])} needs approval and I couldn't judge it.", what)

    async def _question(self, a: dict, t: Transcript, call: dict):
        questions = call["input"].get("questions") or []
        shown = questions or [{"question": "(read it off the dialog on its screen)", "screen": call["input"].get("screen", "")}]
        b = self._brief(a)
        verdict = await self.judge(QUESTION.format(
            **b, context="\n".join(t.context) or "(nothing)",
            questions=clip(json.dumps(shown, ensure_ascii=False, indent=1), 4000)))
        answers = verdict.get("answers") or []
        if not (verdict.get("answer") and answers):
            asked = "; ".join(q.get("question", "") for q in questions) or "see its screen"
            self.escalate(a, "question", f"{tower.say_name(a['name'])} has a question for you: {clip(asked, 160)}",
                          verdict.get("reason", ""))
            return
        if not await self._still_waiting(a, call):
            return
        # Close the question box (Esc), then give the answers as my reply: sturdier than driving the box.
        await tower.tmux("send-keys", "-t", a["pane"], "Escape")
        for _ in range(10):
            await asyncio.sleep(0.5)
            if not await tower.dialog_open(a["pane"]):
                break
        lines = "\n".join(f"- {x.get('question', '')} -> {x.get('choice', '')}" for x in answers)
        text = f"[answered by my coordinator while I'm away] {lines}\nCarry on with those answers."
        ok, out = await self._send(a, text)
        self.record(a, "answered its question" if ok else "failed to answer", verdict.get("reason", "") or out, lines)

    async def _still_waiting(self, a: dict, call: dict) -> bool:
        """Between judging and acting, I may have answered it myself."""
        fresh = next((x for x in await tower.agents() if x.get("pane") == a.get("pane")), None)
        if not fresh or fresh.get("state") != "waiting" or not await tower.dialog_open(a["pane"]):
            return False
        if call["id"].startswith("screen:"):
            return fresh.get("activity") == a.get("activity")
        pending = (await read(fresh.get("transcript", ""))).pending
        return bool(pending and pending["id"] == call["id"])

    # ---- the end of a turn ------------------------------------------------------------------

    async def _turn_end(self, a: dict):
        key = ("turn", a.get("pane"), a.get("finished") or a.get("updated"))
        if key in self.handled:
            return
        self.handled.append(key)
        rc, reply = await tower.run("last", a["pane"])
        if rc or not reply.strip():
            return
        tail = reply[-2500:]
        if USAGE_LIMIT.search(tail[-600:]):
            self.record(a, "left it", "it hit a usage limit; nothing to do until it resets")
            return
        if CONTEXT_FULL.search(tail[-600:]):
            await self._compact(a, "its context is full")
            return
        if API_ERROR.search(tail[-400:]):
            await self._retry(a)
            return
        task = self.task(a)
        k = self.key(a)
        last_task, count = self.go_aheads.get(k, ("", 0))
        if last_task != task:
            count = 0
        if count >= GO_AHEAD_MAX:
            return
        verdict = await self.judge(TURN.format(**self._brief(a), reply=clip(tail, 2500)))
        action = verdict.get("action")
        if action == "continue" and verdict.get("message"):
            fresh = next((x for x in await tower.agents() if x.get("pane") == a.get("pane")), None)
            if not fresh or fresh.get("state") not in ("done", "idle") or fresh.get("finished") != a.get("finished"):
                return  # I got to it first
            ok, out = await self._send(a, f"[from my coordinator, while I'm away] {verdict['message']}")
            if ok:
                self.go_aheads[k] = (task, count + 1)
            self.record(a, "told it to go ahead" if ok else "failed to message", verdict.get("reason", "") or out,
                        verdict["message"])
        elif action == "ask":
            self.escalate(a, "decision", f"{tower.say_name(a['name'])} needs your call: {verdict.get('reason', '')}",
                          clip(tail[-600:], 600))

    async def _retry(self, a: dict):
        k = self.key(a)
        recent = [t for t in self.retries.get(k, []) if time.time() - t < 3600]
        if len(recent) >= RETRY_MAX:
            self.escalate(a, "error", f"{tower.say_name(a['name'])} keeps failing on API errors.")
            return
        self.retries[k] = recent + [time.time()]
        ok, out = await self._send(a, "That failed on an API error. Please continue where you left off.")
        self.record(a, "retried" if ok else "failed to retry", "its turn ended on an API error", out if not ok else "")

    async def _compact(self, a: dict, why: str):
        ok, out = await self._send(a, "/compact")
        self.record(a, "compacted its context" if ok else "failed to compact", why, out if not ok else "")
        if ok:
            asyncio.create_task(self._after_compact(a))

    async def _after_compact(self, a: dict):
        for _ in range(40):  # up to ten minutes
            await asyncio.sleep(15)
            fresh = next((x for x in await tower.agents() if x.get("pane") == a.get("pane")), None)
            if not fresh:
                return
            if fresh.get("state") in ("idle", "done"):
                screen = (await tower.run("peek", "-n", "15", a["pane"]))[1]
                if "compact" in screen.lower():
                    ok, _ = await self._send(fresh, "Continue where you left off.")
                    if ok:
                        self.record(fresh, "resumed it", "its context was compacted")
                return

    # ---- stalls -----------------------------------------------------------------------------

    async def _maybe_stalled(self, a: dict):
        t = await read(a.get("transcript", ""))
        quiet = time.time() - t.mtime if t.mtime else 0
        if quiet < STALL_S:
            return
        key = ("stall", a.get("pane"), int(t.mtime))
        if key in self.handled:
            return
        self.handled.append(key)
        rc, screen = await tower.run("peek", "-n", "60", a["pane"])
        if rc:
            return
        if CONTEXT_FULL.search(screen[-1500:]):
            await self._compact(a, "its context is full")
            return
        verdict = await self.judge(STALL.format(**self._brief(a), minutes=int(quiet // 60), screen=clip(screen, 5000)))
        action = verdict.get("action")
        if action == "interrupt":
            await tower.run("stop", a["pane"])
            await asyncio.sleep(2)
            ok, out = await self._send(a, verdict.get("message") or "That got stuck, so I interrupted it. Try another way.")
            self.record(a, "unstuck it", verdict.get("reason", ""), verdict.get("message", "") or out)
        elif action == "compact":
            await self._compact(a, verdict.get("reason", "its context is full"))
        elif action == "ask":
            self.escalate(a, "stuck", f"{tower.say_name(a['name'])} is stuck: {verdict.get('reason', '')}")
        elif action == "wait":
            self.record(a, "let it run", verdict.get("reason", "busy, not stuck"))

    # ---- folder trust ------------------------------------------------------------------------

    async def _trust(self, pane: str, a: dict | None = None) -> bool:
        if not await tower.trust_dialog(pane):
            return False
        rc, path = await tower.tmux("display-message", "-p", "-t", pane, "#{pane_current_path}")
        if rc or not path.startswith(str(Path.home())):
            return False
        if not await tower.accept_trust(pane):
            self.handled.append(("trust", pane))
            self.escalate(a or {"name": tower.short_path(path), "pane": pane}, "trust",
                          f"A new agent in {tower.short_path(path)} asks whether to trust the folder, and I couldn't answer it.")
            return False
        self.record(a or {"name": tower.short_path(path), "pane": pane}, "trusted the folder",
                    f"a new agent in {tower.short_path(path)} was stuck on the folder-trust question")
        return True

    async def _trust_prompts(self, items: list[dict]):
        """Agents stuck on the folder-trust question aren't in tower's list yet: look for them. A
        spawned agent often runs under a shell, so shells count too; _trust checks for the dialog."""
        rc, out = await tower.tmux("list-panes", "-a", "-F", "#{pane_id} #{pane_current_command}")
        if rc:
            return
        known = {a.get("pane") for a in items}
        for line in out.splitlines():
            pane, _, cmd = line.partition(" ")
            if cmd.strip() in SHELLS and pane not in known and ("trust", pane) not in self.handled:
                if await self._trust(pane):
                    self.handled.append(("trust", pane))

    # ---- agents and each other ----------------------------------------------------------------

    async def _clashes(self, items: list[dict], focused: str | None):
        """Two agents editing one file: tell both, once."""
        now = time.time()
        edits: dict[str, set[str]] = {}
        for a in items:
            if a.get("state") not in ("working", "waiting", "done"):
                continue
            for when, path in (await read(a.get("transcript", ""), 200_000)).edits:
                if now - when < OVERLAP_S:
                    edits.setdefault(path, set()).add(a.get("pane", ""))
        byp = {a.get("pane"): a for a in items}
        for path, panes in edits.items():
            if len(panes) < 2:
                continue
            key = ("clash", path, tuple(sorted(panes)))
            if key in self.warned:
                continue
            self.warned.add(key)
            for pane in panes:
                a = byp.get(pane)
                others = [byp[p]["name"] for p in panes if p != pane and p in byp]
                if a and not self._skip(a, focused):
                    text = (f"[note from my coordinator] {', '.join(others)} is editing {tower.short_path(path)} too. "
                            f"Check with them before you change it again (tower send {others[0]} \"...\").")
                    asyncio.create_task(self._note(a, text, f"{', '.join(others)} also edits {tower.short_path(path)}"))

    async def _note(self, a: dict, text: str, reason: str):
        ok, out = await self._send(a, text, busy_ok=True)
        self.record(a, "warned it" if ok else "failed to warn", reason, text if ok else out)

    async def _review(self, items: list[dict], focused: str | None):
        active = [a for a in items if a.get("state") in ("working", "waiting", "done")]
        if len(active) < 2:
            return
        fleet = []
        for a in items:
            rc, reply = await tower.run("last", a["pane"])
            fleet.append({**self._brief(a), "state": a.get("state"), "doing": clip(a.get("activity", ""), 160),
                          "last_reply": clip(reply[-700:] if not rc else "", 700)})
        fingerprint = json.dumps([(f["name"], f["state"], f["last_reply"][-120:]) for f in fleet])
        if fingerprint == self.review_print:
            return
        self.review_print = fingerprint
        verdict = await self.judge(REVIEW.format(fleet=json.dumps(fleet, ensure_ascii=False, indent=1)),
                                   model=models.ROLES["review"])
        byname = {a.get("name", "").lower(): a for a in items}
        for m in (verdict.get("messages") or [])[:2]:
            a = byname.get(str(m.get("to", "")).lower())
            if not a or self._skip(a, focused) or a.get("state") == "waiting":
                continue
            await self._note(a, f"[note from my coordinator] {m.get('text', '')}", m.get("reason", ""))

    # ---- acting -----------------------------------------------------------------------------

    async def _send(self, a: dict, text: str, busy_ok: bool = False) -> tuple[bool, str]:
        """Type a message into an agent's prompt. Never while it sits on a permission prompt: the
        Enter would approve whatever is pending."""
        fresh = next((x for x in await tower.agents() if x.get("pane") == a.get("pane")), a)
        if await tower.dialog_open(a["pane"]):
            return False, "it is on a prompt"
        # tower refuses an agent it thinks is waiting; with no dialog on screen that state is stale
        stale = fresh.get("state") == "waiting"
        flags = ["--force"] if stale or (busy_ok and fresh.get("state") == "working") else []
        for attempt in (1, 2):
            rc, out = await tower.run("send", *flags, a["pane"], text)
            if rc == 0:
                self.sent.setdefault(a.get("pane", ""), set()).add(text.strip())
                return True, out
            await asyncio.sleep(2)
        return False, out

    async def resolve(self, pane: str, decision: str, note: str = "") -> str:
        """My answer to something it escalated, from the panel or the voice."""
        item = self.pending.get(pane)
        a = next((x for x in self.items if x.get("pane") == pane), None)
        if not a:
            return "That agent is gone."
        if item and item.get("kind") not in ("permission", "question", "waiting"):
            self.pending.pop(pane, None)
            if decision == "approve":
                ok, out = await self._send(a, note or "Yes, go ahead.")
                self.record(a, "told it to go ahead (my call)" if ok else "failed to message", item.get("text", ""))
                return f"Told {a['name']} to go ahead." if ok else out
            self._changed()
            return "Dismissed."
        if a.get("state") != "waiting":
            self.pending.pop(pane, None)
            self._changed()
            return f"{a['name']} isn't waiting any more."
        if decision == "approve":
            rc, out = await tower.tmux("send-keys", "-t", pane, "Enter")
            what = "approved"
        else:
            rc, out = await tower.tmux("send-keys", "-t", pane, "Escape")
            what = "denied"
            if not rc and note:
                await asyncio.sleep(1.5)
                await tower.run("send", pane, note)
        self.pending.pop(pane, None)
        self.record(a, f"{what} (my call)", note or (item or {}).get("text", ""))
        return out if rc else f"{what.capitalize()} {a['name']}."

    def report(self) -> str:
        """For the voice: what each agent is doing, what's waiting on me, what the coordinator did."""
        lines = [f"Coordinator {'on' if self.enabled else 'off'}."]
        for p in self.pending.values():
            lines.append(f"Waiting on me: {p['text']}")
        for e in list(self.log)[-8:]:
            ago = tower.ago(e["ts"])
            lines.append(f"{ago}: {e['action']} for {e['agent']}: {e['reason']}")
        return "\n".join(lines)


def short_model(model_id: str) -> str:
    """claude-sonnet-5-5 -> Sonnet 5.5"""
    m = re.match(r"claude-([a-z]+)-(\d+)-(\d+)", model_id or "")
    return f"{m.group(1).capitalize()} {m.group(2)}.{m.group(3)}" if m else ""


def _from_screen(a: dict, screen: str) -> dict | None:
    """A pending call rebuilt from tower's activity and the dialog on the agent's screen."""
    activity = str(a.get("activity", ""))
    if not activity.startswith("permission:"):
        return None
    rest = activity.removeprefix("permission:").strip()
    name, _, summary = rest.partition(" ")
    return {"id": f"screen:{a.get('pane')}:{a.get('turn_started')}:{rest}", "name": name or "unknown",
            "input": {"summary": summary, "screen": tower.bottom(screen, 25)}}


def _describe(call: dict) -> str:
    inp = call.get("input") or {}
    for key in ("command", "file_path", "url", "pattern", "query", "description", "summary"):
        if inp.get(key):
            return str(inp[key])
    return json.dumps(inp, ensure_ascii=False)
