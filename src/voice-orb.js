// The voice's little round mark in the bottom-left HUD, drawn in half-unit pixels: the mic button
// while the voice is idle, and the call orb while it's busy. One function so both look the same.
import { CLAUDE, spinnerFrame } from './sprite.js';

const MIC = ['.###.', '.###.', '.###.', '#...#', '.###.', '..#..', '.###.'];
const BANG = ['#', '#', '#', '.', '#'];
const NOTE = ['..##', '..#.', '..#.', '###.', '##..'];

const RING = {
  idle: '#D9D4CB', listening: '#D9D4CB', hearing: '#7FD6FF', transcribing: CLAUDE, thinking: CLAUDE,
  approval: '#FF6B6B', muted: '#6E6A64', off: '#6E6A64', hangup: '#FF6B6B', music: '#B49BDB',
};

// o: { phase, level (0..1), now, fade (0..1), hot (hovered), color (ring while speaking) }
// phase: idle (mic button), off (voice turned off), hangup (button during a call), music, or a call
// phase from the engine (listening, hearing, transcribing, thinking, speaking, approval, muted).
export function drawOrb(ctx, ox, oy, cell, n, o) {
  const { phase, level = 0, now = 0, fade = 1, hot = false } = o;
  const px = (cx, cy, w, h, color, alpha = 1) => {
    ctx.globalAlpha = alpha;
    ctx.fillStyle = color;
    ctx.fillRect(ox + cx * cell, oy + cy * cell, w * cell, h * cell);
  };
  const glyph = (rows, gx, gy, color) => {
    rows.forEach((row, dy) => {
      for (let dx = 0; dx < row.length; dx++) if (row[dx] === '#') px(gx + dx, gy + dy, 1, 1, color);
    });
  };
  const ring = phase === 'speaking' ? o.color : hot ? '#FFFFFF' : RING[phase] ?? RING.idle;
  const c = (n - 1) / 2;
  const r = n / 2 - 0.1;

  // a soft halo that swells with whoever is talking
  const glow = phase === 'hearing' || phase === 'speaking' ? Math.min(0.45, level * 0.55) * fade : 0;
  for (let row = -1; row <= n; row++) {
    const dy = row - c;
    const inner = Math.sqrt(Math.max(0, r * r - dy * dy));
    if (glow > 0.04) {
      const outer = Math.sqrt(Math.max(0, (r + 1) ** 2 - dy * dy));
      for (let col = Math.ceil(c - outer); col <= Math.floor(c + outer); col++) {
        if (Math.abs(dy) > r || Math.abs(col - c) > inner) px(col, row, 1, 1, ring, glow);
      }
    }
    if (Math.abs(dy) > r) continue;
    // dark disc with a thin rim, readable on any wallpaper
    const l = Math.ceil(c - inner), h = Math.floor(c + inner);
    px(l, row, h - l + 1, 1, '#161514', 0.9 * fade);
    const edge = Math.sqrt(Math.max(0, (r - 1) ** 2 - dy * dy));
    for (let col = l; col <= h; col++) {
      if (Math.abs(dy) > r - 1 || Math.abs(col - c) > edge) px(col, row, 1, 1, ring, fade);
    }
  }
  ctx.globalAlpha = 1;
  if (fade < 0.6) return;
  if (o.pressed) {
    // pressed: a filled disc, so the click shows the moment it lands
    for (let row = 0; row < n; row++) {
      const dy = row - c;
      const inner = Math.sqrt(Math.max(0, (r - 1) ** 2 - dy * dy));
      if (Math.abs(dy) > r - 1) continue;
      px(Math.ceil(c - inner), row, Math.floor(c + inner) - Math.ceil(c - inner) + 1, 1, '#ECE7DE', 0.95);
    }
    ctx.globalAlpha = 1;
  }

  const mid = (w, h) => [Math.floor((n - w) / 2), Math.floor((n - h) / 2)];
  if (phase === 'idle' || phase === 'hangup') {
    glyph(MIC, ...mid(5, 7), o.pressed ? '#161514' : hot ? '#FFFFFF' : phase === 'hangup' ? '#FFB4B4' : '#ECE7DE');
  } else if (phase === 'off' || phase === 'muted') {
    glyph(MIC, ...mid(5, 7), '#6E6A64');
    for (let i = 0; i < n - 4; i++) px(2 + i, n - 3 - i, 1, 1, '#FF6B6B');
  } else if (phase === 'thinking' || phase === 'transcribing') {
    glyph(spinnerFrame(Math.floor(now / 110)), ...mid(5, 5), CLAUDE);
  } else if (phase === 'approval') {
    if (Math.floor(now / 400) % 2) glyph(BANG, ...mid(1, 5), '#FF6B6B');
  } else if (phase === 'music') {
    glyph(NOTE, ...mid(4, 5), '#D8CCF2');
  } else {
    // waveform: four thin bars, quiet ticks while listening, tall when someone talks
    const t = now / 1000;
    const L = Math.max(phase === 'listening' ? 0.05 : 0.12, level);
    ctx.fillStyle = phase === 'speaking' ? '#FFFFFF' : phase === 'hearing' ? '#BFF0FF' : '#ECE7DE';
    const maxes = n >= 11 ? [5, 7, 7, 5] : [3, 5, 5, 3];
    const left = Math.floor((n - 7) / 2);
    maxes.forEach((max, i) => {
      const wobble = 0.65 + 0.35 * Math.sin(t * (2.3 + i * 0.7) + i * 1.9);
      const h = Math.max(1, Math.min(max, 1 + L * (max - 1) * 1.5 * wobble)) * cell; // device px, smooth
      ctx.fillRect(ox + (left + i * 2) * cell, Math.round(oy + (n * cell) / 2 - h / 2), cell, Math.round(h));
    });
  }
}
