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

**Around the screen.** It doesn't only live on the floor. It sits on the left, right and top edges and in the corners, turned the right way for each, walks around the screen's edge to get there, hides behind an edge with just its hands and the top of its head showing, and peeks out to look around. Now and then it goes exploring on its own and comes back. With two monitors it stays on the one it's on: it only changes monitors when I carry it over or tell it to go to the other screen.

**Physics.** Let go of it mid-throw and it keeps the speed: it bounces off screen edges and ceilings, soft-bounces off window sides, squashes when it lands and slides to a stop. It swings while I hold it, a poke shoves it, and it falls when the window it stands on goes away. Dropped near a window top it lands on it; near a window side or a screen edge it clings there (window tops and sides need Hyprland).

**Fetch.** "Play fetch" in the menu (or "let's play fetch") puts a ball at my feet. I grab it with the mouse and fling it anywhere on the screen; the pet runs for where it will come down, hops for it when it drops close by, carries it back to my cursor and drops it there for another throw. A catch in the air scores 3, off a wall 5, off the floor 1, and the best score is kept. "Stop playing", the menu again, or 40 seconds without a throw puts the ball away. The ball and the pet's thrown stones live on a see-through layer over the pet's monitor (`src/play.js`), so they fly across the whole screen; only the ball takes clicks, everything else goes through to whatever is underneath. The game stays on the pet's monitor and ends if the pet goes to the other one.

**Gestures and weather.** It skips stones across the screen, kicks a ball, juggles, flexes and blows a kiss, on its own now and then or when asked. Real local weather shows around it (rain, clouds and so on, from Open-Meteo for the location of my IP via ipwho.is, with wttr.in as a fallback, refreshed every 15 minutes).

**Notifications.** When a desktop notification arrives, it hops with a letter and shows "App: summary", and during a voice call the voice reads it out at the next lull. Media players stay quiet, so does any app that sends more than 3 in 2 minutes, and so do the apps I list in `quietApps` in its config.

**On its own** it strolls along the bottom of the screen, gets the zoomies, chases the cursor and sits down to look up at it, trips over, sneezes, dances, stretches, and notices when the cursor comes close. Its eyes follow the cursor around the screen. After 5 quiet minutes it falls asleep.

**Interactions:** drag it anywhere: it hangs from the cursor and swings with it, paddling faster the faster I move it, and dragged along the floor it crawls. Let go mid-air and it falls back to the floor, let go mid-swing and it flies. Click to poke it (four quick pokes make it dizzy), right-click for the menu. Only the pet itself catches the mouse; clicks on the empty parts of its window go straight through to whatever is underneath. The same menu sits in the system tray, and the tray tooltip shows the current status.

**Menu:** Talk to me, Play fetch, Voice panel, Voice on, React to Claude Code, Play animation, Thinking styles, Roam around the screen, Show status text, Notify when Claude is done, Show the weather, React to notifications, Size, Color (pink, Claude orange, mint, sky, lavender, ghost), Always on top, Start at login.

## Talk to it

Claude Bot is also my voice assistant: everything Jarvis (`~/voiceagent`) did now lives here. The mic sits in a small strip in the bottom-left corner of the right-hand screen, there whenever the voice can run, so it stays put while the pet wanders. One click goes live and one click hangs up; hovering it says what a click does, and it fills the moment it is pressed. While the voice is busy, the mic shows the call orb (waveform bars while either of us talks, a spinner while it thinks, a `!` when it needs my OK, grey when muted) and the strip says what it is doing in plain words ("Listening", "Checking the fleet", the sentence it is saying), or which song is playing. While a typed request is being answered outside a call, the mic stops the answer. Click the text to open the voice panel. Double-tap the pet for the panel too.

**Voice on and off.** Off means no listening and no speaking at all: the call ends, any reply in progress goes silent, and the mic stays closed until I turn it back on. Typed messages still get answers, in the transcript only, and music keeps playing. The switch survives restarts. Ways to flip it: "Voice on" in the right-click menu, the switch at the top of the panel, `V` while the pet or the panel has focus, `SUPER + ALT + V`, or `claudebot --voice` (`--voice-on`, `--voice-off`). Clicking the mic while the voice is off turns it on and goes live.

It is a full duplex call. I talk, it answers out loud, and talking over it cuts it off. Same persona and tools as Jarvis:

- **Fleet:** what every Claude Code agent in my tmux panes is doing (through tower), what they said, handing them work, spawning, interrupting and approving them. It speaks up when an agent finishes or needs me. It knows each agent's task, what it has done so far, what's next, what blocks it and what it needs (see the coordinator below), so "what is crowpane doing?" gets an answer without a tool call, and "approve it" or "tell it to use staging" reaches the agent we were just talking about. Messages can carry files: "send crowpane a screenshot of my screen", "send usepc that recording", or any file by path. With a tower that has `--attach`, tower keeps a copy and tells the agent what it got; with an older one the paths go in the message (images still arrive as images), and screenshots are taken with grim into `~/.local/share/claudebot/shared/`.
- **Desktop:** the pc plugin's tools (screenshots, windows, keyboard and mouse, processes, services, logs), plus a shell, files and the web.
- **Music:** "play some lo-fi", "skip", "pause", "louder". Tracks come from YouTube through yt-dlp and mpv and play through Claude Bot's own speaker stream, so the music fades down while either of us talks and the echo canceller never mistakes a song for me.
- **Memory:** it remembers facts, preferences, projects and people I mention, across conversations. It keeps them in `~/.local/share/claudebot/memory.json` and puts them in the session's context at the start of every conversation. It also logs every task it does for me (agents it started or messaged, commands that changed something, files it wrote, desktop input), with what I asked and what it answered, so a fresh session knows what is already done or under way. Tasks have their own cap of 40, separate from the 200 facts, and the newest go into the context. The panel's Memory tab lists both; "forget that" or the panel removes one.
- **Approvals:** risky tool calls ask out loud ("Okay to ...?"). "Yes", "no" or "always" answers, or the card in the panel. Anything negative ("please don't", "okay wait", "fine, no") is a no, a yes has to be a whole yes ("go back" isn't one), and a question back ("what does it delete?") holds the action and gets answered.
- **Quick commands:** these skip the model and happen as soon as the transcript is in, without stopping a task it's busy with: "hang up", "mute the mic", "talk slower" or "faster", "speak up", "longer answers", "pause", "resume", "next song", "louder" and "quieter" (the system volume), "what time is it", "what's the date", "repeat that", "go on" (the rest of a clipped answer), "approve it" or "deny it" (when the coordinator waits on exactly one thing), "voice off", the pet's moves ("dance", "make the pet fly", "peek from the left"), and, with a pc that has `pc record`, "start recording", "stop recording" and "record the screen for 30 seconds" (the video's path goes to the model, so "send that to crowpane" works next). A longer sentence that only starts the same way ("pause the deployment") still goes to the model.
- **The pet:** "fly", "dance", "hide", "peek from the left", "go to the top right corner", "come back", "throw", "kick the ball", "blow me a kiss", "go to the other screen" and the rest of its moves, places, gestures, reactions, scenes and thinking styles. The `pet_action` tool runs whatever the pet can do.

**Taking turns.** When I start talking over a reply, the reply pauses at once (about a third of a second after my first word) and waits to see what I said. If I said something, the old reply is dropped, marked "cut off" in the conversation, and my new words get the answer. If it was a cough, a murmur or its own voice coming back, it picks up the sentence it was on. "Hold on" or "wait" pauses the reply where it is and "go on" picks it up again; "okay", "yeah", "thanks" or "mm-hmm" while it talks or works just mean I'm listening, so the reply and the task carry on (unless it just asked me something: then "yes" is my answer). "Stop", "stop it", "okay stop" and "Jarvis, stop" silence it. It never starts talking while I talk or in the short moment after I stop. It waits a patient 1.1 seconds of silence before taking its turn, unless what I said already reads as a finished sentence, in which case it goes after half a second. If I trail off ("turn on the lights and") it waits longer, and if I add to a question it hasn't answered yet, the two become one request instead of two replies. Its own voice is never taken for mine: echo cancellation, an echo gate that learns how much of the speaker reaches the mic, and a check of each transcript against what it just said. My words show in the conversation and the HUD while I'm still saying them. Music ducks while either of us talks, and fleet news waits for a real lull.

**Speed.** From the end of my question to its first spoken word, measured with `voice/tests/latency.py`: median 1.76 seconds and about 1.4 at best, down from 2.6 (and from 5.6 before that). Most of the gain is in four places. It decides I've finished sooner when what I said is plainly complete: whisper starts on the last words after a third of a second of silence, and a finished sentence (or three words or more that don't trail off on "and" or "to") ends my turn after 0.5 to 0.75 seconds instead of the full 1.1. The reply is spoken as it streams instead of when the model is done, first clause first. Questions about my agents are answered from the coordinator's profiles without a tool call. And starting a fresh session or reconnecting happens between turns, not at the start of my next one. The transcriber runs in process and stays loaded, the brain is Haiku with thinking off, and Kokoro speaks a whole clause at a time, so speed never costs a choppy, unnatural delivery. Every request logs its stage timings (`latency: ... from end of speech to first word`), and quick commands log theirs too (`... to a local command`).

**What it knows without asking.** Each message carries a line of live context: the time, my focused window, the music, busy agents, the agent we last talked about (with its profile when I name one), and for questions about the fleet what every agent is doing and needs, whoever waits on me first. It answers from that instead of spending a tool call, and never reads it out. Whisper is told to expect "Jarvis", "Claude Bot", "tower" and my agents' names, which it used to mishear, and the HUD keeps what it heard on screen until the work starts.

It says one sentence and stops. It never narrates ("I'll check", "Let me look", "Checking"): a message from the model that opens like one is held until it ends, and if a tool call follows, it was a preamble and is dropped unheard. Everything else is spoken while the model is still writing it, clause by clause, so the first words play before the answer is finished. It only speaks once the work is done, and after a simple action I can see or hear for myself (music, a page, an app, a window, the pet) it says nothing unless something failed. A longer reply is clipped to its first sentence out loud and kept whole in the conversation; the Answers setting raises the limit to two or three. What it is doing shows in the HUD. Agent names go through speech to text, so they match loosely ("claudia bot" finds claudebot), but never so loosely that a message lands on the wrong agent: if two names fit about equally, it asks. An agent spawned into a folder Claude Code hasn't seen stops on the folder trust question; the voice says so and trusts the folder only when I say yes.

The panel has the orb and captions, the dock (call, mute, type), the music controls, and four tabs: Fleet, Conversation, Memory and Settings (model, voice, effect, volume, speed, microphone, speaker, access level, hands-free or push to talk, interrupting, answer length, announcements, pause length, music volume, ducking, memory). Settings save to `~/.config/claudebot/voice.json`; on first launch it copies my Jarvis settings from `~/.config/voiceagent/settings.json`. Keys in the panel: `C` call, `M` mute, `Space` held is push to talk, `Enter` type, `D` drawer, `Y` / `N` / `A` answer an approval, `Esc` interrupt or close.

From a hotkey or a script, a second `claudebot` hands the command to the running one:

```sh
claudebot --call         # start or end a call
claudebot --interrupt    # stop talking and cancel the answer
claudebot --mute
claudebot --panel
claudebot --say "what are my agents doing?"
claudebot --voice        # voice on or off
```

### The coordinator

A background loop in the voice engine looks after every Claude Code agent in my tmux panes, so they keep going while I'm busy elsewhere. It reads what tower reports and each agent's transcript and screen:

- **Permission prompts:** Claude (Sonnet) weighs the pending tool call against the agent's task. In scope and safe (reading, building, testing, editing inside the project, local git), it approves after a few seconds. Deleting outside the project, sudo, force pushes, deploying, spending, sending messages, touching secrets, or anything unclear waits for me: it says what the agent wants ("usepc wants to run rm -rf build"), puts a card with Approve and Deny in the panel, and "approve it" or "deny it" by voice answers it.
- **Questions:** an AskUserQuestion left unanswered for 40 seconds gets answered from the agent's task, picking the recommended option when nothing argues against it. Real decisions (direction, money, production) come to me instead.
- **"Want me to ...?":** a turn that ended on a yes-or-no question about the plainly next step gets "Yes, go ahead" 75 seconds later, at most three times per task. A choice between options comes to me. Turns that ended more than 20 minutes ago are left alone.
- **Stalls and errors:** a turn that died on an API error is retried, a full context gets `/compact` and then "continue", a turn with no progress for 10 minutes is looked at and interrupted with a hint when it hangs, and an agent that hit a usage limit is left alone.
- **Folder trust:** a new agent stuck on "Do you trust this folder?" in my home gets "Yes", picked one key at a time and only once the pointer is seen on it.
- **Each other:** two agents editing the same file within half an hour both hear about it, and every 10 minutes it looks over the whole fleet for one agent that needs another's result.

Everything it types is marked as coming from the coordinator, so an agent never takes it for my own words. It leaves alone the pane I'm working in (the active tmux pane, while I've used tmux in the last two minutes) and any agent I put hands-off ("leave usepc alone", or the button in the panel). Every action goes in a log with its reason (the panel's Fleet tab, and `~/.local/share/claudebot/coordinator.json`); routine approvals stay in the log, and only what needs me is spoken. Turn it off in the Fleet tab or by voice ("turn the coordinator off").

It also keeps a short profile of every agent, refreshed by Haiku as its transcript moves: the task, the model it runs on, what it has done, what's next, what blocks it and what it needs. The Fleet tab shows it under each agent, and the voice uses it for questions about the fleet.

### Which model does what

Opus thinks and plans, Sonnet implements and executes, Haiku is quick (`voice/src/claudebot_voice/models.py`).

- **Agents the voice starts** get a model picked from their task: Opus for planning, design, debugging, investigating, research and review ("figure out why the webhook returns 500", "review the settlement PR"); Sonnet for implementing and running things ("rename getUser and run the tests", "add a test for the refund endpoint", "check the logs"); `opusplan` for a build from scratch ("build a new dashboard app", "design and implement rate limiting"), which starts in plan mode on Opus and, once the plan is accepted (by me, or by the coordinator when it stays inside the task), carries it out on Sonnet. Naming a model wins ("use opus for this").
- **Claude Bot's own calls:** the voice on Haiku (speed; Sonnet and Opus are in the panel), agent profiles on Haiku, the coordinator's approvals, answers and stall checks on Sonnet, and its look over the whole fleet on Opus.

With claude-sudo armed in every session, its gate approves tool calls before Claude Code asks, so permission prompts are rare and the coordinator mostly answers questions, pushes past "want me to ...?" and recovers stalls.

### How the voice works

```
mic -> PortAudio at 48 kHz, 10 ms blocks
    -> WebRTC echo cancellation, noise suppression and gain (against everything the speaker plays)
    -> 16 kHz -> Silero VAD cuts utterances (early finish on a complete sentence)
    -> whisper.cpp in process, on voxtype's model (voxtype itself as the fallback)
    -> a Claude Code session through the Agent SDK (fleet, pc, shell, web, music and memory tools)
    -> sentences stream into Kokoro TTS -> the Jarvis EQ, compressor and room -> speaker
music: yt-dlp -> mpv (raw PCM on a pipe) -> mixed under the voice, ducked while anyone talks
```

The engine is the Python project in `voice/`. Claude Bot starts it with `uv run` when it launches, hands it a fresh token, restarts it if it dies, and stops it on quit. It listens on `127.0.0.1:47822` (`CLAUDEBOT_VOICE_PORT`) and only accepts Claude Bot's own windows with that token. Audio never goes through a window: WebKitGTK has no echo canceller, so the engine owns the mic and the speaker, and the windows only watch and send commands. The mic is only open during a call or push to talk.

Voice needs Linux with `uv`, `tower`, `mpv` and `yt-dlp` on the PATH, a whisper model from voxtype (`~/.local/share/voxtype/models/ggml-base.en.bin`; `voxtype setup` fetches it), and the models in `voice/models` (not in git):

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

Places: `hide`, `peek`, `peek:left` (or `right`, `top`, `bottom`), `edge:left` (and the others), `corner:top-left` (and the other three), `home`, `explore`. Physics: `fly`, `drop`, `throw`. Gestures: `stones`, `kick`, `juggle`, `flex`, `kiss`. Screens: `monitor:other`, `monitor:left`, `monitor:right`, `split`. Scenes: `idle`, `thinking`, `building`, `testing`, `typing`, `reading`, `searching`, `surfing`, `planning`, `delegating`, `alert`, `waiting`, `done`, `compacting`, `error`, `sleeping`. Reactions: `celebrate`, `hello`, `remind`, `dizzy`, `shrug`, `oops`, `notice`. Moves: `walk`, `zoomies`, `chase`, `dance`, `trip`, `sneeze`, `hop`, `wave`, `sit`, `stretch`, `yawn`, `look`. Thinking styles: `think:bubble`, `think:ponder`, `think:pontificate`, `think:cook`, `think:wizard`, `think:vibe`, `think:gears`, `think:hatch`, `think:spin`, `think:wander`, `think:garden`, `think:space`, `think:weather`, `think:doodle`, `think:forge`. And `agent` sends in a demo subagent. Handy for CI scripts, other agents, or a long `make` (`make && curl --data celebrate ...`).

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
  world.js        walking the window around the screen, edges and corners, gravity, surfaces
  physics.js      throws, bounces, slides and the swing while held
  weather.js      local weather around the pet
  main.js         render loop, status line, input, Tauri wiring
  voice.js        WebSocket client for the voice engine, shared by the pet and the panel
  voice-pet.js    voice commands for the pet, its talking mouth
  panel.*         the voice panel: orb, captions, dock, fleet, conversation, memory, settings
  hud.*           the bottom-left voice strip: the mic, the call orb and status
  voice-orb.js    the round mic and call orb drawn in the HUD
  game.js         fetch from the pet's side: chasing, catching, bringing the ball back
  play.*          the see-through game layer: the ball, its physics, my throws, the score, flying stones
  orb.js sky.js   the panel's dotted orb and pixel sky
src-tauri/src/
  main.rs         window, tray and right-click menu, settings
  hooks.rs        adds, updates and removes the Claude Code hooks
  server.rs       localhost HTTP endpoint
  world.rs        monitors, cursor, window moves (native or Hyprland IPC), click-through
  desktop.rs      window sizing and Hyprland rules
  voice.rs        starts, watches and stops the voice engine
  notifications.rs  desktop notifications from the session bus, for the pet to react to
voice/src/claudebot_voice/
  server.py       HTTP and WebSocket, local only, token checked
  session.py      the hub: calls, VAD segmenting, turns, approvals, fleet announcements, ducking
  audio.py        the sound card, WebRTC echo cancellation, the Jarvis voice chain, the mixer
  brain.py        the Claude session, system prompt, fleet, music and memory tools
  music.py        YouTube search and the yt-dlp to mpv pipe
  memory.py       long-term memory
  policy.py       which tool calls ask first
  tower.py        tower CLI wrapper and fleet watcher
  stt.py          whisper.cpp in process (voxtype as the fallback)
  tts.py vad.py speech.py
voice/tests/
  sim_turns.py    simulated conversations: barge-in, coughs, continuations, echo, grace, announcements
  latency.py      end of speech to first word, stage by stage, with the real models and Claude
```

Everything is drawn in "units" on a 56x30 stage; Clawd is 17x10 units, traced from the terminal mascot. Size just changes how many screen pixels a unit gets (4, 5 or 7). Mini Clawds and the status text are drawn with the same painter at a smaller unit.

Claude, Claude Code and Clawd belong to Anthropic. This is an unofficial fan project.
