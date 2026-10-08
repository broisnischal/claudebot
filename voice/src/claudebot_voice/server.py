"""HTTP and WebSocket front door. Local only: Host must be this server, and every request but the
health check carries the token Claude Bot handed the engine at launch."""

import asyncio
import hmac
import json
import logging
import os
import re
import signal
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from .config import PARENT, PORT, TOKEN
from .session import Hub

log = logging.getLogger("claudebot_voice.server")
hub = Hub()
LOCAL = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
# Claude Bot's own windows: the bundled app, or `tauri dev`'s server on a loopback port.
APP_ORIGINS = {"tauri://localhost", "http://tauri.localhost", "https://tauri.localhost"}
LOOPBACK = re.compile(r"^http://(127\.0\.0\.1|localhost)(:\d+)?$")


def trusted(host: str | None, origin: str | None, token: str | None, need_token: bool = True) -> bool:
    # Any web page I visit could otherwise reach this socket and drive a shell on my machine. A page
    # on the internet fails the origin check; anything local still needs the per-launch token.
    if host not in LOCAL:
        return False
    if origin is not None and origin not in APP_ORIGINS and not LOOPBACK.match(origin):
        return False
    return not need_token or not TOKEN or hmac.compare_digest(token or "", TOKEN)


async def orphan_watch():
    """Quit when Claude Bot does, even if it died without stopping me."""
    while PARENT:
        await asyncio.sleep(2)
        try:
            os.kill(PARENT, 0)
        except ProcessLookupError:
            log.info("claudebot is gone, quitting")
            os.kill(os.getpid(), signal.SIGTERM)
            return
        except PermissionError:
            pass


@asynccontextmanager
async def lifespan(app):
    watch = asyncio.create_task(orphan_watch())
    await hub.start()
    yield
    watch.cancel()
    await hub.stop()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def guard(request: Request, call_next):
    open_door = request.url.path == "/api/health"
    token = request.headers.get("x-claudebot-token") or request.query_params.get("token")
    if not trusted(request.headers.get("host"), request.headers.get("origin"), token, not open_door):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/health")
async def health():
    return {"ok": True, "clients": len(hub.clients), "phase": hub.phase, "call": hub.call,
            "model": hub.settings["model"], "claude": hub.brain.client is not None, "audio": hub.device_error()}


@app.post("/api/{action}")
async def control(action: str, request: Request):
    """For hotkeys and scripts: call | call-start | call-end | ptt-start | ptt-stop | interrupt | mute | say |
    voice | voice-on | voice-off."""
    if action == "call":
        await hub.toggle_call()
    elif action == "call-start":
        await hub.start_call()
    elif action == "call-end":
        await hub.end_call()
    elif action == "ptt-start":
        hub.ptt_start()
    elif action == "ptt-stop":
        hub.ptt_stop()
    elif action == "interrupt":
        await hub.interrupt()
    elif action == "mute":
        hub.set_muted(not hub.muted)
    elif action in ("voice", "voice-on", "voice-off"):
        await hub.set_voice({"voice": None, "voice-on": True, "voice-off": False}[action])
    elif action == "say":
        text = (await request.body()).decode(errors="replace")
        await hub.handle_text(text, typed=True)
    else:
        return JSONResponse({"error": f"unknown action {action}"}, status_code=404)
    return {"ok": True, "phase": hub.phase, "call": hub.call}


@app.websocket("/ws")
async def socket(ws: WebSocket):
    if not trusted(ws.headers.get("host"), ws.headers.get("origin"), ws.query_params.get("token")):
        await ws.close(code=1008)
        return
    await ws.accept()
    await hub.join(ws)
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("text"):
                try:
                    data = json.loads(msg["text"])
                except ValueError:
                    continue
                await hub.on_message(data, ws)
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("socket error")
    finally:
        hub.leave(ws)
