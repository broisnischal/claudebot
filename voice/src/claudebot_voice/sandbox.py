"""Where a background worker runs, and what fences it in.

- bwrap: Claude Code's own sandbox. Shell commands run in bubblewrap and can only write inside the
  working folder (and /tmp); the file tools are held to the same folders by a hook.
- worktree: a git worktree of the folder on a branch of its own, so the worker never touches my
  checkout. The work stays on that branch when it's done.
- docker: the whole session runs in a throwaway container that sees only the working folder and a
  read-only copy of my Claude setup. No desktop, no other files, no host MCP servers.

They combine. With docker, bwrap is left out: the container is the fence.
"""

import asyncio
import json
import os
import re
import shlex
import shutil
from pathlib import Path

import claude_agent_sdk
from claude_agent_sdk import HookMatcher

from .config import SANDBOX_DIR, WORKTREES_DIR

KINDS = ("bwrap", "worktree", "docker")
IMAGE = "claudebot-sandbox:1"
DOCKERFILE = """FROM debian:trixie-slim
RUN apt-get update && apt-get install -y --no-install-recommends \\
      git ca-certificates curl ripgrep jq procps less build-essential \\
      python3 python3-venv python3-pip nodejs npm \\
    && rm -rf /var/lib/apt/lists/*
"""
CLAUDE_HOME = Path.home() / ".claude"
# What a container gets from my setup, through links into the read-only mount of ~/.claude.
SHARED = ("skills", "plugins", "agents", "commands", "output-styles", "CLAUDE.md")


class SandboxError(Exception):
    pass


def kinds(value) -> list[str]:
    """Whatever I asked for ("docker", ["worktree", "bwrap"], "worktree+docker") as known kinds."""
    words = value if isinstance(value, (list, tuple)) else re.split(r"[\s,+]+", str(value or ""))
    return [k for k in KINDS if k in {str(w).strip().lower() for w in words}]


async def run(*cmd: str, cwd: str | None = None, stdin: bytes | None = None, timeout: float = 60) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=cwd, stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(stdin), timeout)
    except TimeoutError:
        proc.kill()
        return 124, f"{cmd[0]} timed out after {timeout:.0f}s"
    return proc.returncode or 0, out.decode(errors="replace").strip()


async def prepare(w, progress) -> tuple[str, str]:
    """The folder the worker runs in, and its branch when it has a worktree."""
    base = Path(w.dir).expanduser() if w.dir else None
    if base and not base.is_dir():
        raise SandboxError(f"{w.dir} isn't a folder")
    workdir, branch = base, ""
    if "worktree" in w.sandbox:
        if not base:
            raise SandboxError("a worktree needs a folder inside a git repository")
        rc, top = await run("git", "-C", str(base), "rev-parse", "--show-toplevel")
        if rc:
            raise SandboxError(f"{w.dir} isn't in a git repository, so it can't get a worktree")
        root = Path(top)
        branch = f"claudebot/{w.name}"
        rc, _ = await run("git", "-C", str(root), "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
        if rc == 0:
            branch += f"-{w.id[:4]}"
        path = WORKTREES_DIR / f"{root.name}-{branch.removeprefix('claudebot/')}"
        path.parent.mkdir(parents=True, exist_ok=True)
        progress("Making a worktree")
        rc, out = await run("git", "-C", str(root), "worktree", "add", "-b", branch, str(path), "HEAD")
        if rc:
            raise SandboxError(f"git worktree add failed: {out[-300:]}")
        workdir = path / base.resolve().relative_to(root)
    if not workdir:
        if w.sandbox:
            workdir = SANDBOX_DIR / w.id / "work"
            workdir.mkdir(parents=True, exist_ok=True)
        else:
            workdir = Path.home()
    if "docker" in w.sandbox:
        await ensure_image(progress)
    return str(workdir), branch


async def ensure_image(progress):
    if shutil.which("docker") is None:
        raise SandboxError("docker isn't installed")
    rc, _ = await run("docker", "image", "inspect", IMAGE)
    if rc == 0:
        return
    progress("Building the sandbox image (first time only)")
    rc, out = await run("docker", "build", "-t", IMAGE, "-", stdin=DOCKERFILE.encode(), timeout=900)
    if rc:
        raise SandboxError(f"building the sandbox image failed: {out[-400:]}")


def note(w) -> str:
    """What the worker is told about its fences."""
    lines = []
    if w.branch:
        lines.append(f"You work in a git worktree on the branch {w.branch}, apart from my own checkout. "
                     "Commit your work on that branch when you are done; don't merge or push it.")
    if "docker" in w.sandbox:
        lines.append(f"You run inside a throwaway Docker container that only sees {w.workdir}. "
                     "My desktop, my other files and my MCP servers aren't there. Install what you need.")
    elif "bwrap" in w.sandbox:
        lines.append(f"You are sandboxed: you can only write inside {w.workdir} and /tmp, "
                     "and shell commands run in a bubblewrap sandbox.")
    return " ".join(lines)


def apply(w, opts: dict):
    """Fence the session's options in."""
    if "docker" in w.sandbox:
        opts["cli_path"] = str(_docker_wrapper(w))
        opts["mcp_servers"] = {}
        opts["extra_args"] = {**opts.get("extra_args", {}), "strict-mcp-config": None}
    elif "bwrap" in w.sandbox:
        opts["sandbox"] = {"enabled": True, "autoAllowBashIfSandboxed": True, "allowUnsandboxedCommands": False}
        allowed = [Path(w.workdir).resolve(), Path("/tmp")]
        opts["hooks"] = {"PreToolUse": [HookMatcher(matcher="Write|Edit|MultiEdit|NotebookEdit",
                                                    hooks=[_write_guard(allowed)])]}


def _write_guard(allowed: list[Path]):
    async def guard(data, tool_use_id, context):
        inp = data.get("tool_input") or {}
        target = inp.get("file_path") or inp.get("notebook_path") or ""
        path = Path(target).expanduser().resolve() if target else None
        if path is None or any(path.is_relative_to(a) for a in allowed):
            return {}
        return {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"Sandboxed: you can only write inside {allowed[0]} and /tmp.",
        }}
    return guard


def _cli() -> Path:
    bundled = Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude"
    found = bundled if bundled.exists() else Path(shutil.which("claude") or "claude")
    return found.resolve()


def _docker_wrapper(w) -> Path:
    """An executable that stands in for the claude CLI and runs it in a container instead. The SDK
    talks to it over stdin and stdout exactly as it would to claude itself."""
    home = SANDBOX_DIR / w.id
    config = home / "claude"
    _container_config(config)
    workdir = Path(w.workdir)
    mounts = [(str(_cli()), "/usr/local/bin/claude", "ro"), (str(CLAUDE_HOME), str(CLAUDE_HOME), "ro"),
              (str(config), str(config), "rw"), (str(workdir), str(workdir), "rw")]
    if w.branch:
        # a worktree's .git file points into the main repository's .git folder
        common = (workdir / ".git").read_text().split("gitdir:", 1)[-1].strip().split("/worktrees/")[0]
        mounts.append((common, common, "rw"))
    args = ["docker", "run", "--rm", "-i", "--init", "--name", f"claudebot-{w.id}",
            "--user", f"{os.getuid()}:{os.getgid()}", "-e", "HOME=/tmp", "-e", f"CLAUDE_CONFIG_DIR={config}",
            "-w", str(workdir)]
    for src, dst, mode in mounts:
        args += ["-v", f"{src}:{dst}:{mode}"]
    script = home / "claude-in-docker"
    script.write_text(f"""#!/bin/sh
# Runs claude in a container for the worker {w.name}. Written by Claude Bot.
if [ "$1" = "-v" ] || [ "$1" = "--version" ]; then exec {shlex.quote(str(_cli()))} "$@"; fi
envs=""
for v in $(env | sed -n 's/^\\(\\(CLAUDE\\|ANTHROPIC\\|ENABLE_CLAUDEAI\\)[A-Za-z0-9_]*\\)=.*/\\1/p'); do
  [ "$v" = CLAUDE_CONFIG_DIR ] || envs="$envs -e $v"
done
exec {shlex.join(args)} $envs {IMAGE} claude "$@"
""")
    script.chmod(0o755)
    return script


def _container_config(config: Path):
    """A config folder for claude in a container: my settings without hooks (they call into my
    desktop), my login, and links to my skills, plugins and agents."""
    config.mkdir(parents=True, exist_ok=True)
    try:
        settings = json.loads((CLAUDE_HOME / "settings.json").read_text())
    except (OSError, ValueError):
        settings = {}
    for key in ("hooks", "statusLine", "sandbox"):
        settings.pop(key, None)
    (config / "settings.json").write_text(json.dumps(settings, indent=2))
    creds = CLAUDE_HOME / ".credentials.json"
    if creds.exists():
        shutil.copy2(creds, config / ".credentials.json")
        (config / ".credentials.json").chmod(0o600)
    try:
        state = json.loads((Path.home() / ".claude.json").read_text())
    except (OSError, ValueError):
        state = {}
    keep = ("oauthAccount", "userID", "hasCompletedOnboarding", "lastOnboardingVersion", "firstStartTime")
    (config / ".claude.json").write_text(json.dumps({k: state[k] for k in keep if k in state}))
    for name in SHARED:
        link, target = config / name, CLAUDE_HOME / name
        if target.exists() and not link.is_symlink():
            link.symlink_to(target)


async def cleanup(w):
    """Drop the worktree and scratch files. The branch stays, with whatever the worker committed."""
    if w.branch and w.workdir and Path(w.workdir).exists():
        rc, out = await run("git", "-C", w.workdir, "rev-parse", "--show-toplevel", "--git-common-dir")
        if rc == 0:
            top, common = out.splitlines()[:2]
            main = Path(w.workdir, common).resolve().parent  # the repository the worktree came from
            await run("git", "-C", str(main), "worktree", "remove", "--force", top)
    shutil.rmtree(SANDBOX_DIR / w.id, ignore_errors=True)
