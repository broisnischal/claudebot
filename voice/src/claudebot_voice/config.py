"""Paths and settings. The panel writes changes to ~/.config/claudebot/voice.json."""

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT.parent / "src"  # Claude Bot's windows, when I run from the source tree
MODELS = Path(os.environ.get("CLAUDEBOT_VOICE_MODELS") or ROOT / "models")
HOST = "127.0.0.1"
PORT = int(os.environ.get("CLAUDEBOT_VOICE_PORT", "47822"))
# Claude Bot hands the engine a fresh token on every launch; every socket and request must carry it.
TOKEN = os.environ.get("CLAUDEBOT_VOICE_TOKEN", "")
PARENT = int(os.environ.get("CLAUDEBOT_PARENT_PID", "0") or 0)

XDG_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
XDG_DATA = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
CONFIG_DIR = XDG_CONFIG / "claudebot"
SETTINGS_FILE = CONFIG_DIR / "voice.json"
LEGACY_SETTINGS = XDG_CONFIG / "voiceagent" / "settings.json"  # Jarvis, before it moved in here
DATA_DIR = XDG_DATA / "claudebot"
MEMORY_FILE = DATA_DIR / "memory.json"
RUNTIME_DIR = Path(os.environ.get("CLAUDEBOT_VOICE_RUNTIME") or Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "claudebot-voice")

MODELS_CHOICES = ["haiku", "sonnet", "opus"]

DEFAULTS = {
    "enabled": True,  # off: no listening and no speaking at all, until I turn it back on
    "name": "Jarvis",
    "model": "haiku",  # the fastest to its first word; sonnet and opus are a click away in the panel
    "voice": "jarvis",  # a blend of Kokoro's British male voices, see tts.py
    "speed": 1.1,  # a little brisk, still clear
    "effect": "jarvis",  # jarvis: EQ, compression and a little room on the voice. clean: none.
    "volume": 0.8,
    "autonomy": "full",  # full: nothing asks but wiping the machine. trust: destructive shell asks. ask: side effects ask.
    "input": "handsfree",  # handsfree: voice activity detection. ptt: only while Space is held.
    "barge_in": True,  # talking over the assistant cuts it off
    "announce": True,  # speak up when an agent finishes or needs me
    "endpoint_ms": 1100,  # silence that ends an utterance; patient, so a thinking pause doesn't end my turn
    "stt_model": "",  # empty: whatever voxtype's own config uses
    "input_device": "",  # empty: the system default
    "output_device": "",
    "music_volume": 0.6,
    "duck": 0.2,  # music level while either of us talks, as a share of music_volume
    "memory": True,  # remember facts about me across conversations
    "cwd": str(Path.home()),
}

# Values the panel may change, with how to coerce them.
EDITABLE = {
    "model": lambda v: v if v in MODELS_CHOICES else None,
    "voice": str,
    "speed": lambda v: min(1.5, max(0.7, float(v))),
    "effect": lambda v: v if v in ("jarvis", "clean") else None,
    "volume": lambda v: min(1.0, max(0.1, float(v))),
    "autonomy": lambda v: v if v in ("ask", "trust", "full") else None,
    "input": lambda v: v if v in ("handsfree", "ptt") else None,
    "barge_in": bool,
    "announce": bool,
    "endpoint_ms": lambda v: min(2500, max(400, int(v))),
    "stt_model": str,
    "input_device": str,
    "output_device": str,
    "music_volume": lambda v: min(1.0, max(0.0, float(v))),
    "duck": lambda v: min(1.0, max(0.0, float(v))),
    "memory": bool,
    "enabled": bool,
    "name": lambda v: str(v).strip()[:24] or None,
}


class Settings(dict):
    @classmethod
    def load(cls) -> "Settings":
        s = cls(DEFAULTS)
        for path in (SETTINGS_FILE, LEGACY_SETTINGS):
            try:
                saved = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            s.update({k: v for k, v in saved.items() if k in DEFAULTS})
            if saved.get("turns", 0) < 3:
                # the old defaults: a pause that answered half-finished questions, a slower model and voice
                for key, old in (("endpoint_ms", 800), ("model", "sonnet"), ("speed", 0.96)):
                    if saved.get(key) == old:
                        s[key] = DEFAULTS[key]
                s["turns"] = 3
                s.save()
            if path == LEGACY_SETTINGS:
                s.save()  # carried over once; from here on claudebot keeps its own copy
            break
        return s

    def save(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(dict(self), indent=2))

    def patch(self, changes: dict) -> dict:
        applied = {}
        for key, value in changes.items():
            coerce = EDITABLE.get(key)
            if coerce is None:
                continue
            try:
                value = coerce(value)
            except (TypeError, ValueError):
                continue
            if value is not None and self.get(key) != value:
                self[key] = applied[key] = value
        if applied:
            self.save()
        return applied
