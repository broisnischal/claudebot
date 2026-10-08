// The voice HUD: a small fixed strip at the bottom left of the screen with the call orb and what
// the voice is doing. It shows while the voice is busy or music plays and hides otherwise. Click
// the orb to hang up, the text to open the voice panel.
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

voice.on('caption', (m) => (caption = m.text));
voice.on('heard', () => (caption = ''));

const enabled = () => S.settings.enabled !== false;
const busy = () => S.connected && enabled() && (S.call || S.phase !== 'idle');
const music = () => S.connected && (S.music.playing || S.music.paused);

function label() {
  if (!busy()) return { text: S.music.paused ? `Paused: ${S.music.title}` : S.music.title };
  if (S.phase === 'speaking') return { text: caption || 'Speaking' };
  if (S.phase === 'approval') return { text: S.approval?.title || TEXT.approval, color: '#FF8A8A' };
  if (S.phase === 'thinking') return { text: S.tool || TEXT.thinking, spin: true };
  if (S.phase === 'transcribing') return { text: TEXT.transcribing, spin: true };
  return { text: TEXT[S.phase] || TEXT.listening };
}

function frame(now) {
  requestAnimationFrame(frame);
  const dt = Math.min(0.1, Math.max(0, (now - (last || now)) / 1000));
  last = now;
  const target = voice.loudness;
  level += (target - level) * (1 - Math.exp(-dt / (target > level ? 0.05 : 0.15)));

  const want = busy() || music();
  if (want !== shown) {
    shown = want;
    if (want) shownAt = now;
    if (win) (want ? win.show() : win.hide()).catch(() => {});
  }
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
  const phase = busy() ? S.phase : 'music';
  const fade = Math.min(1, (now - shownAt) / 160);
  drawOrb(ctx, ox, oy, cell, N, { phase, level, now, fade, color: '#D78787' });
  orbRight = (ox + N * cell) / dpr;

  // the status pill, in the pet's pixel font
  const fpx = Math.max(1, Math.round(CSS.font * dpr));
  const px0 = ox + N * cell + Math.round(CSS.gap * dpr);
  const room = Math.floor((W - px0) / fpx) - 8;
  const l = label();
  const spin = l.spin ? 7 : 0;
  const text = fit((l.text || '').toUpperCase(), room - spin);
  const w = 5 + spin + textWidth(text);
  const h = 9;
  const p = new Painter(ctx, fpx, px0, Math.round((H - h * fpx) / 2));
  p.rect(1, 0, w - 2, h, '#1C1B1A', 0.9 * fade);
  p.rect(0, 1, w, h - 2, '#1C1B1A', 0.9 * fade);
  if (spin) p.bitmap(spinnerFrame(Math.floor(now / 110)), 3, 2, CLAUDE);
  drawText(p, text, 3 + spin, 2, l.color || '#F4EFE6', fade);

  // only the orb and the pill take clicks; the rest of the strip lets them through
  const r = { x: 0, y: 0, width: Math.ceil((px0 + w * fpx) / dpr) + 2, height: innerHeight };
  const key = `${r.width}`;
  if (invoke && key !== hitKey) {
    hitKey = key;
    invoke('set_hit_region', r).catch(() => {});
  }
}

canvas.addEventListener('pointerup', (e) => {
  if (e.button !== 0) return;
  if (e.offsetX <= orbRight + 2) {
    if (S.call) voice.send({ type: 'call', action: 'end' });
    else voice.send({ type: 'interrupt' });
  } else {
    invoke?.('toggle_panel').catch(() => {});
  }
});

requestAnimationFrame(frame);
voice.start();
