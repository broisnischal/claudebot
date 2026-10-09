"""Which model does what: Opus thinks and plans, Sonnet implements and executes, Haiku is quick.

Agents Claude Bot starts get a model picked from what their task asks for (pick):
- Opus for thinking work: planning, design, debugging, investigating, research, review.
- Sonnet for doing work: implementing a known change, tests, fixes, renames, docs, running things.
- opusplan for a build from scratch: it starts in plan mode on Opus, and once the plan is accepted
  Claude Code carries it out on Sonnet.
I can always name the model myself ("use opus").

Claude Bot's own calls each have a role (ROLES): the voice and the agent profiles on Haiku, because
they run often and speed matters; approvals, questions and stalls on Sonnet; the look over the whole
fleet on Opus, because it has to reason about several agents at once.
"""

import re

OPUS, SONNET, HAIKU, OPUSPLAN = "opus", "sonnet", "haiku", "opusplan"
CHOICES = (OPUS, SONNET, HAIKU, OPUSPLAN)
ROLES = {"judge": SONNET, "review": OPUS, "profile": HAIKU}

# Verbs and phrases that mark a task as thinking or as doing. Matched as whole words.
THINK = [
    "plan", "planning", "design", "architect", "architecture", "investigate", "diagnose", "debug", "root cause",
    "figure out", "find out why", "why does", "why is", "why are", "research", "review", "audit", "analyze",
    "analyse", "analysis", "evaluate", "compare", "decide", "strategy", "propose", "proposal", "explore",
    "understand", "explain", "brainstorm", "spec", "rfc", "trade-offs", "tradeoffs", "threat model",
    "assess", "study", "think through", "reason about", "what's wrong", "what is wrong", "learn how",
]
DO = [
    "implement", "write tests", "write a test", "add tests", "add a test", "fix the test", "fix the tests",
    "fix the typo", "fix typos", "fix lint", "rename", "update", "bump", "upgrade", "run the tests", "run tests",
    "run the build", "format", "lint", "apply", "wire up", "hook up", "convert", "port", "generate",
    "scaffold", "install", "set up", "configure", "delete", "remove", "move", "clean up", "commit",
    "open a pr", "make a pr", "push", "document", "docs", "readme", "changelog", "translate", "add",
    "replace", "deploy", "release", "fix", "write", "code", "build", "create", "refactor", "migrate",
    "check", "run", "restart", "start", "stop", "list", "show", "open", "find", "search", "look at", "read",
]
# Starting something new from nothing: worth a plan on Opus, then the work on Sonnet.
BUILD = re.compile(r"\b(build|create|make|develop|write|start)\b.{0,40}\b(new |an? |the )?(app|application|"
                   r"service|system|feature|tool|project|library|cli|api|site|website|dashboard|bot|game|engine|"
                   r"pipeline|integration|prototype|mvp)\b|\bdesign and (build|implement)|\bplan and (build|implement)"
                   r"|\bend[- ]to[- ]end\b|\bfrom scratch\b", re.I)


def _hits(words: list[str], text: str) -> list[str]:
    return [w for w in words if re.search(rf"(?<![\w-]){re.escape(w)}(?![\w-])", text)]


def pick(task: str) -> tuple[str, str]:
    """(model, why) for an agent about to start on this task."""
    text = " ".join(str(task or "").lower().split())
    think = _hits(THINK, text)
    # "find" in "find out why" isn't doing, and naming the problem ("the build is slow") is common
    # in thinking tasks, so doing words only count outside the thinking phrases, and count half
    rest = text
    for w in think:
        rest = re.sub(rf"(?<![\w-]){re.escape(w)}(?![\w-])", " ", rest)
    do = _hits(DO, rest)
    if BUILD.search(text):
        return OPUSPLAN, "a build from scratch: Opus plans it, Sonnet carries it out"
    if think and do and len(text.split()) > 30:
        return OPUSPLAN, f"it needs both thinking ({think[0]}) and doing ({do[0]})"
    if think and 2 * len(think) >= len(do):
        return OPUS, f"a thinking task ({', '.join(think[:2])})"
    if do:
        return SONNET, f"an implementation task ({', '.join(do[:2])})"
    if len(text.split()) <= 12:
        return SONNET, "a short errand"
    return OPUSPLAN, "not clearly one or the other, so it plans on Opus and works on Sonnet"


def claude_command(model: str) -> str:
    """The command an agent pane starts with. opusplan only thinks on Opus in plan mode, so it
    starts there; accepting the plan moves it on to Sonnet."""
    if model == OPUSPLAN:
        return "claude --model opusplan --permission-mode plan"
    return f"claude --model {model}"
