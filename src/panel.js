// The voice panel: the orb, captions, approvals, and a drawer with the fleet, the conversation,
// memory and settings. The engine owns the mic and the speaker; this window only shows and asks.
import { Orb } from './orb.js';
import { startSky } from './sky.js';
import { Voice } from './voice.js';

const T = window.__TAURI__;
const $ = (sel) => document.querySelector(sel);
const body = document.body;
const voice = new Voice();
const S = voice.state;
const ui = {
  heard: $('#heard'), caption: $('#caption'), activity: $('#activity'), timer: $('#timer'), title: $('#title'),
  engine: $('#engine'), mic: $('#btn-mic'), type: $('#btn-type'), call: $('#btn-call'), callLabel: $('#call-label'),
  drawerBtn: $('#btn-drawer'), drawer: $('#drawer'), composer: $('#composer'), input: $('#composer-input'),
  approval: $('#approval'), toasts: $('#toasts'), music: $('#music'), musicTitle: $('#music-title'),
  fleet: $('#tab-fleet'), log: $('#tab-log'), memory: $('#tab-memory'), settings: $('#tab-settings'),
  fleetCount: $('#fleet-count'), memoryCount: $('#memory-count'), voiceBtn: $('#btn-voice'), voiceLabel: $('#voice-label'),
};
const voiceOn = () => S.settings.enabled !== false;
const toggleVoice = () => send({ type: 'voice', action: 'toggle' });
const view = { openAgent: null, tab: 'fleet' };

const LABELS = {
  idle: '', listening: 'listening', hearing: 'hearing you', transcribing: 'transcribing',
  thinking: 'thinking', speaking: 'speaking', approval: 'needs your ok', muted: 'muted',
};
const send = (msg) => voice.send(msg);

addEventListener('error', (e) => send({ type: 'client_error', message: `panel: ${e.message} at ${e.filename}:${e.lineno}` }));

// ---------------------------------------------------------------- engine events

voice.on('engine', () => render());
voice.on('connected', () => render());
voice.on('hello', () => {
  document.title = S.settings.name || 'Jarvis';
  ui.log.replaceChildren();
  S.history.forEach(addEntry);
  renderFleet(); renderSettings(); renderApproval(); renderMemory(); renderMusic(); render();
  if (S.audioError) setCaption(`No sound device: ${S.audioError}`);
});
voice.on('phase', () => render());
voice.on('call', (m) => {
  if (m.active && captionText === 'Standing by.') setCaption('');
  render();
});
voice.on('muted', () => render());
voice.on('caption', (m) => setCaption(m.text));
voice.on('heard', (m) => {
  ui.heard.textContent = `“${m.text}”`;
  setCaption('');
  livePartial(null);
});
// My words as I say them: a provisional line in the conversation, replaced by the final one.
voice.on('partial', (m) => {
  if (m.text) ui.heard.textContent = `“${m.text}”`;
  livePartial(m.text || null);
});
// A reply I talked over: its lines stay, marked as cut off.
voice.on('cut', (m) => {
  for (const el of ui.log.querySelectorAll(`.entry[data-turn="${m.turn}"][data-role="assistant"]`)) el.classList.add('cut');
});
voice.on('tool', () => render());
voice.on('log', (m) => {
  addEntry(m.entry);
  if (m.entry.role === 'system') setCaption(m.entry.text);
});
voice.on('history', () => ui.log.replaceChildren());
voice.on('fleet', () => renderFleet());
voice.on('coordinator', () => renderFleet());
voice.on('profiles', () => renderFleet());
voice.on('toast', (m) => toast(m.text, m.kind));
voice.on('approval', () => renderApproval());
voice.on('settings', () => {
  document.title = S.settings.name || 'Jarvis';
  renderSettings();
  render();
});
voice.on('memory', () => renderMemory());
voice.on('music', () => renderMusic());

// ---------------------------------------------------------------- rendering

let captionText = '';

function setCaption(text) {
  if (text === captionText) return;
  captionText = text;
  ui.caption.textContent = text;
  ui.caption.classList.remove('swap');
  void ui.caption.offsetWidth;
  ui.caption.classList.add('swap');
}

function render() {
  body.dataset.phase = S.phase;
  body.classList.toggle('connected', S.connected);
  body.classList.toggle('in-call', S.call);
  body.classList.toggle('muted', S.muted && S.call);
  body.classList.toggle('voice-off', S.connected && !voiceOn());
  ui.voiceBtn.setAttribute('aria-pressed', String(voiceOn()));
  ui.voiceLabel.textContent = voiceOn() ? 'Voice on' : 'Voice off';
  ui.title.textContent = S.settings.name || 'Jarvis';
  ui.engine.textContent = S.connected ? S.host : S.engine === 'unavailable' ? 'voice unavailable' : 'starting';
  ui.callLabel.textContent = S.call ? 'End' : 'Call';
  ui.mic.setAttribute('aria-label', S.muted ? 'Unmute' : 'Mute');
  tickTimer();
  let label = LABELS[S.phase] || S.phase;
  if (S.tool && (S.phase === 'thinking' || S.phase === 'speaking')) label += ` · ${S.tool}`;
  if (!S.connected) label = S.engine === 'unavailable' ? S.error : 'voice engine starting';
  else if (!voiceOn()) label = 'voice off · not listening, not speaking · press V';
  else if (S.phase === 'idle') label = S.call ? '' : 'press C to call · hold space to talk';
  ui.activity.textContent = label;
  if (S.phase === 'idle' && !S.call && !captionText) setCaption('Standing by.');
}

function fmt(sec) {
  sec = Math.max(0, Math.floor(sec));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${m}:${String(s).padStart(2, '0')}`;
}

function tickTimer() {
  ui.timer.textContent = !S.connected ? 'offline' : S.call ? fmt(Date.now() / 1000 - S.started) : 'ready';
}
setInterval(tickTimer, 500);

function h(tag, props = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k in el && typeof v !== 'string') el[k] = v;
    else el.setAttribute(k, v);
  }
  el.append(...kids.flat().filter((x) => x !== null && x !== undefined && x !== false));
  return el;
}

function ago(ts) {
  if (!ts) return '';
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.round(s / 60)}m`;
  if (s < 86400) return `${Math.round(s / 3600)}h`;
  return `${Math.round(s / 86400)}d`;
}

const RANK = { waiting: 0, working: 1, done: 2, idle: 3 };
const STATE_TEXT = { working: 'working', waiting: 'waiting on you', done: 'done', idle: 'idle' };

// The coordinator: on or off, what it's waiting on me for (with my answer one click away), and
// what it did lately. It sits above the agents it looks after.
function coordinatorView() {
  const C = S.coordinator;
  const resolve = (pane, decision) => (e) => { e.stopPropagation(); send({ type: 'coordinator', action: 'resolve', pane, decision }); };
  const prompt = (kind) => kind === 'permission' || kind === 'question' || kind === 'waiting';
  return h('section', { class: 'coord' },
    h('div', { class: 'coord-head' },
      h('span', { class: 'coord-title' }, 'Coordinator'),
      h('span', { class: 'coord-sub' }, C.enabled ? 'approves, answers and unsticks your agents' : 'off'),
      h('button', { class: 'coord-toggle', 'aria-pressed': String(!!C.enabled),
        onclick: () => send({ type: 'coordinator', action: 'toggle' }) }, C.enabled ? 'On' : 'Off')),
    ...C.pending.map((p) => h('div', { class: 'coord-card' },
      h('p', { class: 'coord-text' }, p.text),
      p.detail ? h('pre', { class: 'coord-detail' }, p.detail) : null,
      h('div', { class: 'coord-actions' },
        h('button', { class: 'primary', onclick: resolve(p.pane, 'approve') }, prompt(p.kind) ? 'Approve' : 'Go ahead'),
        h('button', { onclick: resolve(p.pane, 'deny') }, prompt(p.kind) ? 'Deny' : 'Dismiss')))),
    C.log.length ? h('details', { class: 'coord-log', open: !!view.logOpen, ontoggle: (e) => { view.logOpen = e.target.open; } },
      h('summary', {}, `Recent actions (${C.log.length})`),
      ...C.log.slice(-12).reverse().map((e) => h('p', {},
        h('span', { class: 'coord-when' }, ago(e.ts)), ' ', h('b', {}, e.agent), ` ${e.action}: ${e.reason}`))) : null);
}

function renderFleet() {
  const agents = [...S.fleet].sort((a, b) => (RANK[a.state] ?? 9) - (RANK[b.state] ?? 9));
  ui.fleetCount.textContent = agents.length || '';
  const waiting = agents.some((a) => a.state === 'waiting'), done = agents.some((a) => a.state === 'done');
  if (waiting || done) ui.drawerBtn.dataset.alert = waiting ? 'waiting' : 'done';
  else delete ui.drawerBtn.dataset.alert;
  if (!agents.length) {
    ui.fleet.replaceChildren(coordinatorView(), h('p', { class: 'empty' }, 'No agents in tmux right now.'));
    return;
  }
  const profiles = new Map(S.profiles.map((p) => [p.pane, p]));
  const skip = new Set((S.coordinator.skip || []).map((x) => x.toLowerCase()));
  ui.fleet.replaceChildren(coordinatorView(), ...agents.map((a) => {
    const p = profiles.get(a.pane);
    const off = skip.has(a.name.toLowerCase());
    const hands = (e) => { e.stopPropagation(); send({ type: 'coordinator', action: off ? 'hands_on' : 'hands_off', agent: a.name }); };
    const busy = a.state === 'working' || a.state === 'waiting';
    const since = ago(a.since);
    const ask = (text) => (e) => { e.stopPropagation(); send({ type: 'text', text }); };
    return h('article', {
      class: `agent${view.openAgent === a.pane ? ' open' : ''}`, 'data-state': a.state,
      onclick: () => { view.openAgent = view.openAgent === a.pane ? null : a.pane; renderFleet(); },
    },
      h('div', { class: 'agent-head' },
        h('span', { class: 'state-dot' }),
        h('span', { class: 'agent-name' }, a.name),
        h('span', { class: 'agent-state' }, STATE_TEXT[a.state] || a.state, since ? ` · ${since}` : ''),
        h('span', { class: 'agent-where', title: a.where }, a.cwd)),
      (busy && a.activity) || a.prompt
        ? h('p', { class: `agent-doing${busy && a.activity ? ' mono' : ''}` }, busy && a.activity ? a.activity : a.prompt)
        : null,
      p?.summary ? h('p', { class: 'agent-note' }, p.model ? `${p.model} · ${p.summary}` : p.summary) : null,
      p?.blocked_on ? h('p', { class: 'agent-note blocked' }, `Blocked on: ${p.blocked_on}`) : null,
      p?.needs ? h('p', { class: 'agent-note needs' }, `Needs: ${p.needs}`) : null,
      p?.next && view.openAgent === a.pane ? h('p', { class: 'agent-note' }, `Next: ${p.next}`) : null,
      h('div', { class: 'agent-actions' },
        h('button', { onclick: ask(`What is ${a.name} doing right now?`) }, 'What’s it doing?'),
        h('button', { onclick: ask(`What did ${a.name} say in its last reply?`) }, 'Last reply'),
        a.state === 'waiting' ? h('button', { onclick: ask(`What is ${a.name} waiting on me for?`) }, 'What does it need?') : null,
        h('button', { onclick: (e) => { e.stopPropagation(); send({ type: 'agent', action: 'show', pane: a.pane }); } }, 'Show pane'),
        h('button', { onclick: hands, title: 'Whether the coordinator may act on this agent' },
          off ? 'Coordinator: hands off' : 'Coordinator: on')));
  }));
}

const WHO = { user: 'You', assistant: () => S.settings.name || 'Jarvis', tool: 'tool', system: 'system', event: 'fleet', approval: 'approval' };

let partialEl = null;
function livePartial(text) {
  if (!text) {
    partialEl?.remove();
    partialEl = null;
    return;
  }
  const pinned = ui.log.scrollHeight - ui.log.scrollTop - ui.log.clientHeight < 40;
  if (!partialEl) {
    partialEl = h('div', { class: 'entry partial', 'data-role': 'user' }, h('span', { class: 'who' }, 'You'), h('p', {}), h('time', {}, 'now'));
  }
  partialEl.querySelector('p').textContent = text;
  ui.log.append(partialEl); // keep it last
  if (pinned) ui.log.scrollTop = ui.log.scrollHeight;
}

function addEntry(e) {
  const pinned = ui.log.scrollHeight - ui.log.scrollTop - ui.log.clientHeight < 40;
  const who = typeof WHO[e.role] === 'function' ? WHO[e.role]() : WHO[e.role] || e.role;
  const time = new Date(e.ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const attrs = { class: `entry${e.cut ? ' cut' : ''}`, 'data-role': e.role };
  if (e.turn !== undefined) attrs['data-turn'] = String(e.turn);
  ui.log.append(h('div', attrs, h('span', { class: 'who' }, who), h('p', {}, e.text), h('time', {}, time)));
  if (partialEl) ui.log.append(partialEl);
  while (ui.log.childElementCount > 300) ui.log.firstElementChild.remove();
  if (pinned) ui.log.scrollTop = ui.log.scrollHeight;
}

function renderApproval() {
  const a = S.approval;
  ui.approval.hidden = !a;
  if (!a) return;
  $('#approval-tool').textContent = a.tool.replace(/^mcp__/, '').replace('__', ' · ');
  $('#approval-title').textContent = a.title;
  $('#approval-detail').textContent = a.detail && a.detail !== a.title ? a.detail : '';
}

function decide(decision) {
  if (S.approval) send({ type: 'approve', id: S.approval.id, decision });
}

const KIND_TEXT = { fact: 'fact', preference: 'likes', project: 'project', person: 'person' };

function renderMemory() {
  const items = [...S.memory].reverse();
  ui.memoryCount.textContent = items.length || '';
  if (!items.length) {
    ui.memory.replaceChildren(h('p', { class: 'empty' },
      S.settings.memory === false ? 'Memory is off in settings.' : 'Nothing remembered yet. Tell me about yourself, or say "remember that" and the rest.'));
    return;
  }
  ui.memory.replaceChildren(
    ...items.map((m) => h('div', { class: 'memory-item', 'data-kind': m.kind },
      h('span', { class: 'who' }, KIND_TEXT[m.kind] || m.kind),
      h('p', {}, m.text),
      h('button', { class: 'forget', 'aria-label': `Forget: ${m.text}`, title: 'Forget',
        onclick: () => send({ type: 'memory', action: 'forget', id: m.id }) },
        h('span', { 'aria-hidden': 'true' }, '×')))),
    h('div', { class: 'memory-foot' },
      h('button', { onclick: (e) => {
        // two taps, no dialog: the webview's confirm() is not reliable across platforms
        if (e.target.dataset.armed) send({ type: 'memory', action: 'clear' });
        else { e.target.dataset.armed = '1'; e.target.textContent = 'Tap again to forget everything'; }
      } }, 'Forget everything')),
  );
}

function renderMusic() {
  const m = S.music;
  const on = m.playing || m.paused;
  ui.music.hidden = !on;
  body.classList.toggle('has-music', on);
  if (!on) return;
  ui.musicTitle.textContent = m.title || m.query;
  ui.musicTitle.title = m.title;
  ui.music.classList.toggle('paused', m.paused);
  $('#music-toggle').setAttribute('aria-label', m.paused ? 'Play' : 'Pause');
}

const VOICE_KIND = { af: 'American female', am: 'American male', bf: 'British female', bm: 'British male' };
const MODEL_TEXT = { haiku: 'Haiku, fastest', sonnet: 'Sonnet, balanced', opus: 'Opus, smartest' };

function renderSettings() {
  const s = S.settings;
  if (!s.model) return;
  const patch = (p) => send({ type: 'settings', patch: p });
  const row = (label, ...control) => h('div', { class: 'settings-row' }, h('span', { class: 'label' }, label), h('div', { class: 'control' }, ...control));
  const select = (key, options, text) => h('select', { 'aria-label': key, onchange: (e) => patch({ [key]: e.target.value }) },
    options.map((o) => h('option', { value: o, selected: o === s[key] }, text(o))));
  const segmented = (key, options) => h('div', { class: 'segmented', role: 'group' },
    options.map(([value, text]) => h('button', { 'aria-pressed': String(s[key] === value), onclick: () => patch({ [key]: value }) }, text)));
  const toggle = (key) => h('label', { class: 'switch' },
    h('input', { type: 'checkbox', checked: !!s[key], 'aria-label': key, onchange: (e) => patch({ [key]: e.target.checked }) }), h('span'));
  const range = (key, min, max, step, show) => {
    const value = h('span', { class: 'range-value' }, show(s[key]));
    return [h('input', { type: 'range', min: String(min), max: String(max), step: String(step), value: String(s[key]), 'aria-label': key,
      oninput: (e) => (value.textContent = show(Number(e.target.value))),
      onchange: (e) => patch({ [key]: Number(e.target.value) }) }), value];
  };
  const pct = (v) => `${Math.round(v * 100)}%`;
  const device = (key, list) => select(key, ['', ...list.filter((d) => d !== s[key]), ...(s[key] ? [s[key]] : [])],
    (d) => d || 'System default');

  ui.settings.replaceChildren(
    row('Voice', toggle('enabled'), h('span', { class: 'label' }, 'Listen and speak. Off stops both until I turn it back on')),
    row('Name', h('input', { class: 'text-input', value: s.name, maxlength: '24', 'aria-label': 'Name',
      onchange: (e) => patch({ name: e.target.value }) })),
    row('Model', select('model', S.models, (m) => MODEL_TEXT[m] || m)),
    row('Voice',
      select('voice', S.voices, (v) => (v === 'jarvis' ? 'Jarvis · British male blend'
        : `${v.slice(3).replace(/^./, (c) => c.toUpperCase())} · ${VOICE_KIND[v.slice(0, 2)] || v.slice(0, 2)}`)),
      h('button', { onclick: () => send({ type: 'preview' }) }, 'Test')),
    row('Effect', segmented('effect', [['jarvis', 'Jarvis'], ['clean', 'Clean']])),
    row('Volume', ...range('volume', 0.1, 1, 0.05, pct)),
    row('Speed', ...range('speed', 0.8, 1.3, 0.05, (v) => `${Number(v).toFixed(2)}x`)),
    row('Microphone', device('input_device', S.devices.input)),
    row('Speaker', device('output_device', S.devices.output)),
    row('Access', segmented('autonomy', [['full', 'Full'], ['trust', 'Trusted'], ['ask', 'Ask first']]),
      h('small', {}, {
        full: 'Does everything without asking. Only wiping disks, deleting home or powering off asks.',
        trust: 'Destructive shell commands ask. Clicks, typing and agent messages just happen.',
        ask: 'Reading, looking and research run on their own. Clicks, typing, edits and agent messages ask first.',
      }[s.autonomy] || '')),
    row('Listening', segmented('input', [['handsfree', 'Hands-free'], ['ptt', 'Push to talk']]),
      h('small', {}, s.input === 'ptt' ? 'Only while Space is held.' : 'Voice detection ends my turn after a pause. Space still works.')),
    row('Interrupt', toggle('barge_in'), h('span', { class: 'label' }, 'Talking over the voice cuts it off')),
    row('Answers', segmented('sentences', [[1, 'One sentence'], [2, 'Two'], [3, 'Three']]),
      h('small', {}, 'The most it says out loud. The full reply stays in the conversation.')),
    row('Announce', toggle('announce'), h('span', { class: 'label' }, 'Speak up when an agent finishes or needs me')),
    row('Pause length', ...range('endpoint_ms', 400, 1600, 100, (v) => `${v}ms`)),
    row('Music', ...range('music_volume', 0, 1, 0.05, pct)),
    row('Ducking', ...range('duck', 0, 1, 0.05, pct),
      h('small', {}, 'Music level while either of us talks.')),
    row('Memory', toggle('memory'), h('span', { class: 'label' }, 'Remember what I tell you, and the tasks it did, across conversations')),
    row('Conversation', h('button', { onclick: () => send({ type: 'reset' }) }, 'Start fresh')),
  );
}

function toast(text, kind = 'info') {
  const el = h('div', { class: 'toast', 'data-kind': kind }, text);
  ui.toasts.append(el);
  while (ui.toasts.childElementCount > 4) ui.toasts.firstElementChild.remove();
  setTimeout(() => { el.classList.add('out'); setTimeout(() => el.remove(), 320); }, 5000);
}

// ---------------------------------------------------------------- controls

function toggleMute() {
  if (!S.call) return voice.toggleCall();
  send({ type: 'mute', value: !S.muted });
}

function openComposer(open = ui.composer.hidden) {
  ui.composer.hidden = !open;
  body.classList.toggle('typing', open);
  if (open) {
    setDrawer(false);
    ui.input.focus();
  } else ui.input.blur();
}

function setDrawer(open = !body.classList.contains('drawer-open')) {
  body.classList.toggle('drawer-open', open);
  ui.drawer.setAttribute('aria-hidden', String(!open));
  ui.drawerBtn.setAttribute('aria-expanded', String(open));
  if (open) {
    ui.composer.hidden = true;
    body.classList.remove('typing');
    if (view.tab === 'log') ui.log.scrollTop = ui.log.scrollHeight;
  }
}

function setTab(tab) {
  view.tab = tab;
  for (const b of ui.drawer.querySelectorAll('[role="tab"]')) b.setAttribute('aria-selected', String(b.dataset.tab === tab));
  for (const p of ['fleet', 'log', 'memory', 'settings']) $(`#tab-${p}`).hidden = p !== tab;
  if (tab === 'log') ui.log.scrollTop = ui.log.scrollHeight;
}

const closePanel = () => T?.window.getCurrentWindow().close();

// With the voice off, the call button turns it back on and goes live.
function callButton() {
  if (!voiceOn()) {
    send({ type: 'voice', on: true });
    send({ type: 'call', action: 'start' });
  } else voice.toggleCall();
}

ui.call.addEventListener('click', callButton);
ui.voiceBtn.addEventListener('click', toggleVoice);
ui.mic.addEventListener('click', toggleMute);
ui.type.addEventListener('click', () => openComposer());
ui.drawerBtn.addEventListener('click', () => setDrawer());
$('#btn-close').addEventListener('click', closePanel);
ui.drawer.querySelectorAll('[role="tab"]').forEach((b) => b.addEventListener('click', () => setTab(b.dataset.tab)));
ui.approval.querySelectorAll('[data-decision]').forEach((b) => b.addEventListener('click', () => decide(b.dataset.decision)));
ui.music.querySelectorAll('[data-music]').forEach((b) => b.addEventListener('click', () => send({ type: 'music', action: b.dataset.music })));

ui.composer.addEventListener('submit', (e) => {
  e.preventDefault();
  const text = ui.input.value.trim();
  if (!text) return;
  send({ type: 'text', text });
  ui.input.value = '';
});

let pttHeld = false;
function pttDown() {
  if (pttHeld || !S.connected) return;
  pttHeld = true;
  if (S.muted) send({ type: 'mute', value: false });
  send({ type: 'ptt', down: true });
}
function pttUp() {
  if (!pttHeld) return;
  pttHeld = false;
  setTimeout(() => send({ type: 'ptt', down: false }), 120); // the last syllable is still in flight
}

addEventListener('keydown', (e) => {
  if (e.target.closest('input, select, textarea')) {
    if (e.key === 'Escape') { openComposer(false); e.target.blur(); }
    return;
  }
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  if (e.code === 'Space') {
    e.preventDefault();
    if (!e.repeat) pttDown();
    return;
  }
  const key = e.key.toLowerCase();
  if (S.approval && (key === 'y' || key === 'n' || key === 'a')) {
    decide({ y: 'allow', n: 'deny', a: 'always' }[key]);
  } else if (key === 'escape') {
    if (body.classList.contains('drawer-open')) setDrawer(false);
    else if (S.phase === 'speaking' || S.phase === 'thinking') send({ type: 'interrupt' });
    else closePanel();
  } else if (key === 'c') callButton();
  else if (key === 'v') toggleVoice();
  else if (key === 'm') toggleMute();
  else if (key === 'd') setDrawer();
  else if (key === 'enter' || key === '/') { e.preventDefault(); openComposer(true); }
});
addEventListener('keyup', (e) => { if (e.code === 'Space') pttUp(); });
addEventListener('blur', pttUp);

// ---------------------------------------------------------------- go

startSky($('#sky'));
const orb = new Orb($('#orb'));
let last = performance.now();
function frame(now) {
  const dt = Math.min(0.05, (now - last) / 1000);
  last = now;
  orb.frame(dt, S.connected ? S.phase : 'muted', voice.loudness);
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);
render();
voice.start();
