"""The assistant: one long-lived Claude Code session through the Agent SDK, with fleet tools and pc."""

import asyncio
import glob
import json
import logging
import re
import shutil
import socket
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    StreamEvent,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    create_sdk_mcp_server,
    tool,
)

from . import models, policy, tower
from .config import RUNTIME_DIR
from .speech import SENTENCE_END, Chunker, clip

log = logging.getLogger("claudebot_voice.brain")
SESSION_FILE = RUNTIME_DIR / "session"

# A fresh session starts before the conversation gets near the model's 200k context. Screenshots
# fill it fast, and a full context makes every turn fail with "Prompt is too long".
ROTATE_AT = 130_000

# Status lines belong on screen, not in my ears: the pet and the panel show what is going on.
FILLER = re.compile(r"^(ok(ay)?[,.]? )?(checking|looking|on it|one sec(ond)?|one moment|hang on|working on it|"
                    r"let me (check|look|see)( that| into that)?|give me a (sec|second|moment))\W*$", re.I)
PC_STATUS = {"screenshot": "Looking at the screen", "screen_record": "Recording the screen", "windows": "Checking windows", "system_state": "Checking the system",
             "system_events": "Checking recent events", "processes": "Checking processes", "process_info": "Checking a process",
             "services": "Checking services", "logs": "Reading logs", "ports": "Checking ports", "system_info": "Checking the system",
             "open_app": "Opening an app", "focus_window": "Switching windows", "close_window": "Closing a window",
             "switch_workspace": "Switching workspace", "wait_for": "Waiting"}
BUILTIN_TOOLS = ["Bash", "Read", "Glob", "Grep", "WebSearch", "WebFetch", "Write", "Edit"]

SYSTEM = """You are {name}, the voice of my Linux workstation ({host}: Arch Linux, Hyprland, tmux). I talk to you out loud through speech to text, and everything you write is spoken by a text to speech voice.

How to answer:
- Answer in {length}, even when there is a lot to say: pick what matters most. Lead with it; no preamble, no offers, no questions back unless you need my decision. When several things matter (several agents, several results), fit them into that, most urgent first.
- Never write anything before or between tool calls: no "I'll check", "Let me look", "Checking", "On it". Call the tools without a word; the screen shows what you are doing, and only your final words are spoken.
- When I ask you to do something, do it, then answer once it is done. After a simple action I can see or hear for myself (music, a page, an app, a window, the pet), write nothing at all. Speak up when something failed or needs my decision.
- Plain spoken words only: no markdown, lists, code, emoji, URLs, paths, hashes or IDs. Say what things mean.
- Answer directly from what you know whenever no live state is needed: small talk, facts, arithmetic, definitions, the date. Use a tool only when the answer depends on my agents, my machine, my files or the web.
- Never repeat something you already said. If a tool fails twice, stop and tell me why.
- Speech to text mishears names: "Claudia Bot" is probably the agent claudebot, "tau er" is tower.
- Dry, quick and calm, like a good chief of staff. No filler, no apologies.

What you run:
- The fleet: Claude Code agents in my tmux panes, through the fleet tools (tower). fleet_status also says what each one has done, what's next, what blocks it and what it needs. For a question about one agent, call agent_context and answer about that agent only. Sum it up in plain words, whoever is waiting on me first. "waiting" means blocked on me; "done" means finished and unread. Mention idle agents only if I ask about everything.
- The coordinator looks after the fleet for me: it approves safe permission prompts, answers their questions when I don't, tells them to go ahead, recovers stalls and errors, and asks me about anything risky. coordinator_report tells what it did and what waits on me; coordinator_answer gives my answer to something it asked ("approve it", "no, tell it to use the staging database"); coordinator_set turns it on or off, or keeps it away from an agent.
- My desktop through the pc tools, like Claude Code does: do things yourself instead of telling me how. Orient with windows (cheap text), screenshot only when you need to see or need coordinates (x and y are pixels of the latest screenshot; aim at the middle of a control). Prefer press_keys and paste_text (pass window= to target one) over clicks, chain known steps in one act call, wait_for instead of sleeping. system_state first for questions about the machine. Never click through consent, payment or destructive dialogs on your own; if I tell you to stop controlling my computer, call input_disable (a plain "stop" only stops your speech, and never reaches you).
- A shell, files and the web. Give every Bash call a short description.
- Each message from me starts with a bracketed line of live context: the time, my focused window, the music, agents that are busy or waiting, the agent we last talked about ("it", "that one"), and for questions about agents what they are doing and need. It is live: when it answers my question, answer straight from it without a tool call. Never read it out.
- Shortcuts: open_url with the final URL for any site or search; music_play and music_control for music (it plays here, under your voice, and ducks while either of us talks; pick a sensible query when I'm vague); play_youtube for a video to watch; open_app for apps.
- You live in Claude Bot, the pixel creature on my screen, so you and the pet are the same: "fly", "dance", "hide" and the like, said to you or to the pet, mean pet_action. Don't ask, just do it.
- Screenshots fill your memory fast: orient with windows first, and take a low-detail screenshot unless you must read small text.

Risky actions go through an approval I answer out loud; don't ask me yourself, just call the tool, and accept a no. A message may start with a bracketed note of what happened since my last message (fleet events, things handled without you); it is background, so mention it only when it answers what I asked.
{memory}
It is {date}. My home folder is {home}."""


MEMORY = """
Memory: you keep a long-term memory of me across conversations, stored on this machine.
- When I tell you something durable about me (a fact, a preference, a project I am working on, a person in my life) or ask you to remember something, call remember right away, in your own words, one short self-contained sentence. Do not announce it unless I asked you to remember.
- When something you remember changes or I ask you to forget it, call forget, then remember the new version.
- Skip small talk, one-off requests and anything you could look up.
- Use what you remember naturally, without saying "I remember that".
- The tasks you do for me are logged on their own; never remember them yourself.
What you remember so far:
{memories}
What you did for me before, oldest first. It tells you what is already done or under way; check live state before you rely on it:
{tasks}
"""
LENGTH = {1: "one sentence", 2: "at most two sentences", 3: "at most three sentences"}

# Actions whose result I see or hear for myself: a turn that only did these stays silent unless one failed.
SIMPLE = {"pet_action", "music_play", "music_control", "open_url", "play_youtube", "open_app", "focus_window",
          "switch_workspace", "agent_show"}
# Tools that only look. Together with the simple actions, they never make a turn worth logging as a task.
LOOK = {"fleet_status", "agent_last_reply", "agent_screen", "remember", "forget", "coordinator_report",
        "agent_context"} | policy.READ_TOOLS


def weight(name: str, inp: dict) -> str:
    """'look', 'simple' or 'task' for one tool call."""
    short = name.rpartition("__")[2]
    if short == "music_control" and inp.get("action") == "status":
        return "look"
    if short in SIMPLE:
        return "simple"
    if short in LOOK or (name == "Bash" and policy.bash_is_safe(inp.get("command") or "")):
        return "look"
    if name.startswith("mcp__pc__") and (short not in policy.PC_ASK or (short == "clipboard" and not inp.get("text"))):
        return "look"
    return "task"


def did(name: str, inp: dict) -> str:
    """One tool call in the past tense, for the task log."""
    short = name.rpartition("__")[2]
    agent = tower.say_name(str(inp.get("agent", ""))) or "an agent"
    if short == "agent_spawn":
        named = f" named {inp['name']}" if inp.get("name") else ""
        where = f" in {inp['dir']}" if inp.get("dir") else ""
        model = inp.get("model") if inp.get("model") in models.CHOICES else models.pick(inp.get("task", ""))[0]
        text = f"started an agent{named}{where} on {model} for: {inp.get('task', '')}"
    else:
        text = {
            "agent_send": f"told {agent}: {inp.get('message', '')}" + (
                f" (with {', '.join(inp.get('attach') or [])}{' and a screenshot' if inp.get('screenshot') else ''})"
                if inp.get("attach") or inp.get("screenshot") else ""),
            "agent_interrupt": f"interrupted {agent}",
            "agent_approve": f"approved {agent}'s prompt",
            "Bash": f"ran {inp.get('description') or inp.get('command', '')}",
            "Write": f"wrote {inp.get('file_path', '')}",
            "Edit": f"edited {inp.get('file_path', '')}",
        }.get(short) or f"{short.replace('_', ' ')} {brief(inp)}"
    return re.sub(r"\s+", " ", text).strip()[:160]


# A question about the fleet as a whole ("what are my agents doing?", "anyone need me?").
FLEET_Q = re.compile(r"\b(agents?|fleet|everyone|everybody|anyone|anybody|who'?s (working|waiting|busy|stuck)|"
                     r"needs? me|waiting on me|blocked|stuck)\b", re.I)

# How a message that ends up before a tool call usually starts: "I'll check", "Let me look", "Opening it".
PREAMBLE = re.compile(r"^(?:(?:ok(?:ay)?|sure|alright|right)[,.!]?\s+)?(?:i'?ll|i will|let me|let's|i'm going to|"
                      r"i am going to|one (?:sec|second|moment)|give me|hold on|on it|checking|looking|opening|"
                      r"playing|starting|launching|switching|searching|pulling up|getting|first,? i)\b", re.I)


class Speaker:
    """Speaks a turn's reply while the model is still writing it.

    The first words of each message decide: one that opens like a preamble ("I'll check", "Opening
    it") is held until the message ends, and dropped if a tool call follows it. Anything else goes to
    the voice clause by clause as it streams, so the first word plays while the rest is written. Only
    the first few sentences are spoken (the Answers setting), never the same one twice, and nothing
    after a simple action I can see or hear for myself. The transcript gets every word."""

    def __init__(self, hub, turn_id: int, work):
        self.hub, self.turn_id, self.work = hub, turn_id, work
        self.limit = hub.settings.get("sentences", 1)
        self.said: set[str] = set()
        self.start()

    def start(self):
        """A new message from the model."""
        self.text = ""
        self.fed = 0
        self.chunker = Chunker()
        self.tool = False
        self.mode = None  # None while deciding, then "speak" or "hold"
        self.spoke = False

    def delta(self, piece: str):
        self.text += piece
        if self.tool:
            return
        if self.mode is None:
            if len(self.text.split()) < 4 and not SENTENCE_END.search(self.text):
                return  # too early to tell a preamble from an answer
            self.mode = "hold" if PREAMBLE.match(self.text.lstrip()) else "speak"
        if self.mode == "speak":
            self._feed(final=False)

    def tool_call(self):
        self.tool = True

    def stop(self):
        """The message ended."""
        text = self.text.strip()
        if not text:
            return
        if self.tool:
            if self.spoke:
                self.hub.reply(self.turn_id, text)
            else:
                log.debug("dropped a preamble: %r", text[:200])
            return
        self._feed(final=True)
        self.hub.reply(self.turn_id, text)
        self.work.answer = text

    def _feed(self, final: bool):
        if self.work.silent:
            return
        allowed = clip(self.text, self.limit)  # stops growing once the sentence cap is reached
        new, self.fed = allowed[self.fed:], len(allowed)
        parts = self.chunker.feed(new) + (self.chunker.flush() if final else [])
        for part in parts:
            key = re.sub(r"\W+", " ", part.lower()).strip()
            if not key or key in self.said or FILLER.match(part.strip()):
                continue
            self.said.add(key)
            self.spoke = True
            self.hub.mark("first_chunk", self.turn_id)
            self.hub.say(part, self.turn_id)


@dataclass
class Work:
    """What one turn did: whether it may stay silent, and what goes in the task log."""
    tools: int = 0
    simple: bool = True  # every tool call so far was a simple action
    failed: bool = False
    actions: list[str] = field(default_factory=list)
    calls: dict[str, int] = field(default_factory=dict)  # tool_use id -> index in actions
    answer: str = ""

    def call(self, block: ToolUseBlock):
        self.tools += 1
        w = weight(block.name, block.input)
        self.simple = self.simple and w == "simple"
        if w == "task":
            self.calls[block.id] = len(self.actions)
            self.actions.append(did(block.name, block.input))

    def result(self, block: ToolResultBlock):
        if not block.is_error:
            return
        self.failed = True
        i = self.calls.pop(block.tool_use_id, None)
        if i is not None:
            self.actions[i] += " (it failed or I said no)"

    @property
    def silent(self) -> bool:
        return self.tools > 0 and self.simple and not self.failed


# Everything the pet in Claude Bot can act out (what brain.play accepts in src/brain.js), and the
# words I am likely to use for them.
PET = {
    "moves": ["fly", "dance", "walk", "zoomies", "chase", "hop", "wave", "sit", "stretch", "yawn", "trip", "sneeze", "look",
              "drop", "throw", "explore"],
    "games": ["fetch", "fetch:stop"],
    "gestures": ["stones", "kick", "juggle", "flex", "kiss"],
    "screens": ["monitor:other", "monitor:left", "monitor:right", "split"],
    "reactions": ["hello", "celebrate", "dizzy", "shrug", "oops", "giggle", "poke", "notice", "remind"],
    "scenes": ["idle", "sleeping", "thinking", "building", "testing", "typing", "reading", "searching", "surfing",
               "planning", "delegating", "alert", "waiting", "done", "compacting", "error", "agent"],
    "places": ["hide", "peek", "peek:left", "peek:right", "peek:top", "peek:bottom", "edge:left", "edge:right",
               "edge:top", "edge:bottom", "corner:top-left", "corner:top-right", "corner:bottom-left",
               "corner:bottom-right", "home"],
    "thinking styles": ["think:bubble", "think:ponder", "think:pontificate", "think:cook", "think:wizard", "think:vibe",
                        "think:gears", "think:hatch", "think:spin", "think:wander", "think:garden", "think:space",
                        "think:weather", "think:doodle", "think:forge"],
}
PET_NAMES = {name for names in PET.values() for name in names}
PET_WORDS = {
    "levitate": "think:space", "float": "think:space", "hyperspace": "think:space", "jump": "hop", "run": "zoomies",
    "run around": "zoomies", "follow me": "chase", "follow the cursor": "chase", "sleep": "sleeping", "nap": "sleeping",
    "go to sleep": "sleeping", "wake up": "idle", "stop": "idle", "relax": "idle", "party": "celebrate",
    "confetti": "celebrate", "hi": "hello", "say hi": "hello", "spin": "think:spin", "cook": "think:cook",
    "magic": "think:wizard", "wizard": "think:wizard", "vibe": "think:vibe", "garden": "think:garden",
    "storm": "think:weather", "rain": "think:weather", "doodle": "think:doodle", "build": "building",
    "hammer": "building", "type": "typing", "read": "reading", "search": "searching", "surf": "surfing",
    "think": "thinking", "fall over": "trip", "trip over": "trip", "subagent": "agent", "helper": "agent",
    "hide away": "hide", "go hide": "hide", "peek out": "peek", "come out": "peek", "come back": "home",
    "come home": "home", "go home": "home", "back to the floor": "home",
    "fall": "drop", "fall down": "drop", "toss": "throw", "throw yourself": "throw", "throw stones": "stones",
    "skip stones": "stones", "kick the ball": "kick", "kick a ball": "kick", "play football": "kick",
    "show your muscles": "flex", "blow a kiss": "kiss", "blow me a kiss": "kiss", "go explore": "explore",
    "play fetch": "fetch", "let's play fetch": "fetch", "lets play fetch": "fetch", "play with me": "fetch",
    "let's play": "fetch", "lets play": "fetch", "play ball": "fetch", "stop playing": "fetch:stop",
    "game over": "fetch:stop", "stop fetch": "fetch:stop", "put the ball away": "fetch:stop",
    "other screen": "monitor:other", "other monitor": "monitor:other", "left screen": "monitor:left",
    "left monitor": "monitor:left", "right screen": "monitor:right", "right monitor": "monitor:right",
}
SIDES = {"left": "left", "right": "right", "top": "top", "up": "top", "bottom": "bottom", "down": "bottom"}


def pet_place(a: str) -> str | None:
    """'peek from the left', 'go to the top right corner', 'sit on the right edge' and so on."""
    words = re.findall(r"[a-z]+", a)
    sides = [SIDES[w] for w in words if w in SIDES]
    if "corner" in words or len(sides) == 2:
        v = next((s for s in sides if s in ("top", "bottom")), None)
        h = next((s for s in sides if s in ("left", "right")), None)
        return f"corner:{v}-{h}" if v and h else None
    if not sides:
        return None
    if "peek" in words or "peeking" in words:
        return f"peek:{sides[0]}"
    return f"edge:{sides[0]}"


def pet_name(action: str) -> str | None:
    a = action.strip().lower().replace("_", " ").removeprefix("the ")
    if a in PET_NAMES:
        return a
    if a in PET_WORDS:
        return PET_WORDS[a]
    styled = "think:" + a.removeprefix("think ").strip()
    if styled in PET_NAMES:
        return styled
    return pet_place(a)


def pc_root() -> Path | None:
    found = sorted(glob.glob(str(Path.home() / ".claude/plugins/cache/pc/pc/*/bin/pc")))
    return Path(found[-1]).parents[1] if found else None


def pc_binary() -> str | None:
    root = pc_root()
    return str(root / "bin" / "pc") if root else shutil.which("pc")


async def trust_prompt(target: str) -> bool:
    """Is this pane sitting on Claude Code's "do you trust this folder" question? Tower only starts
    tracking an agent once it is past it."""
    return await tower.trust_dialog(target)


SHARED = Path.home() / ".local/share/claudebot/shared"  # screenshots I hand to agents, kept for them to open


async def screenshot(target: str = "focused") -> str | None:
    """A screenshot saved where another agent can open it: my focused monitor, all of them, one
    monitor by name, or a window by class or title."""
    SHARED.mkdir(parents=True, exist_ok=True)
    path = SHARED / f"shot-{time.strftime('%Y%m%d-%H%M%S')}-{int(time.time() * 1000) % 1000:03d}.png"
    t = (target or "focused").strip()

    async def hypr(what: str):
        proc = await asyncio.create_subprocess_exec("hyprctl", what, "-j", stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.DEVNULL)
        out, _ = await proc.communicate()
        return json.loads(out or b"[]")

    cmd = ["grim"]
    if t.lower() != "all":
        monitors = await hypr("monitors")
        mon = next((m for m in monitors if m["name"].lower() == t.lower()), None)
        if t.lower() in ("focused", "screen", "true", ""):
            mon = next((m for m in monitors if m.get("focused")), None)
        if mon:
            cmd += ["-o", mon["name"]]
        else:
            low = t.lower()
            win = next((c for c in await hypr("clients")
                        if low in str(c.get("class", "")).lower() or low in str(c.get("title", "")).lower()), None)
            if not win:
                return None
            (x, y), (w, h) = win["at"], win["size"]
            cmd += ["-g", f"{x},{y} {w}x{h}"]
    proc = await asyncio.create_subprocess_exec(*cmd, str(path), stdout=asyncio.subprocess.DEVNULL,
                                                stderr=asyncio.subprocess.DEVNULL)
    return str(path) if await proc.wait() == 0 and path.exists() else None


async def spawn(*cmd: str):
    """Start a desktop program detached from me."""
    await asyncio.create_subprocess_exec(*cmd, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                                         stderr=asyncio.subprocess.DEVNULL, start_new_session=True)


def ok(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


def fail(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "is_error": True}


def status(name: str, inp: dict) -> str:
    """What the pet and the panel show while a tool runs."""
    server, _, tool = name.removeprefix("mcp__").rpartition("__")
    tool = tool or name
    agent = tower.say_name(str(inp.get("agent", ""))) or "an agent"
    whose = f"{agent}'s" if inp.get("agent") else "an agent's"
    if server == "pc":
        return PC_STATUS.get(tool, "Using the desktop")
    return {
        "fleet_status": "Checking the fleet",
        "agent_last_reply": f"Reading {whose} reply",
        "agent_screen": f"Looking at {agent}",
        "agent_send": f"Messaging {agent}",
        "agent_spawn": "Starting an agent",
        "agent_interrupt": f"Stopping {agent}",
        "agent_approve": f"Approving {agent}",
        "agent_show": f"Showing {agent}",
        "open_url": "Opening a page",
        "play_youtube": "Opening YouTube",
        "music_play": f"Finding {inp.get('query') or 'music'}",
        "music_control": f"Music: {inp.get('action', '')}".strip(": "),
        "remember": "Remembering",
        "coordinator_report": "Checking the coordinator",
        "agent_context": f"Reading up on {agent}",
        "coordinator_answer": f"Answering {agent}",
        "coordinator_set": "Setting up the coordinator",
        "pet_action": f"Pet: {str(inp.get('action', '')).removeprefix('think:')}".strip(": "),
        "forget": "Forgetting",
        "Bash": str(inp.get("description") or "Running a command"),
        "Read": "Reading a file",
        "Grep": "Searching files",
        "Glob": "Searching files",
        "Write": "Writing a file",
        "Edit": "Editing a file",
        "WebSearch": "Searching the web",
        "WebFetch": "Reading a page",
    }.get(tool, tool.replace("_", " ").capitalize())[:80]


def brief(inp: dict) -> str:
    for key in ("description", "command", "agent", "query", "url", "file_path", "pattern", "app", "text"):
        if inp.get(key):
            return str(inp[key])[:120]
    return json.dumps(inp, ensure_ascii=False)[:120]


class Brain:
    def __init__(self, hub):
        self.hub = hub
        self.client: ClaudeSDKClient | None = None
        self.lock = asyncio.Lock()
        self.connecting = asyncio.Lock()
        self.notes: list[str] = []
        self.busy = False
        self.context_tokens = 0  # how full the session's context was on its last API call
        self.session_id = ""
        self.cost = 0.0
        self.last_agent = ""  # the agent I last asked about or gave something to: what "it" means next
        self.recap_next = False  # the session was started fresh after the last turn: catch it up
        self.server = create_sdk_mcp_server(name="jarvis", version="1.0.0", tools=self._tools())

    # ---- session -------------------------------------------------------------------------

    def options(self) -> ClaudeAgentOptions:
        s = self.hub.settings
        servers = {"jarvis": self.server}
        pc = pc_binary()
        if pc:
            servers["pc"] = {"type": "stdio", "command": pc, "args": ["mcp"]}
        return ClaudeAgentOptions(
            model=s["model"],
            system_prompt=SYSTEM.format(
                name=s["name"], host=socket.gethostname(), home=str(Path.home()),
                date=time.strftime("%A %-d %B %Y"), memory=self._memory_block(),
                length=LENGTH.get(s.get("sentences"), LENGTH[1]),
            ),
            tools=BUILTIN_TOOLS,
            mcp_servers=servers,
            strict_mcp_config=True,  # without it the claude.ai connectors load too: 60s+ start, huge prompts
            setting_sources=[],  # no user hooks or plugins: tower must not mistake me for a tmux agent
            include_partial_messages=True,
            thinking={"type": "disabled"},
            can_use_tool=self.hub.permit,
            cwd=s["cwd"],
            env={"TMUX_PANE": ""},
            stderr=lambda line: log.debug("cli: %s", line.rstrip()),
            resume=self._saved_session() or None,  # a server restart keeps the conversation
        )

    def _memory_block(self) -> str:
        if not self.hub.settings.get("memory", True):
            return ""
        return MEMORY.format(memories=self.hub.memory.prompt(), tasks=self.hub.memory.prompt(tasks=True))

    def _log_task(self, request: str, work: Work):
        """Keep what this turn did in long-term memory, so a later session knows it happened."""
        if not work.actions or not self.hub.settings.get("memory", True):
            return
        text = f'I asked "{request[:160]}". You {"; ".join(work.actions)[:240]}.'
        if work.answer:
            text += f' You said "{clip(work.answer, 1)[:100]}"'
        self.hub.memory.add(text, "task")
        self.hub.memory_changed()

    def _saved_session(self) -> str:
        try:
            return SESSION_FILE.read_text().strip()
        except OSError:
            return ""

    def _save_session(self, session_id: str):
        if session_id and session_id != self.session_id:
            SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
            SESSION_FILE.write_text(session_id)

    async def connect(self):
        async with self.connecting:
            if self.client:
                return
            client = ClaudeSDKClient(options=self.options())
            try:
                # a resume can hang (a huge saved session, one that ended on an error); the voice is
                # dead until this returns, so it gets a deadline like any other failure
                await asyncio.wait_for(client.connect(), 45)
            except Exception:
                if not self._saved_session():
                    raise
                log.warning("could not resume the last session, starting fresh")
                try:
                    await client.disconnect()
                except Exception:
                    log.debug("disconnect after a failed resume failed", exc_info=True)
                SESSION_FILE.unlink(missing_ok=True)
                client = ClaudeSDKClient(options=self.options())
                await client.connect()
            self.client = client
            log.info("claude session up (model %s)", self.hub.settings["model"])

    async def close(self):
        client, self.client = self.client, None
        if client:
            try:
                await client.disconnect()
            except Exception:
                log.debug("disconnect failed", exc_info=True)

    async def reset(self):
        await self.interrupt()
        async with self.lock:
            await self.close()
            self.notes.clear()
            self.session_id = ""
            SESSION_FILE.unlink(missing_ok=True)
        asyncio.create_task(self.warm())

    async def warm(self):
        try:
            await self.connect()
        except Exception:
            log.exception("could not start claude")

    async def set_model(self, model: str):
        if self.client and not self.busy:
            try:
                await self.client.set_model(model)
                return
            except Exception:
                log.debug("set_model failed, reconnecting", exc_info=True)
        await self.restart()

    async def restart(self):
        async with self.lock:
            await self.close()
        asyncio.create_task(self.warm())

    async def interrupt(self):
        if self.client and self.busy:
            try:
                await self.client.interrupt()
            except Exception:
                log.debug("interrupt failed", exc_info=True)

    # ---- one turn ------------------------------------------------------------------------

    async def _context(self, text: str = "") -> str:
        """One line of what's true right now, ahead of each message: the session's own idea of the date
        is from when it started, and it can't see my screen or the fleet without a tool call."""
        hub = self.hub
        parts = [time.strftime("%A %-d %B, %H:%M")]
        try:
            proc = await asyncio.create_subprocess_exec("hyprctl", "activewindow", "-j", stdout=asyncio.subprocess.PIPE,
                                                        stderr=asyncio.subprocess.DEVNULL)
            out, _ = await asyncio.wait_for(proc.communicate(), 0.3)
            w = json.loads(out or b"{}")
            if w.get("class"):
                parts.append(f'focused: {w["class"]} "{str(w.get("title", ""))[:60]}"')
        except (OSError, ValueError, TimeoutError):
            pass
        m = hub.music.state()
        if m["playing"] or m["paused"]:
            parts.append(f'music: {"paused" if m["paused"] else "playing"} "{m["title"][:50]}"')
        busy = [f'{a["name"]} {a["state"]}' + (f' ({str(a.get("activity", ""))[:50]})' if a["state"] == "waiting" else "")
                for a in hub.fleet if a.get("state") in ("working", "waiting")]
        if busy:
            parts.append("agents: " + ", ".join(busy[:6]))
        asks = [p["text"] for p in hub.coordinator.pending.values()]
        if asks:
            parts.append("the coordinator waits on me: " + "; ".join(a[:90] for a in asks[:2]))
        # an agent I name: its profile right here, so the answer needs no tool call
        squash = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
        said = squash(text)
        for a in hub.fleet:
            if len(squash(a["name"])) >= 3 and squash(a["name"]) in said:
                self.last_agent = a["name"]
                p = next((p for p in hub.coordinator.profiles.values() if p.get("pane") == a.get("pane")), {})
                facts = [f"{a['name']} is {a.get('state')}"] + [f"{label}: {p[k]}" for k, label in (
                    ("task", "task"), ("summary", "so far"), ("next", "next"), ("blocked_on", "blocked on"),
                    ("needs", "needs")) if p.get(k)]
                parts.append("about " + ". ".join(facts)[:700])
        if not any(p.startswith("about ") for p in parts) and FLEET_Q.search(text):
            # a question about the fleet as a whole: the profiles answer it, no tool call needed
            lines = []
            # whoever waits on me first, then anyone blocked or in need, then the rest
            urgency = lambda p: (p.get("state") != "waiting", not (p.get("needs") or p.get("blocked_on")),
                                 p.get("state") != "working")
            for p in sorted(hub.coordinator.profiles.values(), key=urgency):
                if p.get("state") in ("working", "waiting", "done"):
                    bits = [f"{p['name']} {p['state']}"] + [p[k] for k in ("summary", "blocked_on", "needs") if p.get(k)]
                    lines.append(" - ".join(bits)[:260])
            if lines:
                parts.append("fleet now: " + " | ".join(lines)[:1400])
        if self.last_agent:
            parts.append(f"last agent we talked about: {self.last_agent}")
        return "[" + "; ".join(parts) + "]\n"

    async def _fresh(self, why: str):
        """Drop the session and start a new one (long-term memory comes back through the prompt)."""
        log.warning("starting a fresh claude session: %s", why)
        await self.close()
        self.session_id = ""
        self.context_tokens = 0
        SESSION_FILE.unlink(missing_ok=True)

    def _recap(self) -> str:
        """The last few exchanges, so a fresh session can pick up the thread."""
        lines = []
        for e in list(self.hub.history)[-24:]:
            if e["role"] in ("user", "assistant") and not e.get("cut"):
                who = "Me" if e["role"] == "user" else "You"
                lines.append(f"{who}: {e['text'][:300]}")
        text = "\n".join(lines[-10:])[-2500:]
        if not text:
            return ""
        return "[This is a fresh session; the earlier one ran out of room. The last few exchanges were:\n" + text + "]\n"

    async def turn(self, text: str, turn_id: int):
        hub = self.hub
        async with self.lock:
            self.busy = True
            work = Work()
            speaker = Speaker(hub, turn_id, work)
            self.last_event = time.monotonic()
            watchdog = asyncio.create_task(self._watch(turn_id))

            try:
                context = await self._context(text)
                prompt = context + text
                # a question about one agent gets that agent's facts, not the news about everyone else;
                # the news waits for the next message
                about_one = "; about " in context
                if self.notes and not about_one:
                    prompt = "[since my last message: " + " ".join(self.notes) + "]\n" + prompt
                    self.notes.clear()
                if self.recap_next:
                    self.recap_next = False
                    prompt = self._recap() + prompt
                for attempt in (1, 2):
                    await self.connect()
                    overflow = await self._ask(prompt, turn_id, speaker, work)
                    if not overflow:
                        break
                    if attempt == 2:
                        hub.say("My memory of this conversation is full and I couldn't start over. Try again.", turn_id)
                        break
                    # the context is full and every turn would fail from here on: start over and retry
                    await self._fresh("prompt is too long")
                    prompt = self._recap() + prompt
            except Exception as e:
                log.exception("turn failed")
                await self.close()
                hub.log("system", f"Claude error: {e}")
                hub.say("Something broke on my side. Try that again.", turn_id)
            finally:
                watchdog.cancel()
                self.busy = False
                hub.tool("", "")
                try:
                    self._log_task(text, work)
                except Exception:
                    log.exception("could not log the task")
                # housekeeping goes between turns, not on the next one's clock
                if self.context_tokens > ROTATE_AT or self.client is None:
                    asyncio.create_task(self._between_turns())

    async def _between_turns(self):
        """A session nearly out of room starts fresh now, and a broken one reconnects now, so my next
        question doesn't wait for a new Claude Code process."""
        async with self.lock:
            if self.context_tokens > ROTATE_AT:
                await self._fresh(f"context at {self.context_tokens} tokens")
                self.recap_next = True
            if self.client is None:
                try:
                    await self.connect()
                except Exception:
                    log.exception("could not reconnect")

    async def _ask(self, prompt: str, turn_id: int, speaker: Speaker, work: Work) -> bool:
        """One query, its answer spoken as it streams (see Speaker). True when the session's context
        was full."""
        hub = self.hub
        overflow = False
        await self.client.query(prompt)
        async for m in self.client.receive_response():
            self.last_event = time.monotonic()
            if isinstance(m, StreamEvent):
                if m.parent_tool_use_id:
                    continue
                ev = m.event
                kind = ev.get("type")
                if kind == "message_start":
                    u = (ev.get("message") or {}).get("usage") or {}
                    self.context_tokens = (u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
                                           + u.get("cache_creation_input_tokens", 0))
                    speaker.start()
                elif kind == "content_block_delta" and ev["delta"].get("type") == "text_delta":
                    hub.mark("first_token", turn_id)
                    speaker.delta(ev["delta"]["text"])
                elif kind == "content_block_start" and ev.get("content_block", {}).get("type") == "tool_use":
                    speaker.tool_call()
                    name = ev["content_block"].get("name", "")
                    hub.tool(name, status(name, {}))
                elif kind == "message_stop":
                    speaker.stop()
            elif isinstance(m, AssistantMessage):
                if m.parent_tool_use_id or getattr(m, "error", None):
                    continue  # a subagent's turn, or an API error dressed as a reply
                for block in m.content:
                    if isinstance(block, ToolUseBlock):
                        hub.log("tool", f"{block.name.removeprefix('mcp__').replace('__', ' ')}  {brief(block.input)}")
                        hub.tool(block.name, status(block.name, block.input))
                        work.call(block)
            elif isinstance(m, UserMessage) and not m.parent_tool_use_id and isinstance(m.content, list):
                for block in m.content:
                    if isinstance(block, ToolResultBlock):
                        work.result(block)
            elif isinstance(m, ResultMessage):
                self._save_session(m.session_id)
                self.session_id = m.session_id
                self.cost = m.total_cost_usd or self.cost
                if m.is_error and "too long" in (m.result or "").lower():
                    overflow = True
                elif m.is_error and m.subtype not in ("error_during_execution",):
                    # never fail in silence: say so, and keep the reason in the transcript
                    reason = (m.result or m.subtype or "").strip()[:200]
                    hub.log("system", f"turn failed: {reason}")
                    log.warning("turn failed: %s", reason)
                    hub.say("That didn't work on my side. Try again.", turn_id)
        return overflow

    async def _watch(self, turn_id: int, limit: float = 90.0):
        """A turn that goes quiet for this long (no stream event at all, and not waiting on my
        approval) is stuck: stop it and say so, instead of leaving me in silence."""
        while True:
            await asyncio.sleep(5)
            if self.hub.approval:
                self.last_event = time.monotonic()
            elif time.monotonic() - self.last_event > limit:
                log.warning("turn %s stalled for %.0fs, interrupting", turn_id, limit)
                await self.interrupt()
                self.hub.say("That got stuck, so I stopped it.", turn_id)
                return

    # ---- fleet tools ---------------------------------------------------------------------

    async def _agent(self, name: str) -> tuple[dict | None, dict | None]:
        items = await tower.agents()
        a = tower.resolve(name or "", items)
        if a:
            self.last_agent = a["name"]
            return a, None
        names = ", ".join(x["name"] for x in items) or "none"
        return None, fail(f"No agent matches {name!r}. Agents: {names}.")

    def _tools(self):
        @tool(
            "fleet_status",
            "List every Claude Code agent in my tmux panes: state (working, waiting on me, done, idle), "
            "how long, folder, current activity and its task. Call it for any question about what agents are doing.",
            {"type": "object", "properties": {}},
        )
        async def fleet_status(args):
            items, headless = await asyncio.gather(tower.agents(), tower.threads())
            known = self.hub.coordinator.fleet_text()
            text = tower.report(items, headless)
            return ok(text + ("\n\nWhat each one is doing, blocked on and needs:\n" + known if known else ""))

        @tool(
            "agent_context",
            "Everything about one agent: its task, what it has done so far, what's next, what blocks it and "
            "what it needs, its pending tool call, the files it edited, its recent transcript and last reply. "
            "Use it for detailed questions about an agent or before deciding how to help it.",
            {"type": "object", "properties": {"agent": {"type": "string"}}, "required": ["agent"]},
        )
        async def agent_context(args):
            a, err = await self._agent(args.get("agent", ""))
            if err:
                return err
            return ok(await self.hub.coordinator.context_of(a))

        @tool(
            "agent_last_reply",
            "Read an agent's most recent reply, to tell me what it said, found or finished.",
            {"type": "object", "properties": {"agent": {"type": "string"}}, "required": ["agent"]},
        )
        async def agent_last_reply(args):
            a, err = await self._agent(args.get("agent", ""))
            if err:
                return err
            rc, out = await tower.run("last", a["pane"])
            if rc:
                return fail(out)
            return ok(f"{a['name']} ({a['state']}) last replied:\n{out[-6000:] or '(nothing yet)'}")

        @tool(
            "agent_screen",
            "Show the bottom of an agent's terminal screen. Use it when an agent is waiting on a prompt "
            "or to see exactly where it is mid-task.",
            {"type": "object", "properties": {"agent": {"type": "string"},
                                              "lines": {"type": "integer", "description": "default 40"}},
             "required": ["agent"]},
        )
        async def agent_screen(args):
            a, err = await self._agent(args.get("agent", ""))
            if err:
                return err
            lines = str(min(200, max(5, int(args.get("lines") or 40))))
            rc, out = await tower.run("peek", "-n", lines, a["pane"])
            return fail(out) if rc else ok(out or "(empty screen)")

        @tool(
            "agent_send",
            "Type a message or task into an agent's Claude Code prompt, optionally with files it can open "
            "(screenshots, images, screen recordings, PDFs, logs, any file by path) or a fresh screenshot of my "
            "screen. Set force to send while it is mid-turn; otherwise tower may refuse a busy agent.",
            {"type": "object", "properties": {
                "agent": {"type": "string"},
                "message": {"type": "string"},
                "attach": {"type": "array", "items": {"type": "string"}, "description": "paths of files to hand over"},
                "screenshot": {"type": "string",
                               "description": "attach a screenshot taken now: 'focused' (my focused monitor), 'all', "
                                              "a monitor name, or a window's class or title"},
                "force": {"type": "boolean"}},
             "required": ["agent"]},
        )
        async def agent_send(args):
            a, err = await self._agent(args.get("agent", ""))
            if err:
                return err
            files = [str(Path(p).expanduser()) for p in args.get("attach") or []]
            missing = [f for f in files if not Path(f).exists()]
            if missing:
                return fail(f"No such file: {', '.join(missing)}")
            shot = str(args.get("screenshot") or "").strip()
            message = str(args.get("message") or "").strip()
            if not (message or files or shot):
                return fail("Nothing to send.")
            flags = ["--force"] if args.get("force") else []
            if await tower.supports("send", "attach"):
                # tower keeps a copy of each file and tells the agent what it got
                for f in files:
                    flags += ["--attach", f]
                if shot:
                    flags.append("--shot" if shot.lower() in ("focused", "screen", "true") else f"--shot={shot}")
            else:
                # an older tower: paths in the text, and image paths still arrive as images
                if shot:
                    taken = await screenshot(shot)
                    if not taken:
                        return fail(f"Couldn't take a screenshot of {shot}.")
                    files.append(taken)
                if files:
                    message = (message + "\n\n" if message else "") + "Files for you (open them with Read):\n" + \
                        "\n".join(files)
            # with --shot, tower takes the screenshot; without it, it is already one of the files
            n = len(files) + any(f.startswith("--shot") for f in flags)
            rc, out = await tower.run("send", *flags, a["pane"], message, timeout=60)
            sent = f"Sent to {a['name']}" + (f" with {n} file{'s' if n > 1 else ''}" if n else "") + "."
            return fail(out or "send failed") if rc else ok(out or sent)

        @tool(
            "agent_spawn",
            "Start a new Claude Code agent in its own tmux window on a task. Its model is picked from the task "
            "unless I name one: Opus for planning, debugging, design, research and review; Sonnet for "
            "implementing and running things; opusplan (plans on Opus, then works on Sonnet) for builds from "
            "scratch. Write the task as a complete brief: it has none of our conversation.",
            {"type": "object", "properties": {
                "task": {"type": "string"},
                "name": {"type": "string", "description": "short agent name"},
                "dir": {"type": "string", "description": "working folder, default my home"},
                "worktree": {"type": "boolean", "description": "give it its own git worktree"},
                "model": {"type": "string", "enum": ["auto", *models.CHOICES],
                          "description": "auto unless I asked for a model"}},
             "required": ["task"]},
        )
        async def agent_spawn(args):
            model = str(args.get("model") or "auto").lower()
            why = "you asked for it"
            if model not in models.CHOICES:
                model, why = models.pick(args["task"])
            flags = ["-c", models.claude_command(model)]
            if args.get("name"):
                flags += ["-n", args["name"]]
            if args.get("dir"):
                flags += ["-d", str(Path(args["dir"]).expanduser())]
            if args.get("worktree"):
                flags.append("-w")
            rc, out = await tower.run("spawn", *flags, args["task"], timeout=30)
            if rc:
                return fail(out or "spawn failed")
            out = f"{out}\nIt runs on {model}: {why}." if out else f"Spawned on {model}: {why}."
            pane = re.search(r"%\d+", out or "")
            if pane:
                await asyncio.sleep(4)
                if await trust_prompt(pane.group()):
                    return ok(f"{out}\nIt is stopped on Claude Code's question whether to trust the folder "
                              f"{args.get('dir') or 'home'}, so it has not started and is not in the fleet yet. "
                              f"Ask me; if I agree, agent_approve with agent {pane.group()} trusts the folder.")
            return ok(out or "Spawned.")

        @tool(
            "agent_interrupt",
            "Interrupt an agent's current turn (sends Esc to its pane).",
            {"type": "object", "properties": {"agent": {"type": "string"}}, "required": ["agent"]},
        )
        async def agent_interrupt(args):
            a, err = await self._agent(args.get("agent", ""))
            if err:
                return err
            rc, out = await tower.run("stop", a["pane"])
            return fail(out) if rc else ok(f"Interrupted {a['name']}.")

        @tool(
            "agent_approve",
            "Approve the permission prompt an agent is waiting on (presses Enter on its highlighted Yes), or "
            "trust the folder for a just-spawned agent stuck on that question (pass its pane id, like %12). "
            "Check agent_screen first if you need to know what it is asking.",
            {"type": "object", "properties": {"agent": {"type": "string"}}, "required": ["agent"]},
        )
        async def agent_approve(args):
            target = str(args.get("agent", "")).strip()
            # a fresh agent stuck on the folder trust question isn't in the fleet yet; take its pane id
            if re.fullmatch(r"%\d+", target) and await trust_prompt(target):
                if await tower.accept_trust(target):
                    return ok("Trusted the folder; the agent is starting.")
                return fail("Couldn't pick 'Yes, I trust this folder' on its screen; it is still asking.")
            a, err = await self._agent(target)
            if err:
                return err
            if await trust_prompt(a["pane"]):
                if await tower.accept_trust(a["pane"]):
                    return ok(f"Trusted the folder for {a['name']}; it is starting.")
                return fail(f"Couldn't pick 'Yes, I trust this folder' for {a['name']}; it is still asking.")
            if a["state"] != "waiting":
                return fail(f"{a['name']} is {a['state']}, not waiting on a prompt.")
            rc, out = await tower.tmux("send-keys", "-t", a["pane"], "Enter")
            return fail(out) if rc else ok(f"Approved {a['name']}'s prompt.")

        @tool(
            "agent_show",
            "Bring an agent's tmux pane to the front of my terminal so I can look at it.",
            {"type": "object", "properties": {"agent": {"type": "string"}}, "required": ["agent"]},
        )
        async def agent_show(args):
            a, err = await self._agent(args.get("agent", ""))
            if err:
                return err
            rc, out = await tower.run("jump", a["pane"])
            return fail(out) if rc else ok(f"Showing {a['name']} at {a.get('where', a['pane'])}.")

        @tool(
            "open_url",
            "Open a URL in my default browser right away. The fastest way to show me any website, search "
            "results page, map or document.",
            {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
        )
        async def open_url(args):
            url = str(args.get("url", "")).strip()
            if not re.match(r"^(https?|file|mailto):", url):
                url = "https://" + url
            await spawn("xdg-open", url)
            return ok(f"Opened {url}")

        @tool(
            "play_youtube",
            "Find a video or song on YouTube and start playing the top result in my browser.",
            {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        )
        async def play_youtube(args):
            query = str(args.get("query", "")).strip()
            proc = await asyncio.create_subprocess_exec(
                "yt-dlp", "--no-warnings", "--flat-playlist", "--print", "%(id)s\t%(title)s", f"ytsearch1:{query}",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                out, _ = await asyncio.wait_for(proc.communicate(), 12)
            except TimeoutError:
                proc.kill()
                out = b""
            line = out.decode(errors="replace").strip().split("\n")[0]
            if "\t" not in line:
                url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query)
                await spawn("xdg-open", url)
                return ok(f"No direct hit, opened the search results for {query}.")
            vid, title = line.split("\t", 1)
            await spawn("xdg-open", f"https://www.youtube.com/watch?v={vid}&autoplay=1")
            return ok(f"Playing \"{title}\" on YouTube.")

        @tool(
            "music_play",
            "Search YouTube and play the audio of the top results through my speakers, as a short queue. "
            "Use it for any request to play music.",
            {"type": "object", "properties": {"query": {"type": "string", "description": "artist, song, album or mood"}},
             "required": ["query"]},
        )
        async def music_play(args):
            text = await self.hub.music.play(str(args.get("query", "")).strip() or "lo-fi beats")
            return ok(text)

        @tool(
            "music_control",
            "Control the music that is playing: pause, resume, next, previous or stop. "
            "louder and quieter change the music volume.",
            {"type": "object", "properties": {"action": {"type": "string", "enum": [
                "pause", "resume", "next", "previous", "stop", "louder", "quieter", "status"]}},
             "required": ["action"]},
        )
        async def music_control(args):
            action = args.get("action", "")
            music = self.hub.music
            if action in ("louder", "quieter"):
                vol = float(self.hub.settings.get("music_volume", 0.6)) + (0.15 if action == "louder" else -0.15)
                await self.hub._patch_settings({"music_volume": vol})
                return ok(f"Music volume {round(self.hub.settings['music_volume'] * 100)} percent.")
            if action == "status":
                st = music.state()
                if not music.active:
                    return ok("Nothing is playing.")
                return ok(f"{'Paused' if st['paused'] else 'Playing'}: {st['title']} (searched for {st['query']}).")
            return ok(await music.control(action))

        @tool(
            "remember",
            "Save something about me to long-term memory so you know it in future conversations.",
            {"type": "object", "properties": {
                "fact": {"type": "string", "description": "one short self-contained sentence about me"},
                "kind": {"type": "string", "enum": ["fact", "preference", "project", "person"]}},
             "required": ["fact"]},
        )
        async def remember(args):
            m, new = self.hub.memory.add(str(args.get("fact", "")), str(args.get("kind", "fact")))
            self.hub.memory_changed()
            return ok(("Saved: " if new else "Updated: ") + m["text"])

        @tool(
            "forget",
            "Remove something from long-term memory, matched by meaning.",
            {"type": "object", "properties": {"what": {"type": "string"}}, "required": ["what"]},
        )
        async def forget(args):
            gone = self.hub.memory.forget(str(args.get("what", "")))
            if not gone:
                return fail("Nothing in memory matches that.")
            self.hub.memory_changed()
            return ok("Forgot: " + gone[0]["text"])

        @tool(
            "pet_action",
            "Make the Claude Bot pet act something out on my screen. Actions: "
            + "; ".join(f"{group}: {', '.join(names)}" for group, names in PET.items())
            + ". Plain words work too (levitate, jump, nap, wake up, party, peek from the left, "
            "go to the top right corner, sit on the right edge, come back).",
            {"type": "object", "properties": {"action": {"type": "string"}}, "required": ["action"]},
        )
        async def pet_action(args):
            name = pet_name(str(args.get("action", "")))
            if not name:
                return fail("The pet can't do that. It can: " + ", ".join(sorted(PET_NAMES)))
            if not self.hub.clients:
                return fail("The pet window isn't connected right now.")
            self.hub.broadcast({"type": "pet", "action": name})
            return ok(f"The pet is doing {name.removeprefix('think:')}.")

        @tool(
            "coordinator_report",
            "What the coordinator did for my agents lately (approvals, answers, go-aheads, unsticking) and "
            "what it is waiting on me for.",
            {"type": "object", "properties": {}},
        )
        async def coordinator_report(args):
            return ok(self.hub.coordinator.report())

        @tool(
            "coordinator_answer",
            "Give my answer to something the coordinator asked me about an agent: approve its prompt or let "
            "it go ahead, or deny it, optionally with what it should do instead.",
            {"type": "object", "properties": {
                "agent": {"type": "string"},
                "decision": {"type": "string", "enum": ["approve", "deny"]},
                "note": {"type": "string", "description": "what to tell the agent, e.g. what to do instead"}},
             "required": ["agent", "decision"]},
        )
        async def coordinator_answer(args):
            c = self.hub.coordinator
            pending = list(c.pending.values())
            a = tower.resolve(str(args.get("agent", "")), [{"name": p["agent"], "pane": p["pane"]} for p in pending])
            if not a:
                if len(pending) == 1 and not str(args.get("agent", "")).strip():
                    a = {"pane": pending[0]["pane"]}
                else:
                    names = ", ".join(p["agent"] for p in pending) or "nobody"
                    return fail(f"The coordinator isn't waiting on me about {args.get('agent')!r}. Waiting: {names}.")
            return ok(await c.resolve(a["pane"], args.get("decision", "deny"), str(args.get("note", ""))))

        @tool(
            "coordinator_set",
            "Turn the coordinator on or off, or keep it away from one agent (hands_off) or let it back (hands_on).",
            {"type": "object", "properties": {
                "on": {"type": "boolean"},
                "hands_off": {"type": "string", "description": "agent name"},
                "hands_on": {"type": "string", "description": "agent name"}}},
        )
        async def coordinator_set(args):
            hub = self.hub
            patch = {}
            if "on" in args:
                patch["coordinator"] = bool(args["on"])
            skip = set(hub.settings.get("coordinator_skip", []))
            if args.get("hands_off"):
                skip.add(str(args["hands_off"]).strip())
            if args.get("hands_on"):
                skip = {x for x in skip if x.lower() != str(args["hands_on"]).strip().lower()}
            patch["coordinator_skip"] = sorted(skip)
            await hub._patch_settings(patch)
            off = ", ".join(hub.settings.get("coordinator_skip", [])) or "none"
            return ok(f"Coordinator {'on' if hub.coordinator.enabled else 'off'}; hands off: {off}.")

        return [fleet_status, agent_last_reply, agent_screen, agent_send, agent_spawn, agent_interrupt,
                agent_approve, agent_show, open_url, play_youtube, music_play, music_control, remember, forget,
                pet_action, coordinator_report, coordinator_answer, coordinator_set, agent_context]
