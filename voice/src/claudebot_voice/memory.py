"""Long-term memory: facts, preferences, projects and people I mention, kept across conversations,
and the tasks the voice did for me, so a new session knows what is already done or under way.

A plain JSON file in ~/.local/share/claudebot. Everything in it goes into the system prompt when a
Claude session starts. The model adds facts with the remember tool as we talk; the brain logs a
task after every turn that did something.
"""

import difflib
import json
import re
import time
import uuid

from .config import DATA_DIR, MEMORY_FILE

KINDS = ("fact", "preference", "project", "person", "task")
LIMIT = 200  # oldest go first beyond this
TASK_LIMIT = 40  # tasks have their own cap, so a busy day never pushes out what it knows about me
PROMPT_CHARS = 8000
TASK_PROMPT_CHARS = 3000


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


class Memory:
    def __init__(self):
        self.items: list[dict] = []
        try:
            self.items = [m for m in json.loads(MEMORY_FILE.read_text()) if m.get("text")]
        except (OSError, ValueError):
            pass

    def _save(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = MEMORY_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.items, indent=2, ensure_ascii=False))
        tmp.replace(MEMORY_FILE)

    def add(self, text: str, kind: str = "fact") -> tuple[dict, bool]:
        """(the memory, whether it is new). A near duplicate updates the old entry instead."""
        text = re.sub(r"\s+", " ", text).strip()[:500]
        kind = kind if kind in KINDS else "fact"
        key = _norm(text)
        for m in self.items:
            if difflib.SequenceMatcher(None, _norm(m["text"]), key).ratio() > 0.88:
                m.update(text=text, kind=kind, ts=time.time())
                self._save()
                return m, False
        m = {"id": uuid.uuid4().hex[:8], "text": text, "kind": kind, "ts": time.time()}
        self.items.append(m)
        self._trim()
        self._save()
        return m, True

    def _trim(self):
        keep, seen = [], {True: 0, False: 0}
        for m in reversed(self.items):
            task = m["kind"] == "task"
            seen[task] += 1
            if seen[task] <= (TASK_LIMIT if task else LIMIT):
                keep.append(m)
        self.items = keep[::-1]

    def find(self, query: str) -> list[dict]:
        q = _norm(query)
        if not q:
            return []
        exact = [m for m in self.items if m["id"] == query.strip()]
        if exact:
            return exact
        words = set(q.split())
        scored = []
        for m in self.items:
            t = _norm(m["text"])
            score = difflib.SequenceMatcher(None, t, q).ratio() + len(words & set(t.split())) / max(1, len(words))
            if q in t:
                score += 1
            scored.append((score, m))
        scored.sort(key=lambda x: -x[0])
        return [m for s, m in scored[:5] if s >= 0.9]

    def forget(self, id_or_query: str) -> list[dict]:
        hits = self.find(id_or_query)[:1]
        if hits:
            self.items = [m for m in self.items if m["id"] != hits[0]["id"]]
            self._save()
        return hits

    def remove(self, mid: str) -> bool:
        before = len(self.items)
        self.items = [m for m in self.items if m["id"] != mid]
        if len(self.items) != before:
            self._save()
            return True
        return False

    def clear(self):
        self.items = []
        self._save()

    def prompt(self, tasks: bool = False) -> str:
        """The facts (or the tasks) that go into the system prompt, newest first when it has to be cut."""
        items = [m for m in self.items if (m["kind"] == "task") == tasks]
        if not items:
            return "Nothing yet."
        lines, size = [], 0
        for m in sorted(items, key=lambda m: -m["ts"]):
            when = time.strftime("%-d %b %H:%M" if tasks else "%-d %b %Y", time.localtime(m["ts"]))
            line = f"- ({when}) {m['text']}" if tasks else f"- ({m['kind']}, {when}) {m['text']}"
            size += len(line) + 1
            if size > (TASK_PROMPT_CHARS if tasks else PROMPT_CHARS):
                break
            lines.append(line)
        return "\n".join(reversed(lines))
