"""Long-term memory: facts, preferences, projects and people I mention, kept across conversations.

A plain JSON file in ~/.local/share/claudebot. Everything in it goes into the system prompt when a
Claude session starts, and the model adds to it with the remember tool as we talk.
"""

import difflib
import json
import re
import time
import uuid

from .config import DATA_DIR, MEMORY_FILE

KINDS = ("fact", "preference", "project", "person")
LIMIT = 200  # oldest go first beyond this
PROMPT_CHARS = 8000


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
        del self.items[:-LIMIT]
        self._save()
        return m, True

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

    def prompt(self) -> str:
        """The block that goes into the system prompt, newest first when it has to be cut."""
        if not self.items:
            return "Nothing yet."
        lines, size = [], 0
        for m in reversed(self.items):
            line = f"- ({m['kind']}, {time.strftime('%-d %b %Y', time.localtime(m['ts']))}) {m['text']}"
            size += len(line) + 1
            if size > PROMPT_CHARS:
                break
            lines.append(line)
        return "\n".join(reversed(lines))
