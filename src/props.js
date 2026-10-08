// Accessories, all drawn relative to Clawd's sprite origin.
//   x    left edge of the 17-unit sprite
//   top  top row of the body (moves with squash)
//   y    top of the sprite while standing; the feet touch y + 10

import { WHITE, INK, CLAUDE, GLYPHS } from './sprite.js';

const WOOD = '#8B5A2B';
const STEEL = '#B9BDC5';
const STEEL_DARK = '#858A93';
const PAPER = '#F4EFE3';
const LINE = '#B9B2A4';

// ---- building ----------------------------------------------------------

export function hardHat(p, x, top) {
  p.rect(x + 6, top - 3, 5, 1, '#F4C84A');
  p.rect(x + 5, top - 2, 7, 1, '#F4C84A');
  p.rect(x + 7, top - 3, 1, 1, '#FFE8A3');
  p.rect(x + 3, top - 1, 11, 1, '#D9A531');
}

// Hammer in the right hand. frame: 'up' | 'mid' | 'down'.
export function hammer(p, x, top, frame) {
  if (frame === 'up') {
    p.rect(x + 17, top - 3, 1, 5, WOOD);
    p.rect(x + 15, top - 5, 5, 1, STEEL);
    p.rect(x + 15, top - 4, 5, 1, STEEL_DARK);
  } else if (frame === 'mid') {
    p.rect(x + 17, top + 3, 3, 1, WOOD);
    p.rect(x + 20, top + 1, 1, 4, STEEL);
    p.rect(x + 21, top + 1, 1, 4, STEEL_DARK);
  } else {
    p.rect(x + 17, top + 5, 1, 1, WOOD);
    p.rect(x + 18, top + 6, 1, 1, WOOD);
    p.rect(x + 18, top + 7, 4, 1, STEEL);
    p.rect(x + 18, top + 8, 4, 1, STEEL_DARK);
  }
}

const BRICKS = [[23, 8], [26, 8], [24, 6]];
export const BRICK_SPOT = [20, 8];
export function brickPile(p, x, y, count) {
  BRICKS.slice(0, count).forEach(([bx, by]) => {
    p.rect(x + bx, y + by, 3, 1, '#CC6A4F');
    p.rect(x + bx, y + by + 1, 3, 1, '#A44C35');
  });
}

// ---- tools -------------------------------------------------------------

export function laptop(p, x, y, t) {
  p.rect(x + 4, y + 3, 9, 1, '#9BE7FF', 0.25 + 0.15 * (Math.floor(t / 300) % 2));
  p.rect(x + 4, y + 4, 9, 5, '#5E6672');
  p.rect(x + 4, y + 4, 9, 1, '#7B8492');
  p.bitmap(['.#.', '###', '.#.'], x + 7, y + 5, CLAUDE);
  p.rect(x + 3, y + 9, 11, 1, '#3E4550');
}

const RING = ['.###.', '#...#', '#...#', '#...#', '.###.'];
// Magnifying glass over the eye at (ex, ey).
export function magnifier(p, ex, ey) {
  p.rect(ex - 1, ey, 3, 3, '#BFE9FF', 0.45);
  p.bitmap(RING, ex - 2, ey - 1, '#D7DCE3');
  p.rect(ex + 3, ey + 4, 1, 1, '#6B4F3A');
  p.rect(ex + 4, ey + 5, 1, 1, '#6B4F3A');
}

// Open book held in front; a page flips over every couple of seconds.
export function book(p, x, top, t) {
  const by = top + 3;
  p.rect(x + 2, by + 4, 13, 1, '#7A4A2A');
  p.rect(x + 3, by, 5, 4, PAPER);
  p.rect(x + 9, by, 5, 4, PAPER);
  p.rect(x + 8, by, 1, 5, '#7A4A2A');
  p.rect(x + 4, by + 1, 3, 1, LINE);
  p.rect(x + 4, by + 2, 2, 1, LINE);
  p.rect(x + 10, by + 1, 3, 1, LINE);
  p.rect(x + 10, by + 2, 3, 1, LINE);
  const ph = t % 1800;
  if (ph > 1500) {
    const k = Math.floor((ph - 1500) / 100);
    if (k === 0) p.rect(x + 11, by - 1, 2, 4, WHITE);
    if (k === 1) p.rect(x + 8, by - 2, 1, 5, WHITE);
    if (k === 2) p.rect(x + 4, by - 1, 2, 4, WHITE);
  }
}

export function goggles(p, x, top) {
  p.rect(x + 2, top + 2, 13, 1, '#3B3B40');
  for (const gx of [3, 11]) {
    p.rect(x + gx, top + 1, 3, 3, '#3B3B40');
    p.rect(x + gx + 1, top + 2, 1, 1, '#9FD8F5');
  }
}

// Bubbling flask in the right hand; the brew keeps changing colour.
export function flask(p, x, top, t) {
  const liquid = ['#7CE38B', '#B98CF0', '#F28AB2', '#FFD166'][Math.floor(t / 900) % 4];
  p.rect(x + 19, top - 2, 1, 2, '#CFE3EA');
  p.rect(x + 18, top, 3, 1, '#CFE3EA');
  p.rect(x + 17, top + 1, 5, 3, liquid);
  p.rect(x + 17, top + 4, 5, 1, '#CFE3EA');
  for (let i = 0; i < 3; i++) {
    const ph = (t / 900 + i / 3) % 1;
    p.rect(x + 19 + Math.round(Math.sin(ph * 9 + i)), top - 3 - Math.round(ph * 5), 1, 1, liquid, 1 - ph);
  }
}

const WAVE = [
  '...##...',
  '..####..',
  '.###.##.',
  '####..#.',
  '#####...',
  '########',
];
// The web: surfing a wave. Clawd stands one unit higher, on the board.
export function surf(p, x, y, t) {
  const g = y + 10;
  const bob = Math.floor(t / 400) % 2;
  p.bitmap(WAVE, x - 8 + (Math.floor(t / 300) % 2), g - 5, '#3F8EDB');
  p.rect(x - 5 + (Math.floor(t / 300) % 2), g - 5, 2, 1, '#E8F6FF');
  p.rect(x - 9, g, 36, 2, '#3F8EDB');
  for (let i = 0; i < 6; i++) p.rect(x - 9 + ((i * 7 + Math.floor(t / 90)) % 36), g, 1, 1, '#E8F6FF');
  p.rect(x + 1, g - 1 - bob, 15, 1, '#F5C84A');
  p.rect(x + 7, g - 1 - bob, 3, 1, '#E5484D');
  return bob;
}

// Planning: a clipboard checklist that ticks itself off.
export function clipboard(p, x, top, t) {
  p.rect(x + 4, top + 2, 9, 7, '#A8743F');
  p.rect(x + 5, top + 3, 7, 5, PAPER);
  p.rect(x + 7, top + 1, 3, 2, '#9AA0A8');
  const done = Math.floor(t / 700) % 4;
  for (let i = 0; i < 3; i++) {
    const row = top + 3 + i * 2;
    p.rect(x + 5, row, 1, 1, i < done ? '#3DBA5C' : LINE);
    p.rect(x + 7, row, i % 2 ? 3 : 4, 1, LINE);
  }
  const row = top + 3 + Math.min(done, 2) * 2;
  p.rect(x + 12, row - 2, 1, 2, '#F4C84A');
  p.rect(x + 12, row, 1, 1, INK);
}

// Delegating: a megaphone shouting at the helpers.
export function megaphone(p, x, top, t) {
  p.rect(x + 15, top + 3, 1, 2, '#E5484D');
  p.rect(x + 16, top + 2, 1, 4, '#F2F2F2');
  p.rect(x + 17, top + 1, 1, 6, '#E5484D');
  if (Math.floor(t / 250) % 2) {
    p.rect(x + 19, top + 2, 1, 4, WHITE);
    p.rect(x + 21, top + 1, 1, 6, WHITE, 0.6);
  }
}

// "Done" sign on a stick, waved about.
export function doneSign(p, x, top, t) {
  const sway = Math.floor(t / 350) % 2;
  p.rect(x + 17, top - 5, 1, 8, WOOD);
  p.bubble(x + 12 + sway, top - 12, 11, 7);
  p.bitmap(GLYPHS.check, x + 15 + sway, top - 10, '#3DBA5C');
}

// Hydraulic press for compaction; `drop` is how far the plate has come down.
export function press(p, x, top) {
  p.rect(x + 7, top - 12, 3, 10, '#5E646D');
  p.rect(x - 1, top - 2, 19, 2, '#7D838C');
  p.rect(x - 1, top - 2, 19, 1, '#9AA1AB');
}

// ---- sleeping ----------------------------------------------------------

export function nightcap(p, x, top) {
  const blue = '#5B7FD1';
  p.rect(x + 3, top - 1, 11, 1, '#F2F2F2');
  p.rect(x + 5, top - 2, 8, 1, blue);
  p.rect(x + 8, top - 3, 6, 1, blue);
  p.rect(x + 12, top - 4, 3, 1, blue);
  p.rect(x + 15, top - 3, 1, 2, blue);
  p.rect(x + 15, top - 1, 2, 2, '#F2F2F2');
  p.rect(x + 7, top - 2, 1, 1, '#F2F2F2');
  p.rect(x + 10, top - 3, 1, 1, '#F2F2F2');
}

// Snot bubble that swells and pops while snoring.
export function snotBubble(p, x, top, t) {
  const k = Math.floor((t % 3200) / 400);
  const bx = x + 11;
  const by = top + 5;
  if (k === 1) p.rect(bx, by, 1, 1, '#DDF3FF', 0.8);
  if (k === 2 || k === 3) p.bitmap(['.#.', '#.#', '.#.'], bx, by - 1, '#DDF3FF', 0.8);
  if (k >= 4 && k <= 6) {
    p.bitmap(['.###.', '#...#', '#...#', '#...#', '.###.'], bx, by - 2, '#DDF3FF', 0.8);
    p.rect(bx + 1, by - 1, 1, 1, WHITE);
  }
  if (k === 7) p.bitmap(['#.#', '...', '#.#'], bx + 1, by - 1, '#DDF3FF', 0.7);
}

// ---- thinking styles ---------------------------------------------------

export function chefHat(p, x, top) {
  p.rect(x + 4, top - 1, 9, 1, '#DCD6CB');
  p.rect(x + 4, top - 4, 9, 3, WHITE);
  p.rect(x + 3, top - 3, 11, 1, WHITE);
  p.rect(x + 5, top - 5, 3, 1, WHITE);
  p.rect(x + 9, top - 5, 3, 1, WHITE);
}

export function pot(p, x, y, t) {
  const g = y + 10;
  const sx = x + [6, 8, 10, 8][Math.floor(t / 180) % 4];
  p.rect(sx, g - 9, 1, 4, '#C69A5B');
  p.rect(x + 3, g - 5, 11, 1, '#4E535C');
  p.rect(x + 4, g - 5, 9, 1, '#E8894A');
  p.rect(x + 4, g - 4, 9, 4, '#6B717C');
  p.rect(x + 5, g - 3, 1, 2, '#8D939D');
  p.rect(x + 2, g - 4, 1, 1, '#4E535C');
  p.rect(x + 14, g - 4, 1, 1, '#4E535C');
  for (let i = 0; i < 3; i++) {
    const ph = (t / 1100 + i / 3) % 1;
    p.rect(x + 5 + i * 3 + Math.round(Math.sin(ph * 7 + i)), g - 6 - Math.round(ph * 9), 1, 1, '#EDEDED', 0.85 * (1 - ph));
  }
}

export function wizardHat(p, x, top) {
  const brim = '#4A378F';
  const cone = '#6A52C4';
  p.rect(x + 2, top - 1, 13, 1, brim);
  p.rect(x + 5, top - 2, 7, 1, cone);
  p.rect(x + 6, top - 3, 5, 1, cone);
  p.rect(x + 7, top - 4, 4, 1, cone);
  p.rect(x + 8, top - 5, 3, 1, cone);
  p.rect(x + 9, top - 6, 2, 1, cone);
  p.rect(x + 11, top - 7, 1, 1, cone);
  p.rect(x + 7, top - 3, 1, 1, '#F6D35B');
  p.rect(x + 10, top - 5, 1, 1, '#F6D35B');
}

export function wand(p, x, top, t) {
  p.rect(x + 17, top + 1, 1, 1, '#2E2218');
  p.rect(x + 18, top, 1, 1, '#2E2218');
  p.rect(x + 19, top - 1, 1, 1, '#2E2218');
  p.rect(x + 20, top - 2, 1, 1, Math.floor(t / 120) % 2 ? WHITE : '#F6D35B');
  const colors = ['#F6D35B', '#9FE2FF', '#F49AC2', WHITE];
  for (let i = 0; i < 4; i++) {
    const a = t / 260 + (i * Math.PI) / 2;
    p.rect(x + 20 + Math.round(Math.cos(a) * 3), top - 2 + Math.round(Math.sin(a) * 2), 1, 1, colors[i]);
  }
}

export function soapbox(p, x, ground) {
  p.rect(x + 1, ground - 3, 15, 3, '#A8743F');
  p.rect(x + 1, ground - 3, 15, 1, '#C28A4E');
  p.rect(x + 5, ground - 2, 1, 2, '#7E5430');
  p.rect(x + 11, ground - 2, 1, 2, '#7E5430');
}

export function shades(p, x, top) {
  p.rect(x + 3, top + 2, 3, 2, INK);
  p.rect(x + 11, top + 2, 3, 2, INK);
  p.rect(x + 6, top + 2, 5, 1, INK);
  p.rect(x + 3, top + 2, 1, 1, '#6E7380');
  p.rect(x + 11, top + 2, 1, 1, '#6E7380');
}

const GEAR = [
  ['...#...', '.#####.', '.#...#.', '##.#.##', '.#...#.', '.#####.', '...#...'],
  ['#.....#', '.#####.', '.#...#.', '.#.#.#.', '.#...#.', '.#####.', '#.....#'],
];
const COG = [
  ['..#..', '.###.', '##.##', '.###.', '..#..'],
  ['#...#', '.###.', '.#.#.', '.###.', '#...#'],
];
export function gears(p, x, top, t) {
  const f = Math.floor(t / 140) % 2;
  p.bitmap(GEAR[f], x + 3, top - 10, '#9AA3AE');
  p.bitmap(COG[1 - f], x + 9, top - 8, '#D9A531');
}

// An egg that wobbles, cracks and hatches a chick, then starts over.
export function egg(p, gx, g, t) {
  const cycle = t % 9000;
  const shell = '#F3EBD8';
  if (cycle > 7600) {
    p.rect(gx + 1, g - 4, 3, 3, '#FFD84D');
    p.rect(gx + 3, g - 3, 1, 1, INK);
    p.rect(gx + 4, g - 3, 1, 1, '#F08A24');
    p.rect(gx, g - 2, 5, 2, shell);
    p.rect(gx + 1, g - 2, 1, 1, '#E3D3B0');
    return;
  }
  const k = Math.floor(t / 120) % 4;
  const ex = gx + (cycle > 3000 ? [0, 1, 0, -1][k] : 0);
  p.rect(ex + 1, g - 6, 3, 1, shell);
  p.rect(ex, g - 5, 5, 4, shell);
  p.rect(ex + 1, g - 1, 3, 1, shell);
  p.rect(ex + 1, g - 4, 1, 1, '#E3D3B0');
  p.rect(ex + 3, g - 3, 1, 1, '#E3D3B0');
  if (cycle > 5200) {
    p.rect(ex + 1, g - 4, 1, 1, '#6E604A');
    p.rect(ex + 2, g - 3, 1, 1, '#6E604A');
    p.rect(ex + 3, g - 4, 1, 1, '#6E604A');
  }
}

export function lantern(p, x, top, t) {
  p.rect(x + 14, top, 9, 9, '#FFE07A', 0.12);
  p.rect(x + 18, top + 2, 1, 1, '#3B3B40');
  p.rect(x + 17, top + 3, 3, 3, '#3B3B40');
  p.rect(x + 18, top + 4, 1, 1, Math.floor(t / 200) % 2 ? '#FFE07A' : '#FFC94A');
}

export function wateringCan(p, x, top, t) {
  p.rect(x + 17, top + 3, 4, 3, '#6FA3C7');
  p.rect(x + 18, top + 2, 2, 1, '#4E7FA3');
  p.rect(x + 21, top + 2, 1, 1, '#6FA3C7');
  p.rect(x + 22, top + 1, 1, 1, '#6FA3C7');
  for (let i = 0; i < 3; i++) {
    const ph = (t / 500 + i / 3) % 1;
    p.rect(x + 23, top + 2 + Math.round(ph * 7), 1, 1, '#7FC8F8', 1 - ph * 0.5);
  }
}

// A seedling that grows into a flower over ten seconds.
export function sprout(p, sx, g, t) {
  const stage = Math.min(5, Math.floor((t % 10000) / 1600));
  const green = '#6CC070';
  p.rect(sx - 1, g - 1, 3, 1, '#6B4A2E');
  if (stage >= 1) p.rect(sx, g - 1 - Math.min(stage, 4), 1, Math.min(stage, 4), green);
  if (stage >= 2) p.rect(sx - 1, g - 3, 1, 1, green);
  if (stage >= 3) p.rect(sx + 1, g - 4, 1, 1, green);
  if (stage >= 5) {
    p.bitmap(['.#.', '#.#', '.#.'], sx - 1, g - 8, '#F27D9B');
    p.rect(sx, g - 7, 1, 1, '#FFD84D');
  }
}

export function planet(p, cx, cy) {
  p.rect(cx - 1, cy - 1, 3, 3, '#F2A65A');
  p.rect(cx - 2, cy, 5, 1, '#E8D4B0');
}

export function rainCloud(p, x, top, t, storm = false) {
  const cy = top - 8;
  if (storm && t % 2600 < 160) {
    p.bitmap(['.#', '#.', '.#', '#.'], x + 8, cy + 4, '#FFE45C');
  }
  for (let i = 0; i < 5; i++) {
    const ph = (t / 600 + i / 5) % 1;
    p.rect(x + 5 + i * 2, cy + 4 + Math.round(ph * 3), 1, 1, '#7FB2E5', 1 - ph * 0.4);
  }
  p.rect(x + 4, cy + 1, 10, 3, '#AEB6C2');
  p.rect(x + 6, cy, 4, 1, '#AEB6C2');
  p.rect(x + 10, cy - 1, 3, 2, '#AEB6C2');
  p.rect(x + 5, cy + 3, 8, 1, '#8E97A4');
}

const DOODLE = [[5, 4], [6, 4], [7, 5], [8, 5], [9, 4], [10, 4], [11, 5], [6, 6], [7, 7], [8, 7], [9, 7], [10, 6], [5, 7], [11, 7], [8, 6]];
export function sketchPad(p, x, top, t) {
  p.rect(x + 4, top + 3, 9, 6, WHITE);
  p.rect(x + 4, top + 2, 9, 1, '#4A4F57');
  const n = Math.floor((t % 6000) / 300);
  const ink = ['#E5484D', '#3F8EDB', '#3DBA5C', '#F2A65A'];
  DOODLE.slice(0, n).forEach(([dx, dy], i) => p.rect(x + dx, top + dy, 1, 1, ink[i % 4]));
  const [qx, qy] = DOODLE[Math.min(n, DOODLE.length - 1)];
  p.rect(x + qx + 1, top + qy - 2, 1, 2, '#F4C84A');
  p.rect(x + qx, top + qy - 1, 1, 1, INK);
}

export function robot(p, rx, g, t) {
  const lit = Math.floor(t / 400) % 3 ? '#5CE1E6' : '#2B3138';
  p.rect(rx + 2, g - 7, 1, 2, '#5E646D');
  p.rect(rx + 2, g - 8, 1, 1, Math.floor(t / 300) % 2 ? '#FF6B6B' : '#FFD166');
  p.rect(rx, g - 5, 5, 4, '#9AA3AE');
  p.rect(rx + 1, g - 4, 1, 1, lit);
  p.rect(rx + 3, g - 4, 1, 1, lit);
  p.rect(rx + 1, g - 1, 1, 1, '#5E646D');
  p.rect(rx + 3, g - 1, 1, 1, '#5E646D');
}

export function wrench(p, x, top, frame) {
  const r = top + 4 + frame;
  p.rect(x + 17, r, 3, 1, STEEL);
  p.rect(x + 20, r - 1, 1, 1, STEEL);
  p.rect(x + 20, r + 1, 1, 1, STEEL);
}
