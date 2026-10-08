# Claude Bot

A pixel desktop pet modeled on Clawd, the little critter from the Claude Code terminal. It lives along the bottom of the screen in a transparent window that floats above everything else, walks around, chases the cursor, gets the zoomies and naps. Hooked up to Claude Code, it acts out whatever Claude is doing, brings in a tiny helper for every subagent, and keeps nagging until I notice that a long turn has finished.

Runs on Linux, Windows and macOS. Built with [Tauri 2](https://tauri.app), so the app is a few MB instead of a bundled browser.

## What it does

| Claude Code is... | Hook | The pet... |
| --- | --- | --- |
| starting a session | `SessionStart` | waves hello |
| thinking | `UserPromptSubmit`, `PostToolUse` | shows the spinner verb ("Pontificating...") and acts it out, see below |
| running a command or MCP tool | `PreToolUse` | puts on a hard hat and hammers out a brick pile |
| running tests | `PreToolUse` (Bash with `test`, `pytest`, `jest`...) | goggles on, bubbling flask |
| editing files | `PreToolUse` (Edit, Write) | types on a tiny laptop |
| reading a file | `PreToolUse` (Read) | reads a book, flipping pages |
| searching code | `PreToolUse` (Grep, Glob) | squints through a magnifying glass |
| on the web | `PreToolUse` (WebFetch, WebSearch) | surfs a wave |
| planning | `PreToolUse` (TodoWrite) | ticks off a clipboard checklist |
| handing off to a subagent | `PreToolUse` (Agent) | shouts into a megaphone |
| running subagents | `SubagentStart`, `SubagentStop` | a mini Clawd walks in per agent, works with its own tiny tools, then checks off and leaves |
| waiting on a permission prompt or question | `PermissionRequest`, `Notification` | jumps and waves a `!` at me, plus a desktop notification |
| done after a long turn | `Stop` | confetti, then holds up a "done" sign and hops toward my cursor every 45 seconds until I click it |
| hitting an API error | `StopFailure` | sulks under a rain cloud |
| interrupted with Esc | `PostToolUseFailure` | shrugs |
| compacting the conversation | `PreCompact` | gets flattened in a hydraulic press |
| closing the last session | `SessionEnd` | yawns, puts on a nightcap and sleeps |

A status line above the pet reads like Claude Code's own: `Running npm test`, `Editing brain.js`, `pc: screenshot`, `Done in 2m 14s`, with `+2 agents` or the project name when more than one thing is going on. With several Claude Code sessions open, it follows whichever one needs me most: a permission prompt beats work in progress, and work in progress beats a finished turn.

**Thinking styles.** Each of Claude Code's 187 spinner verbs maps to a little act: Cooking and Flambéing get a chef hat and a steaming pot, Enchanting gets a wizard hat and wand, Pontificating climbs onto a soapbox, Computing spins gears, Hatching sits on an egg until it cracks, Vibing puts on shades and dances, Sprouting waters a flower, Hyperspacing levitates with an orbiting planet, Thundering stands under a storm cloud, Doodling sketches, Tinkering fixes a robot, Flibbertigibbeting spins in place, and Meandering just wanders off.

**Reminders.** A turn under 10 seconds just gets confetti. A longer one leaves the pet holding a "done" sign until I click it or send the next prompt; turns over 20 seconds also send a desktop notification. Permission prompts always notify.

**On its own** it strolls along the bottom of the screen, gets the zoomies, chases the cursor and sits down to look up at it, trips over, sneezes, dances, stretches, and notices when the cursor comes close. Its eyes follow the cursor around the screen. After 5 quiet minutes it falls asleep.

**Interactions:** drag it anywhere (let go mid-air and it falls back to the floor), click to poke it (four quick pokes make it dizzy), right-click for the menu. Only the pet itself catches the mouse; clicks on the empty parts of its window go straight through to whatever is underneath. The same menu sits in the system tray, and the tray tooltip shows the current status.

**Menu:** React to Claude Code, Play animation, Thinking styles, Roam around the screen, Show status text, Notify when Claude is done, Size, Color (pink, Claude orange, mint, sky, lavender, ghost), Always on top, Start at login.

## Talk to it

Claude Bot is also my voice assistant: everything Jarvis (`~/voiceagent`) did now lives here. Hover over or tap the pet and a mic button appears above its head. Click it and the call goes live; click it again to hang up. While the voice is busy, a small strip in the bottom-left corner of the screen shows the call orb (waveform bars while either of us talks, a spinner while it thinks, a `!` when it needs my OK, grey when muted) and what it is doing in plain words ("Listening", "Checking the fleet", the sentence it is saying). Click the orb there to hang up, the text to open the voice panel. Double-tap the pet for the panel too.

**Voice on and off.** Off means no listening and no speaking at all: the call ends, any reply in progress goes silent, and the mic stays closed until I turn it back on. Typed messages still get answers, in the transcript only, and music keeps playing. The switch survives restarts. Ways to flip it: "Voice on" in the right-click menu, the switch at the top of the panel, `V` while the pet or the panel has focus, `SUPER + ALT + V`, or `claudebot --voice` (`--voice-on`, `--voice-off`). Clicking the pet's mic while the voice is off turns it on and goes live.

It is a full duplex call. I talk, it answers out loud, and talking over it cuts it off. Same persona and tools as Jarvis:

- **Fleet:** what every Claude Code agent in my tmux panes is doing (through tower), what they said, handing them work, spawning, interrupting and approving them. It speaks up when an agent finishes or needs me.
- **Desktop:** the pc plugin's tools (screenshots, windows, keyboard and mouse, processes, services, logs), plus a shell, files and the web.
- **Music:** "play some lo-fi", "skip", "pause", "louder". Tracks come from YouTube through yt-dlp and mpv and play through Claude Bot's own speaker stream, so the music fades down while either of us talks and the echo canceller never mistakes a song for me.
- **Memory:** it remembers facts, preferences, projects and people I mention, across conversations. It keeps them in `~/.local/share/claudebot/memory.json` and puts them in the session's context at the start of every conversation. The panel's Memory tab lists them; "forget that" or the panel removes one.
- **Approvals:** risky tool calls ask out loud ("Okay to ...?"). "Yes", "no" or "always" answers, or the card in the panel.
- **The pet:** "fly", "dance", "go to sleep", "zoomies", "wave", "party" and the rest of its moves, reactions, scenes and thinking styles. The `pet_action` tool runs whatever the pet can do.

It doesn't narrate ("Checking", "On it"); what it is doing shows in the HUD instead. Agent names go through speech to text, so they match loosely ("claudia bot" finds claudebot), but never so loosely that a message lands on the wrong agent: if two names fit about equally, it asks. An agent spawned into a folder Claude Code hasn't seen stops on the folder trust question; the voice says so and trusts the folder only when I say yes.

The panel has the orb and captions, the dock (call, mute, type), the music controls, and four tabs: Fleet, Conversation, Memory and Settings (model, voice, effect, volume, speed, microphone, speaker, access level, hands-free or push to talk, interrupting, announcements, pause length, music volume, ducking, memory). Settings save to `~/.config/claudebot/voice.json`; on first launch it copies my Jarvis settings from `~/.config/voiceagent/settings.json`. Keys in the panel: `C` call, `M` mute, `Space` held is push to talk, `Enter` type, `D` drawer, `Y` / `N` / `A` answer an approval, `Esc` interrupt or close.

From a hotkey or a script, a second `claudebot` hands the command to the running one:

```sh
claudebot --call         # start or end a call
claudebot --interrupt    # stop talking and cancel the answer
claudebot --mute
claudebot --panel
claudebot --say "what are my agents doing?"
claudebot --voice        # voice on or off
```

### How the voice works

```
mic -> PortAudio at 48 kHz, 10 ms blocks
    -> WebRTC echo cancellation, noise suppression and gain (against everything the speaker plays)
    -> 16 kHz -> Silero VAD cuts utterances -> voxtype transcribes
    -> a Claude Code session through the Agent SDK (fleet, pc, shell, web, music and memory tools)
    -> sentences stream into Kokoro TTS -> the Jarvis EQ, compressor and room -> speaker
music: yt-dlp -> mpv (raw PCM on a pipe) -> mixed under the voice, ducked while anyone talks
```

The engine is the Python project in `voice/`. Claude Bot starts it with `uv run` when it launches, hands it a fresh token, restarts it if it dies, and stops it on quit. It listens on `127.0.0.1:47822` (`CLAUDEBOT_VOICE_PORT`) and only accepts Claude Bot's own windows with that token. Audio never goes through a window: WebKitGTK has no echo canceller, so the engine owns the mic and the speaker, and the windows only watch and send commands. The mic is only open during a call or push to talk.

Voice needs Linux with `uv`, `voxtype`, `tower`, `mpv` and `yt-dlp` on the PATH, and the models in `voice/models` (not in git):

```sh
cd voice/models
curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
curl -LO https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx
```

Without them the pet still works and the menu says "Voice unavailable". An installed build looks for the engine where it was built, or in `CLAUDEBOT_VOICE_DIR`.

## Run it

Prerequisites: [Rust](https://rustup.rs), Node 18+, and the [Tauri system dependencies](https://tauri.app/start/prerequisites/) for the OS (on Linux that's WebKitGTK 4.1 and libayatana-appindicator).

```sh
npm install
npm run dev      # run it
npm run build    # installers land in src-tauri/target/release/bundle/
```

`npm run build` produces `.deb`, `.rpm` and `.AppImage` on Linux, `.msi` and `.exe` on Windows, `.dmg` and `.app` on macOS. Each OS builds its own installers, so `.github/workflows/release.yml` does all three in CI: push a tag like `v0.1.0` and the installers show up in a draft GitHub release.

The CI builds aren't code signed. On macOS, right-click the app and pick Open the first time (or run `xattr -cr "/Applications/Claude Bot.app"`). On Windows, SmartScreen needs a "More info, Run anyway".

## Connect it to Claude Code

Right-click the pet and tick **React to Claude Code**. That adds hooks to `~/.claude/settings.json` (or `$CLAUDE_CONFIG_DIR/settings.json`), keeps a one-time backup next to it as `settings.json.claudebot-backup`, and leaves every other setting and hook alone. Restart open Claude Code sessions afterwards if they don't pick it up. Untick it to remove exactly the entries it added. When a newer version listens to more events, it updates its own entries on launch.

From a terminal instead:

```sh
claudebot --install-hooks
claudebot --uninstall-hooks
```

Each hook is one line that pipes Claude Code's event JSON to the pet:

```sh
curl -s -m 2 --data-binary @- http://127.0.0.1:47821/claudebot/hook || true
```

Events: `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `PermissionRequest`, `Notification`, `Stop`, `StopFailure`, `SubagentStart`, `SubagentStop`, `PreCompact`, `PostCompact`, `SessionEnd`. Tool calls made inside a subagent carry its `agent_id`, so they animate that agent's mini Clawd instead of the main pet.

It needs `curl` on the PATH (built into macOS, Windows 10+ and Git Bash). When the pet isn't running the hook fails quietly and Claude Code carries on. The server only listens on `127.0.0.1`, keeps nothing but a few fields per event (never file contents), and refuses requests that come from a browser.

## Drive it from anything

The pet listens on `127.0.0.1:47821` (override with `CLAUDEBOT_PORT`, then reinstall the hooks):

```sh
curl --data celebrate http://127.0.0.1:47821/claudebot/play
curl --data think:cook http://127.0.0.1:47821/claudebot/play
```

Scenes: `idle`, `thinking`, `building`, `testing`, `typing`, `reading`, `searching`, `surfing`, `planning`, `delegating`, `alert`, `waiting`, `done`, `compacting`, `error`, `sleeping`. Reactions: `celebrate`, `hello`, `remind`, `dizzy`, `shrug`, `oops`, `notice`. Moves: `walk`, `zoomies`, `chase`, `dance`, `trip`, `sneeze`, `hop`, `wave`, `sit`, `stretch`, `yawn`, `look`. Thinking styles: `think:bubble`, `think:ponder`, `think:pontificate`, `think:cook`, `think:wizard`, `think:vibe`, `think:gears`, `think:hatch`, `think:spin`, `think:wander`, `think:garden`, `think:space`, `think:weather`, `think:doodle`, `think:forge`. And `agent` sends in a demo subagent. Handy for CI scripts, other agents, or a long `make` (`make && curl --data celebrate ...`).

While the pet has focus, keys `1`-`0` cycle through the main scenes, `a` brings in a subagent, `d` dances and `z` starts the zoomies.

## Desktop notes

Roaming means the app moves its own window, which not every desktop allows:

| Desktop | Roams the screen | Click-through |
| --- | --- | --- |
| Windows, macOS | yes | yes (toggled as the cursor crosses the pet) |
| Linux on X11 | yes | yes |
| Hyprland | yes, through Hyprland's IPC socket | yes |
| GNOME, KDE, sway on Wayland | no, it wanders inside its own window | yes |

- **Hyprland** ignores "always on top" from apps and blurs behind transparent windows. On launch the pet registers a session-only window rule through `hyprctl` (floating, pinned to every workspace, no border, blur, shadow, dimming or move animation, no focus-follows-mouse so it never steals focus by walking under the cursor). Nothing is written to the Hyprland config. To make it permanent anyway, add this to the Lua config:

  ```lua
  hl.window_rule({
    match = { class = "^claudebot$", title = "^Claude Bot$" },
    float = true, pin = true, border_size = 0, no_shadow = true, no_blur = true,
    no_dim = true, no_initial_focus = true, no_follow_mouse = true, no_anim = true,
    opacity = "1 1",
  })
  ```

  On older hyprlang configs: `windowrulev2 = float, class:^(claudebot)$, title:^(Claude Bot)$`, then the same line for `pin`, `noborder`, `noshadow`, `noblur`, `noanim`. The rules match the title because the voice panel ("Claude Bot Voice") shares the class and gets its own rule: floating, 460x720, above the pet.
- **GNOME** hides tray icons without the AppIndicator extension. Right-clicking the pet opens the same menu.

## Layout

```
src/              the pet: plain HTML, canvas and ES modules, no build step
  sprite.js       pixel painter, Clawd's body and eyes, glyphs
  props.js        every hat, tool and gadget
  font.js         5-pixel font for the status line
  verbs.js        Claude Code's spinner verbs and which act each one gets
  views.js        one drawing function per scene and thinking style
  brain.js        sessions, hook mapping, reminders, idle behaviour, particles
  crew.js         mini Clawds for subagents
  world.js        walking the window around the screen, gravity
  main.js         render loop, status line, input, Tauri wiring
  voice.js        WebSocket client for the voice engine, shared by the pet and the panel
  voice-pet.js    the pet's mic button, voice commands for the pet, its talking mouth
  panel.*         the voice panel: orb, captions, dock, fleet, conversation, memory, settings
  hud.*           the bottom-left voice strip: call orb and status
  voice-orb.js    the round mic and orb, shared by the pet and the HUD
  orb.js sky.js   the panel's dotted orb and pixel sky
src-tauri/src/
  main.rs         window, tray and right-click menu, settings
  hooks.rs        adds, updates and removes the Claude Code hooks
  server.rs       localhost HTTP endpoint
  world.rs        monitors, cursor, window moves (native or Hyprland IPC), click-through
  desktop.rs      window sizing and Hyprland rules
  voice.rs        starts, watches and stops the voice engine
voice/src/claudebot_voice/
  server.py       HTTP and WebSocket, local only, token checked
  session.py      the hub: calls, VAD segmenting, turns, approvals, fleet announcements, ducking
  audio.py        the sound card, WebRTC echo cancellation, the Jarvis voice chain, the mixer
  brain.py        the Claude session, system prompt, fleet, music and memory tools
  music.py        YouTube search and the yt-dlp to mpv pipe
  memory.py       long-term memory
  policy.py       which tool calls ask first
  tower.py        tower CLI wrapper and fleet watcher
  stt.py tts.py vad.py speech.py
```

Everything is drawn in "units" on a 56x30 stage; Clawd is 17x10 units, traced from the terminal mascot. Size just changes how many screen pixels a unit gets (4, 5 or 7). Mini Clawds and the status text are drawn with the same painter at a smaller unit.

Claude, Claude Code and Clawd belong to Anthropic. This is an unofficial fan project.
