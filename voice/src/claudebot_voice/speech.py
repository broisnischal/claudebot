"""Turn streamed model text into speakable sentences."""

import re

FENCE = "```"
LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
URL = re.compile(r"https?://\S+")
MARKUP = re.compile(r"\*\*|__|(?<!\w)[*_](?=\S)|(?<=\S)[*_](?!\w)|`|^\s*#+\s*|^\s*(?:[-*+]|\d+[.)])\s+", re.M)
BOUNDARY = re.compile(r"(?<=[.!?])[\"')\]]*\s+|\n+")
LONG = 220


def speakable(text: str) -> str:
    text = LINK.sub(r"\1", text)
    text = URL.sub("the link", text)
    text = MARKUP.sub("", text)
    text = text.replace("~/", "home/").replace(" & ", " and ")
    text = text.replace("\u2014", ", ").replace("\u2013", " to ")
    return re.sub(r"\s+", " ", text).strip()


SENTENCE_END = re.compile(r"(?<!\.\.)(?<=[.!?])[\"')\]]*(?:\n+|(?=\s|$))|\n+")
# "Sure." or "Okay," up front would use up a one-sentence answer before it says anything
OPENER = re.compile(r"^(sure|ok(ay)?|alright|all right|got it|right)[,.!]\s+(?=\S)", re.I)


def clip(text: str, sentences: int) -> str:
    """The first few sentences of a reply: the most the voice says, however much the model wrote."""
    text = OPENER.sub("", text.strip())
    for i, m in enumerate(SENTENCE_END.finditer(text), 1):
        if i == sentences:
            return text[: m.end()]
    return text


CLAUSE = re.compile(r"(?<=[,;:])\s+")
# The first piece is what I wait for, and synthesis time grows with its length: it goes out at the
# first clause break after a few words, or at a word break once it runs long without one.
FIRST_WORDS = 4
FIRST_MAX_WORDS = 12
WEAK = re.compile(r"^(the|a|an|of|to|for|in|on|at|by|with|from|and|or|but|is|are|was|my|your|its|their|this|that)$", re.I)


class Chunker:
    """Feed it text deltas, get back whole sentences. Code blocks are dropped. The very first piece may
    be a clause ("It's Thursday,") so the first word is heard while the rest is still being written."""

    def __init__(self):
        self.raw = ""
        self.buf = ""
        self.in_code = False
        self.first = True

    def feed(self, delta: str) -> list[str]:
        self.raw += delta
        while True:
            i = self.raw.find(FENCE)
            if self.in_code:
                if i < 0:
                    self.raw = self.raw[-2:]
                    break
                self.raw, self.in_code = self.raw[i + 3 :], False
            else:
                if i < 0:
                    # keep trailing backticks back: they may be the start of a fence
                    keep = len(self.raw) - len(self.raw.rstrip("`"))
                    self.buf += self.raw[: len(self.raw) - keep]
                    self.raw = self.raw[len(self.raw) - keep :]
                    break
                self.buf += self.raw[:i] + "\n"
                self.raw, self.in_code = self.raw[i + 3 :], True
        return self._split(final=False)

    def flush(self) -> list[str]:
        if not self.in_code:
            self.buf += self.raw
        self.raw = ""
        return self._split(final=True)

    def _split(self, final: bool) -> list[str]:
        out = []
        while True:
            m = BOUNDARY.search(self.buf)
            if self.first:
                # the earliest of: the sentence end, a clause break after a few words, the word cap
                options = [m] if m else []
                c = next((c for c in CLAUSE.finditer(self.buf) if len(self.buf[: c.start()].split()) >= FIRST_WORDS), None)
                if c:
                    options.append(c)
                words = list(re.finditer(r"\S+\s+", self.buf))
                if len(words) > FIRST_MAX_WORDS:
                    # break after a word that doesn't leave the phrase hanging ("for the | UI")
                    cut = next((w for w in reversed(words[FIRST_WORDS - 1:FIRST_MAX_WORDS])
                                if not WEAK.match(w.group().strip())), words[FIRST_MAX_WORDS - 1])
                    options.append(cut)
                m = min(options, key=lambda x: x.end()) if options else None
            if m:
                piece, self.buf = self.buf[: m.end()], self.buf[m.end() :]
            elif len(self.buf) > LONG:
                cut = max(self.buf.rfind(c, 0, LONG) for c in ",;:")
                if cut < 60:
                    cut = self.buf.rfind(" ", 0, LONG)
                cut = cut if cut > 0 else LONG
                piece, self.buf = self.buf[: cut + 1], self.buf[cut + 1 :]
            elif final and self.buf.strip():
                piece, self.buf = self.buf, ""
            else:
                break
            text = speakable(piece)
            if any(c.isalnum() for c in text):
                out.append(text)
                self.first = False
        return out
