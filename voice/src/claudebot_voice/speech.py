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


class Chunker:
    """Feed it text deltas, get back whole sentences. Code blocks are dropped."""

    def __init__(self):
        self.raw = ""
        self.buf = ""
        self.in_code = False

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
        return out
