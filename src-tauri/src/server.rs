//! Tiny localhost HTTP server that Claude Code hooks (and anything else) can poke.
//!
//!   POST /claudebot/hook   Claude Code hook JSON on the body
//!   POST /claudebot/play   an animation name on the body, e.g. `celebrate`
//!   GET  /claudebot/health

use serde_json::{json, Value};
use std::{io::Read, thread};
use tauri::{AppHandle, Emitter, Runtime};
use tiny_http::{Method, Response, Server};

// Tool payloads can carry whole files; the pet only needs the first few fields.
const MAX_BODY: u64 = 16 * 1024 * 1024;

pub fn spawn<R: Runtime>(app: AppHandle<R>, port: u16) {
    thread::spawn(move || {
        let server = match Server::http(("127.0.0.1", port)) {
            Ok(server) => server,
            Err(e) => {
                eprintln!("claudebot: can't listen on 127.0.0.1:{port}: {e}");
                return;
            }
        };
        for mut req in server.incoming_requests() {
            // Browsers attach Origin to cross-site requests; hooks never do.
            let from_browser = req.headers().iter().any(|h| h.field.equiv("Origin"));
            let mut body = Vec::new();
            let _ = req.as_reader().take(MAX_BODY).read_to_end(&mut body);

            let status = match (req.method(), req.url()) {
                _ if from_browser => 403,
                (Method::Post, "/claudebot/hook") => match serde_json::from_slice::<Value>(&body) {
                    Ok(payload) => {
                        let _ = app.emit("hook", slim(&payload));
                        204
                    }
                    Err(_) => 400,
                },
                (Method::Post, "/claudebot/play") => {
                    let name = String::from_utf8_lossy(&body).trim().to_string();
                    let _ = app.emit("play", name);
                    204
                }
                (Method::Get, "/claudebot/health") => 204,
                _ => 404,
            };
            let _ = req.respond(Response::empty(status));
        }
    });
}

fn text(v: &Value, key: &str) -> Value {
    match v.get(key) {
        Some(Value::String(s)) => Value::String(s.chars().take(160).collect()),
        Some(Value::Bool(b)) => Value::Bool(*b),
        Some(Value::Null) | None => Value::Null,
        Some(other) => Value::String(other.to_string().chars().take(160).collect()),
    }
}

/// Keeps the fields the pet animates on and drops the rest (file contents, diffs).
fn slim(p: &Value) -> Value {
    let input = p.get("tool_input").unwrap_or(&Value::Null);
    let file = ["file_path", "notebook_path", "path"]
        .iter()
        .map(|k| text(input, k))
        .find(|v| !v.is_null())
        .unwrap_or(Value::Null);
    json!({
        "event": text(p, "hook_event_name"),
        "session": text(p, "session_id"),
        "cwd": text(p, "cwd"),
        "title": text(p, "session_title"),
        "source": text(p, "source"),
        "tool": text(p, "tool_name"),
        "agent": text(p, "agent_id"),
        "agentType": text(p, "agent_type"),
        "kind": text(p, "notification_type"),
        "message": text(p, "message"),
        "interrupt": text(p, "is_interrupt"),
        "error": text(p, "error"),
        "input": {
            "file": file,
            "command": text(input, "command"),
            "pattern": text(input, "pattern"),
            "query": text(input, "query"),
            "url": text(input, "url"),
            "description": text(input, "description"),
            "subagentType": text(input, "subagent_type"),
        },
    })
}
