// The voice HUD: a small fixed strip at the bottom left of the right-hand screen with the mic and
// what the voice is doing. The mic is there whenever the voice can run; next to it, the status
// shows while the voice is busy or music plays, and a hint while I hover the mic.
//
// Click the mic to talk (it turns the voice on first if it was off) and again to hang up; while a
// typed request is being answered, it stops the answer instead. Click the status for the voice panel.
import { Painter, spinnerFrame, CLAUDE } from './sprite.js';
import { drawText, textWidth, fit } from './font.js';
import { Voice } from './voice.js';
import { drawOrb } from './voice-orb.js';

const T = window.__TAURI__;
const win = T?.window.getCurrentWindow();
const invoke = T ? (cmd, args) => T.core.invoke(cmd, args) : null;

const N = 9; // orb diameter in cells; a cell is 2 CSS pixels, so the orb is 18 px across
const CSS = { cell: 2, font: 2, pad: 3, gap: 4 };
const TEXT = {
  listening: 'Listening', hearing: 'Hearing you', transcribing: 'Transcribing',
  thinking: 'Thinking', approval: 'Needs your OK', muted: 'Muted',
};

if (invoke) {
  const report = (msg) => invoke('log', { message: `hud: ${msg}` }).catch(() => {});
  addEventListener('error', (e) => report(`${e.message} at ${e.filename}:${e.lineno}`));
  addEventListener('unhandledrejection', (e) => report(e.reason?.stack ?? e.reason));
}

const canvas = document.getElementById('hud');
const ctx = canvas.getContext('2d');
const voice = new Voice();
const S = voice.state;
let caption = '';
let level = 0;
let last = 0;
let shownAt = 0;
let shown = null;
let hitKey = '';
let orbRight = 0;
let hovered = false; // the pointer is over the mic
let pressedAt = -1e9;
let hint = '';
let hintUntil = 0;

voice.on('caption', (m) => (caption = m.text));
voice.on('heard', () => (caption = ''));

const enabled = () => S.settings.enabled !== false;
const available = () => S.engine !== 'unavailable';
const busy = () => S.connected && enabled() && (S.call || S.phase !== 'idle');
const music = () => S.connected && (S.music.playing || S.music.paused);

// What the status pill says, or null for none (just the mic).
function label() {
  if (performance.now() < hintUntil) return { text: hint };
  if (!busy()) {
    if (hovered) return { text: !S.connected ? 'Voice is starting' : enabled() ? 'Click to talk' : 'Voice is off, click to talk' };
    if (music()) return { text: S.music.paused ? `Paused: ${S.music.title}` : S.music.title };
    return null;
  }
  if (S.phase === 'speaking') return { text: caption || 'Speaking' };
  if (S.phase === 'approval') return { text: S.approval?.title || TEXT.approval, color: '#FF8A8A' };
  // what it heard stays up until it starts working on it, so a mishearing shows without the panel
  if (S.phase === 'thinking') return { text: S.tool || S.heard || TEXT.thinking, spin: true };
  if (S.phase === 'transcribing') return { text: S.partial || TEXT.transcribing, spin: true };
  if (S.phase === 'hearing' && S.partial) return { text: S.partial }; // my words, as I say them
  return { text: TEXT[S.phase] || TEXT.listening };
}

function frame(now) {
  requestAnimationFrame(frame);
  const dt = Math.min(0.1, Math.max(0, (now - (last || now)) / 1000));
  last = now;
  const target = voice.loudness;
  level += (target - level) * (1 - Math.exp(-dt / (target > level ? 0.05 : 0.15)));

  const want = shown;
  const dpr = window.devicePixelRatio || 1;
  const W = Math.round(innerWidth * dpr), H = Math.round(innerHeight * dpr);
  if (canvas.width !== W || canvas.height !== H) {
    canvas.width = W;
    canvas.height = H;
    canvas.style.width = `${innerWidth}px`;
    canvas.style.height = `${innerHeight}px`;
    hitKey = '';
  }
  ctx.clearRect(0, 0, W, H);
  if (!want) return;

  const cell = Math.max(1, Math.round(CSS.cell * dpr));
  const oy = Math.round((H - N * cell) / 2);
  const ox = Math.round(CSS.pad * dpr);
  // the mic: the voice's own state while it's busy, else the button (greyed while the voice is off)
  const phase = busy() ? S.phase : S.connected && enabled() ? 'idle' : 'off';
  const fade = Math.min(1, (now - shownAt) / 160);
  const pressed = now - pressedAt < 160;
  drawOrb(ctx, ox, oy, cell, N, { phase, level, now, fade, color: '#D78787', hot: hovered || pressed, pressed });
  orbRight = (ox + N * cell) / dpr;

  // the status pill, in the pet's pixel font
  const l = label();
  const fpx = Math.max(1, Math.round(CSS.font * dpr));
  const px0 = ox + N * cell + Math.round(CSS.gap * dpr);
  if (!l) {
    hitRegion(Math.ceil(orbRight) + 2);
    return;
  }
  const room = Math.floor((W - px0) / fpx) - 8;
  const spin = l.spin ? 7 : 0;
  const text = fit((l.text || '').toUpperCase(), room - spin);
  const w = 5 + spin + textWidth(text);
  const h = 9;
  const p = new Painter(ctx, fpx, px0, Math.round((H - h * fpx) / 2));
  p.rect(1, 0, w - 2, h, '#1C1B1A', 0.9 * fade);
  p.rect(0, 1, w, h - 2, '#1C1B1A', 0.9 * fade);
  if (spin) p.bitmap(spinnerFrame(Math.floor(now / 110)), 3, 2, CLAUDE);
  drawText(p, text, 3 + spin, 2, l.color || '#F4EFE6', fade);

  hitRegion(Math.ceil((px0 + w * fpx) / dpr) + 2);
}

// Only the mic and the pill take clicks; the rest of the strip lets them through.
function hitRegion(width) {
  const key = `${width}`;
  if (invoke && key !== hitKey) {
    hitKey = key;
    invoke('set_hit_region', { x: 0, y: 0, width, height: innerHeight }).catch(() => {});
  }
}

// A hidden window gets no animation frames, so showing and hiding runs on a plain timer.
function visibility() {
  const want = available();
  if (want === shown) return;
  shown = want;
  if (want) shownAt = performance.now();
  if (win) {
    // each time it appears, back to the bottom-left corner of the right-hand screen
    // (Hyprland maps the window a moment after show() returns, so place it again shortly after)
    const place = () => invoke?.('place_hud').catch(() => {});
    (want ? win.show().then(() => [0, 150, 500, 1200].forEach((ms) => setTimeout(place, ms))) : win.hide())
      .catch((e) => invoke?.('log', { message: `hud: ${want ? 'show' : 'hide'} failed: ${e}` }));
  }
}
setInterval(visibility, 150);

// The mic: go live (turning the voice on first if it was off), hang up during a call, and while a
// typed request is being answered outside a call, stop it.
function mic() {
  if (!S.connected) {
    hint = 'Voice is starting';
    hintUntil = performance.now() + 2400;
  } else if (!enabled()) {
    voice.send({ type: 'voice', on: true });
    voice.send({ type: 'call', action: 'start' });
  } else if (S.call) {
    voice.send({ type: 'call', action: 'end' });
  } else if (busy()) {
    voice.send({ type: 'interrupt' });
  } else {
    voice.send({ type: 'call', action: 'start' });
  }
}

const onMic = (e) => e.offsetX <= orbRight + 2;

canvas.addEventListener('pointermove', (e) => (hovered = onMic(e)));
canvas.addEventListener('pointerleave', () => (hovered = false));
canvas.addEventListener('pointerdown', (e) => {
  if (e.button === 0 && onMic(e)) pressedAt = performance.now();
});
canvas.addEventListener('pointerup', (e) => {
  if (e.button !== 0) return;
  if (onMic(e)) mic();
  else invoke?.('toggle_panel').catch(() => {});
});

requestAnimationFrame(frame);
voice.start();
