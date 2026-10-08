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
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    StreamEvent,
    TextBlock,
    ToolUseBlock,
    create_sdk_mcp_server,
    tool,
)

from . import tower
from .config import RUNTIME_DIR
from .speech import Chunker

log = logging.getLogger("claudebot_voice.brain")
SESSION_FILE = RUNTIME_DIR / "session"

# Status lines belong on screen, not in my ears: the pet and the panel show what is going on.
FILLER = re.compile(r"^(ok(ay)?[,.]? )?(checking|looking|on it|one sec(ond)?|one moment|hang on|working on it|"
                    r"let me (check|look|see)( that| into that)?|give me a (sec|second|moment))\W*$", re.I)
PC_STATUS = {"screenshot": "Looking at the screen", "windows": "Checking windows", "system_state": "Checking the system",
             "system_events": "Checking recent events", "processes": "Checking processes", "process_info": "Checking a process",
             "services": "Checking services", "logs": "Reading logs", "ports": "Checking ports", "system_info": "Checking the system",
             "open_app": "Opening an app", "focus_window": "Switching windows", "close_window": "Closing a window",
             "switch_workspace": "Switching workspace", "wait_for": "Waiting"}
BUILTIN_TOOLS = ["Bash", "Read", "Glob", "Grep", "WebSearch", "WebFetch", "Write", "Edit"]

SYSTEM = """You are {name}, the voice of my Linux workstation ({host}: Arch Linux, Hyprland, tmux). I talk to you out loud through speech to text, and everything you write is spoken by a text to speech voice.

How to answer:
- Lead with the answer. One spoken sentence by default, two at most, unless I ask for more.
- Plain spoken words only: no markdown, lists, code, emoji, URLs, paths, hashes or IDs. Say what things mean.
- Answer directly from what you know whenever no live state is needed: small talk, facts, arithmetic, definitions, the date. Use a tool only when the answer depends on my agents, my machine, my files or the web.
- Never narrate your work ("Checking.", "On it.", "Let me see."): the screen shows your status. Work quietly, then answer.
- Never repeat something you already said. If a tool fails twice, stop and tell me in one sentence.
- Speech to text mishears names: "Claudia Bot" is probably the agent claudebot, "tau er" is tower.
- Dry, quick and calm, like a good chief of staff. No filler, no apologies.

What you run:
- The fleet: Claude Code agents in my tmux panes, through the fleet tools (tower). Name each agent and say in plain words what it is doing. "waiting" means blocked on me; "done" means finished and unread. Mention idle agents only if I ask about everything.
- My desktop through the pc tools, like Claude Code does: do things yourself instead of telling me how, and say one short line when done. Orient with windows (cheap text), screenshot only when you need to see or need coordinates (x and y are pixels of the latest screenshot; aim at the middle of a control). Prefer press_keys and paste_text (pass window= to target one) over clicks, chain known steps in one act call, wait_for instead of sleeping. system_state first for questions about the machine. Never click through consent, payment or destructive dialogs on your own; if I say stop, call input_disable.
- A shell, files and the web. Give every Bash call a short description.
- Shortcuts: open_url with the final URL for any site or search; music_play and music_control for music (it plays here, under your voice, and ducks while either of us talks; pick a sensible query when I'm vague); play_youtube for a video to watch; open_app for apps.
- You live in Claude Bot, the pixel creature on my screen. pet_action makes it act things out (fly, dance, hide, peek, sleep, wave...). When I ask for one, call it and answer in a word or two.

Risky actions go through an approval I answer out loud; don't ask me yourself, just call the tool, and accept a no. A message may start with a bracketed note of fleet events since my last message; mention them only when relevant.
{memory}
It is {date}. My home folder is {home}."""


MEMORY = """
Memory: you keep a long-term memory of me across conversations, stored on this machine.
- When I tell you something durable about me (a fact, a preference, a project I am working on, a person in my life) or ask you to remember something, call remember right away, in your own words, one short self-contained sentence. Do not announce it unless I asked you to remember.
- When something you remember changes or I ask you to forget it, call forget, then remember the new version.
- Skip small talk, one-off requests and anything you could look up.
- Use what you remember naturally, without saying "I remember that".
What you remember so far:
{memories}
"""


# Everything the pet in Claude Bot can act out (what brain.play accepts in src/brain.js), and the
# words I am likely to use for them.
PET = {
    "moves": ["fly", "dance", "walk", "zoomies", "chase", "hop", "wave", "sit", "stretch", "yawn", "trip", "sneeze", "look",
              "drop", "throw", "explore"],
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


TRUST = re.compile(r"trust this folder|one you trust", re.I)


async def trust_prompt(target: str) -> bool:
    """Is this pane sitting on Claude Code's "do you trust this folder" question? Tower only starts
    tracking an agent once it is past it."""
    rc, out = await tower.tmux("capture-pane", "-p", "-t", target)
    return rc == 0 and bool(TRUST.search(out))


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
        self.session_id = ""
        self.cost = 0.0
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
        return MEMORY.format(memories=self.hub.memory.prompt())

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
                await client.connect()
            except Exception:
                if not self._saved_session():
                    raise
                log.warning("could not resume the last session, starting fresh")
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

    async def turn(self, text: str, turn_id: int):
        hub = self.hub
        async with self.lock:
            self.busy = True
            chunker = Chunker()
            said: set[str] = set()
            self.last_event = time.monotonic()
            watchdog = asyncio.create_task(self._watch(turn_id))

            def speak(parts):
                for part in parts:
                    key = re.sub(r"\W+", " ", part.lower()).strip()
                    if key in said:
                        continue  # never say the same sentence twice in one answer
                    said.add(key)
                    if not FILLER.match(part.strip()):
                        hub.mark("first_chunk", turn_id)
                        hub.say(part, turn_id)

            try:
                await self.connect()
                prompt = text
                if self.notes:
                    prompt = "[fleet events since my last message: " + " ".join(self.notes) + "]\n" + text
                    self.notes.clear()
                await self.client.query(prompt)
                async for m in self.client.receive_response():
                    self.last_event = time.monotonic()
                    if isinstance(m, StreamEvent):
                        if m.parent_tool_use_id:
                            continue
                        ev = m.event
                        kind = ev.get("type")
                        if kind == "content_block_delta" and ev["delta"].get("type") == "text_delta":
                            hub.mark("first_token", turn_id)
                            speak(chunker.feed(ev["delta"]["text"]))
                        elif kind == "content_block_start" and ev.get("content_block", {}).get("type") == "tool_use":
                            speak(chunker.flush())
                            name = ev["content_block"].get("name", "")
                            hub.tool(name, status(name, {}))
                        elif kind in ("content_block_stop", "message_stop"):
                            speak(chunker.flush())
                    elif isinstance(m, AssistantMessage):
                        if m.parent_tool_use_id:
                            continue
                        for block in m.content:
                            if isinstance(block, TextBlock) and block.text.strip():
                                hub.reply(turn_id, block.text.strip())
                            elif isinstance(block, ToolUseBlock):
                                hub.log("tool", f"{block.name.removeprefix('mcp__').replace('__', ' ')}  {brief(block.input)}")
                                hub.tool(block.name, status(block.name, block.input))
                    elif isinstance(m, ResultMessage):
                        self._save_session(m.session_id)
                        self.session_id = m.session_id
                        self.cost = m.total_cost_usd or self.cost
                        if m.is_error and m.subtype not in ("error_during_execution",):
                            hub.log("system", f"turn ended: {m.subtype}")
                speak(chunker.flush())
            except Exception as e:
                log.exception("turn failed")
                await self.close()
                hub.log("system", f"Claude error: {e}")
                hub.say("Something broke on my side. Try that again.", turn_id)
            finally:
                watchdog.cancel()
                self.busy = False
                hub.tool("", "")

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
            return ok(tower.report(items, headless))

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
            "Type a message or task into an agent's Claude Code prompt. Set force to send while it is "
            "mid-turn; otherwise tower may refuse a busy agent.",
            {"type": "object", "properties": {"agent": {"type": "string"}, "message": {"type": "string"},
                                              "force": {"type": "boolean"}},
             "required": ["agent", "message"]},
        )
        async def agent_send(args):
            a, err = await self._agent(args.get("agent", ""))
            if err:
                return err
            flags = ["--force"] if args.get("force") else []
            rc, out = await tower.run("send", *flags, a["pane"], args["message"])
            return fail(out or "send failed") if rc else ok(out or f"Sent to {a['name']}.")

        @tool(
            "agent_spawn",
            "Start a new Claude Code agent in its own tmux window on a task.",
            {"type": "object", "properties": {
                "task": {"type": "string"},
                "name": {"type": "string", "description": "short agent name"},
                "dir": {"type": "string", "description": "working folder, default my home"},
                "worktree": {"type": "boolean", "description": "give it its own git worktree"}},
             "required": ["task"]},
        )
        async def agent_spawn(args):
            flags = []
            if args.get("name"):
                flags += ["-n", args["name"]]
            if args.get("dir"):
                flags += ["-d", str(Path(args["dir"]).expanduser())]
            if args.get("worktree"):
                flags.append("-w")
            rc, out = await tower.run("spawn", *flags, args["task"], timeout=30)
            if rc:
                return fail(out or "spawn failed")
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
                rc, out = await tower.tmux("send-keys", "-t", target, "Down", "Enter")  # "Yes, I trust this folder"
                return fail(out) if rc else ok("Trusted the folder; the agent is starting.")
            a, err = await self._agent(target)
            if err:
                return err
            if await trust_prompt(a["pane"]):
                rc, out = await tower.tmux("send-keys", "-t", a["pane"], "Down", "Enter")
                return fail(out) if rc else ok(f"Trusted the folder for {a['name']}; it is starting.")
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

        return [fleet_status, agent_last_reply, agent_screen, agent_send, agent_spawn, agent_interrupt,
                agent_approve, agent_show, open_url, play_youtube, music_play, music_control, remember, forget,
                pet_action]
