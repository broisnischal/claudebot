"""Which tool calls run on their own and which ones ask me first."""

import json
import os
import re
import shlex

READ_TOOLS = {"Read", "Glob", "Grep", "WebSearch", "WebFetch", "TodoWrite"}
FLEET_SAFE = {"fleet_status", "agent_last_reply", "agent_screen", "agent_show", "open_url", "play_youtube",
              "music_play", "music_control", "remember", "forget", "pet_action"}
# pc tools with side effects. Everything else in pc only looks (screenshots, windows, logs) or
# is plainly visible and harmless (open an app, focus a window, switch workspace).
PC_ASK = {"click", "drag", "scroll", "type_text", "press_keys", "paste_text", "act", "close_window",
          "clipboard", "input_disable"}

SAFE_COMMANDS = {
    "ls", "cat", "bat", "head", "tail", "grep", "rg", "fd", "find", "wc", "du", "df", "free", "uptime",
    "date", "cal", "whoami", "id", "hostname", "uname", "ps", "pgrep", "pidof", "pwd", "which", "whereis",
    "type", "file", "stat", "echo", "printf", "tree", "jq", "sort", "uniq", "cut", "tr", "column", "nl",
    "diff", "cmp", "basename", "dirname", "realpath", "readlink", "lsblk", "lscpu", "lsusb", "lspci",
    "lsof", "ss", "nproc", "sensors", "journalctl", "cd", "true", "test", "wl-paste", "fastfetch",
    "sha256sum", "md5sum", "sed", "upower", "acpi", "nvidia-smi", "ip",
}
SAFE_SUBCOMMANDS = {
    "git": {"status", "log", "diff", "show", "branch", "remote", "rev-parse", "ls-files", "blame",
            "describe", "shortlog", "tag"},
    "systemctl": {"status", "list-units", "list-timers", "is-active", "is-enabled", "is-failed", "show", "cat"},
    "hyprctl": {"clients", "activewindow", "activeworkspace", "workspaces", "monitors", "devices", "version",
                "getoption", "binds", "layers"},
    "tower": {"ls", "threads", "last", "peek", "comms", "status", "whoami"},
    "pc": {"state", "events", "ps", "proc", "units", "logs", "ports", "sys", "windows"},
    "tmux": {"ls", "list-sessions", "list-windows", "list-panes", "capture-pane", "display-message"},
    "docker": {"ps", "images", "logs", "inspect", "stats"},
    "pactl": {"info", "list", "get-default-sink", "get-default-source", "get-sink-volume", "get-sink-mute"},
    "wpctl": {"status", "get-volume", "inspect"},
    "playerctl": {"status", "metadata", "position", "-l", "--list-all"},
    "voxtype": {"status"},
    "nmcli": {"general", "device"},
    "pacman": {"-Q", "-Qi", "-Ql", "-Qs", "-Ss", "-Si", "-Qe", "-Qu"},
    "npm": {"ls", "list", "view", "outdated"},
}
DANGER = re.compile(
    r"\b(rm|rmdir|sudo|doas|dd|mkfs\S*|shred|wipefs|shutdown|reboot|poweroff|halt|kill|pkill|killall|"
    r"chmod|chown|truncate|crontab)\b|git\s+(push|reset|clean|rebase|filter-branch|checkout\s+--)|"
    r"systemctl\s+(stop|disable|mask|kill|poweroff|reboot|restart)|\|\s*(ba|z)?sh\b|>\s*/dev/sd|:\(\)\s*\{"
)
GIT_LISTING = {"-a", "-r", "-v", "-vv", "-l", "--list", "--all", "--show-current", "--merged", "--no-merged"}
# Asks even with full access: one misheard sentence should not be able to wipe the machine.
CATASTROPHIC = re.compile(
    r"\brm\s+(-\S*\s+)*(/|~|\$HOME|/home/?\S*)\s*$|\brm\s+-\S*r\S*\s+(/|~/?|\$HOME/?)(\s|$)|\bmkfs|\bwipefs|"
    r"\bdd\b[^|]*\bof=/dev/|>\s*/dev/(sd|nvme)|\b(shutdown|poweroff|reboot|halt)\b|:\(\)\s*\{"
)
REDIRECT_OK = re.compile(r"\d?>\s*/dev/null|\d?>&\d")


def bash_is_safe(cmd: str) -> bool:
    """True for commands that only read. Anything I cannot parse counts as unsafe."""
    if re.search(r"`|\$\(|<\(|>\(", cmd):
        return False
    cmd = REDIRECT_OK.sub("", cmd)
    if ">" in cmd:
        return False
    for seg in re.split(r"&&|\|\||[;|\n]", cmd):
        try:
            words = shlex.split(seg)
        except ValueError:
            return False
        while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
            words.pop(0)
        if not words:
            continue
        exe, args = os.path.basename(words[0]), words[1:]
        if exe == "git":
            while args[:1] and args[0] in ("-C", "-c", "--no-pager"):
                args = args[2:] if args[0] != "--no-pager" else args[1:]
        if exe in SAFE_SUBCOMMANDS:
            sub = args[0] if exe in ("pacman", "playerctl") and args else next((a for a in args if not a.startswith("-")), "")
            if sub not in SAFE_SUBCOMMANDS[exe]:
                return False
            if exe == "git" and sub in ("branch", "tag", "remote"):
                rest = args[args.index(sub) + 1:]
                if not (sub == "remote" and rest[:1] == ["show"]) and any(a not in GIT_LISTING for a in rest):
                    return False
        elif exe not in SAFE_COMMANDS:
            return False
        if exe == "find" and any(a in ("-delete", "-exec", "-execdir", "-ok", "-fprint") for a in args):
            return False
        if exe == "sed" and any(a.startswith("-i") or a == "--in-place" for a in args):
            return False
        if exe == "ip" and any(a in ("add", "del", "delete", "set", "flush", "change", "replace") for a in args):
            return False
    return True


def _parts(tool: str) -> tuple[str, str]:
    if tool.startswith("mcp__"):
        _, server, name = tool.split("__", 2)
        return server, name
    return "", tool


def always_key(tool: str, inp: dict) -> str:
    if tool == "Bash":
        words = (inp.get("command") or "").split()
        return "Bash:" + (os.path.basename(words[0]) if words else "")
    return tool


def decide(tool: str, inp: dict, autonomy: str, always: set[str]) -> str:
    """'allow' or 'ask'."""
    server, name = _parts(tool)
    if autonomy == "full":
        return "ask" if tool == "Bash" and CATASTROPHIC.search(inp.get("command") or "") else "allow"
    if always_key(tool, inp) in always or tool in READ_TOOLS:
        return "allow"
    if server == "jarvis" and name in FLEET_SAFE:
        return "allow"
    if server == "pc" and name not in PC_ASK:
        return "allow"
    if tool == "Bash":
        cmd = inp.get("command") or ""
        if bash_is_safe(cmd) or (autonomy == "trust" and not DANGER.search(cmd)):
            return "allow"
        return "ask"
    return "allow" if autonomy == "trust" else "ask"


def _lower_first(s: str) -> str:
    return s[:1].lower() + s[1:] if s[:2] != s[:2].upper() else s


def describe(tool: str, inp: dict) -> tuple[str, str]:
    """(card title, spoken phrase that completes 'Okay to ...?')."""
    server, name = _parts(tool)
    agent = inp.get("agent", "")
    if tool == "Bash":
        desc = (inp.get("description") or "").strip().rstrip(".")
        cmd = (inp.get("command") or "").strip()
        exe = os.path.basename(cmd.split()[0]) if cmd else "a"
        return desc or cmd[:90], _lower_first(desc) if desc else f"run a {exe} command"
    if tool in ("Write", "Edit", "NotebookEdit"):
        path = inp.get("file_path") or inp.get("notebook_path") or ""
        verb = "write" if tool == "Write" else "edit"
        return f"{verb.title()} {path}", f"{verb} {os.path.basename(path) or 'a file'}"
    spoken = {
        "agent_send": (f"Send to {agent}", f"send that to {agent}"),
        "agent_spawn": (f"Spawn agent {inp.get('name', '')}".strip(), "start a new agent on that"),
        "agent_interrupt": (f"Interrupt {agent}", f"interrupt {agent}"),
        "agent_approve": (f"Approve {agent}'s prompt", f"approve {agent}'s prompt"),
        "click": ("Click on screen", "click there"),
        "drag": ("Drag on screen", "drag that"),
        "scroll": ("Scroll", "scroll"),
        "type_text": ("Type text", "type that"),
        "press_keys": (f"Press {inp.get('keys', '')}".strip(), f"press {inp.get('keys', 'those keys')}"),
        "paste_text": ("Paste text", "paste that"),
        "act": ("Run desktop actions", "run those desktop actions"),
        "close_window": ("Close a window", "close that window"),
        "clipboard": ("Use the clipboard", "use the clipboard"),
        "input_disable": ("Disable agent input", "turn off my input control"),
    }.get(name)
    if spoken:
        return spoken
    label = name.replace("_", " ")
    return label.capitalize(), f"use {label}"


def detail(tool: str, inp: dict) -> str:
    if tool == "Bash":
        return inp.get("command", "")
    if tool in ("Write", "Edit"):
        body = inp.get("content") or inp.get("new_string") or ""
        return f"{inp.get('file_path', '')}\n\n{body[:600]}"
    for key in ("message", "task", "text", "keys"):
        if inp.get(key):
            return str(inp[key])[:800]
    return json.dumps(inp, ensure_ascii=False)[:800]
