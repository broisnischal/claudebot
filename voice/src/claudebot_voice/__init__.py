def main() -> None:
    import logging
    import os
    import sys

    import uvicorn

    from .config import HOST, PORT

    # Claude Bot may have been started from a Claude Code session or a tmux pane; their variables
    # would make my own Claude session a "child" and make tower think I am that pane's agent.
    for key in [k for k in os.environ if k.startswith(("CLAUDE_CODE_", "CLAUDECODE")) or k in ("CLAUDE_PID", "CLAUDE_EFFORT", "TMUX", "TMUX_PANE")]:
        del os.environ[key]
    sys.setswitchinterval(0.002)  # hand the GIL to the audio callback sooner than the default 5 ms
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("phonemizer").setLevel(logging.ERROR)  # "words count mismatch" on every sentence
    uvicorn.run("claudebot_voice.server:app", host=HOST, port=PORT, log_level="warning", access_log=False)
