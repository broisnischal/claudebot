// Everything is drawn in "units": one unit is one chunky pixel of Clawd.
// Clawd's body traces the Claude Code terminal mascot: 17x10 units with arms and legs.

export const STAGE = { w: 56, h: 30 };
export const SPRITE = { w: 17, h: 10 };
export const GROUND = 28;
export const STAND_Y = GROUND - SPRITE.h;
export const HOME_X = 20;

export const COLORS = {
  pink: '#D78787',
  clay: '#D77757',
  mint: '#7CC8A0',
  sky: '#7FAEE3',
  lavender: '#B49BDB',
  ghost: '#E4E2DC',
};

export const INK = '#1A1A1A';
export const WHITE = '#FBFAF6';
export const OUTLINE = '#26242B';
export const CLAUDE = '#D77757';

export class Painter {
  constructor(ctx, px, ox = 0, oy = 0) {
    this.ctx = ctx;
    this.px = px; // device pixels per unit, always an integer so edges stay crisp
    this.ox = ox;
    this.oy = oy;
  }

  // A painter with its own unit size, whose origin sits at (ux, uy) in this painter's units.
  child(px, ux, uy) {
    return new Painter(this.ctx, Math.max(1, px), Math.round(this.ox + ux * this.px), Math.round(this.oy + uy * this.px));
  }

  clear() {
    this.ctx.clearRect(0, 0, this.ctx.canvas.width, this.ctx.canvas.height);
  }

  rect(x, y, w, h, color, alpha = 1) {
    if (w <= 0 || h <= 0 || alpha <= 0) return;
    const { ctx, px } = this;
    ctx.globalAlpha = Math.min(1, alpha);
    ctx.fillStyle = color;
    ctx.fillRect(this.ox + Math.round(x) * px, this.oy + Math.round(y) * px, Math.round(w * px), Math.round(h * px));
    ctx.globalAlpha = 1;
  }

  bitmap(rows, x, y, color, alpha = 1) {
    rows.forEach((row, dy) => {
      for (let dx = 0; dx < row.length; dx++) {
        if (row[dx] === '#') this.rect(x + dx, y + dy, 1, 1, color, alpha);
      }
    });
  }

  // A glyph with a dark rim so it reads on any wallpaper.
  outlined(rows, x, y, color, alpha = 1) {
    for (const [ox, oy] of [[-1, 0], [1, 0], [0, -1], [0, 1]]) {
      this.bitmap(rows, x + ox, y + oy, OUTLINE, alpha);
    }
    this.bitmap(rows, x, y, color, alpha);
  }

  // Rounded box with a 1-unit outline. Content area starts at (x+1, y+1).
  bubble(x, y, w, h, fill = WHITE) {
    this.rect(x + 1, y, w - 2, h, OUTLINE);
    this.rect(x, y + 1, w, h - 2, OUTLINE);
    this.rect(x + 1, y + 1, w - 2, h - 2, fill);
  }

  dot(x, y, size) {
    this.rect(x - 1, y - 1, size + 2, size + 2, OUTLINE);
    this.rect(x, y, size, size, WHITE);
  }
}

export const GLYPHS = {
  Z: ['#####', '...#.', '..#..', '.#...', '#####'],
  z: ['####', '..#.', '.#..', '####'],
  bang: ['#', '#', '#', '.', '#'],
  ask: ['###', '..#', '.##', '...', '.#.'],
  heart: ['#.#', '###', '.#.'],
  note: ['.##', '.#.', '.#.', '##.', '##.'],
  right: ['#.', '.#', '#.'],
  left: ['.#', '#.', '.#'],
  sparkle: ['.#.', '###', '.#.'],
  check: ['....#', '...#.', '#.#..', '.#...'],
  star: ['..#..', '.###.', '#####', '.#.#.'],
};

// Pixel take on Claude Code's spinner (· ✢ ✳ ✶ ✻ ✽), played forward then back.
const SPIN = [
  ['.....', '.....', '..#..', '.....', '.....'],
  ['.....', '..#..', '.###.', '..#..', '.....'],
  ['..#..', '..#..', '#####', '..#..', '..#..'],
  ['..#..', '.###.', '#####', '.###.', '..#..'],
  ['#.#.#', '.###.', '#####', '.###.', '#.#.#'],
  ['#.#.#', '.###.', '##.##', '.###.', '#.#.#'],
];
export function spinnerFrame(i) {
  const n = SPIN.length;
  const k = i % (n * 2 - 2);
  return SPIN[k < n ? k : n * 2 - 2 - k];
}

// Eye shapes as [dx, dy, w, h] rects around the eye anchor, written for the left eye.
// The right eye mirrors them so asymmetric shapes like > < face inward.
const EYES = {
  open: [[0, 0, 1, 2]],
  blink: [[0, 1, 1, 1]],
  closed: [[-1, 1, 3, 1]],
  happy: [[-1, 1, 1, 1], [0, 0, 1, 1], [1, 1, 1, 1]],
  sad: [[-1, 0, 1, 1], [0, 1, 1, 1], [1, 1, 1, 1]],
  wide: [[0, -1, 1, 3]],
  big: [[0, 0, 2, 3]],
  squeeze: [[-1, 0, 1, 1], [0, 1, 1, 1], [-1, 2, 1, 1]],
  x: [[-1, 0, 1, 1], [1, 0, 1, 1], [0, 1, 1, 1], [-1, 2, 1, 1], [1, 2, 1, 1]],
  plus: [[0, 0, 1, 1], [-1, 1, 3, 1], [0, 2, 1, 1]],
  none: [],
};

function drawEye(p, style, ex, ey, mirror) {
  for (const [dx, dy, w, h] of EYES[style] ?? EYES.open) {
    p.rect(ex + (mirror ? -dx - w + 1 : dx), ey + dy, w, h, INK);
  }
}

// pose: { x, y, color, squash, widen, eyes, look, mouth, armL, armR, legs, turn }
//   squash > 0 flattens the body from the top (< 0 stretches it)
//   widen pushes both sides outward
//   armL / armR shift an arm up (negative) or down; null hides it
//   legs are four heights; 0 tucks a leg away
//   turn: 0 front, 1 facing right, 2 back, 3 facing left
export function drawClawd(p, pose) {
  const {
    x, y, color,
    squash = 0, widen = 0,
    eyes = 'open', look = [0, 0], mouth = null,
    armL = 0, armR = 0,
    legs = [2, 2, 2, 2],
    turn = 0,
  } = pose;

  const top = y + squash;
  const bh = 8 - squash;

  if (turn === 1 || turn === 3) {
    const dir = turn === 1 ? 1 : -1;
    p.rect(x + 6, y + 8, 1, legs[1], color);
    p.rect(x + 10, y + 8, 1, legs[2], color);
    p.rect(x + 4, top, 9, bh, color);
    const arm = dir > 0 ? armR : armL;
    if (arm !== null) p.rect(dir > 0 ? x + 13 : x + 2, Math.max(top, Math.min(top + bh - 2, top + 4 + arm)), 2, 2, color);
    drawEye(p, Array.isArray(eyes) ? eyes[0] : eyes, dir > 0 ? x + 10 : x + 6, top + 2 + look[1], false);
    return;
  }

  const bx = x + 2 - widen;
  const bw = 13 + widen * 2;
  const legX = [4 - widen, 6 - widen, 10 + widen, 12 + widen];
  legs.forEach((h, i) => p.rect(x + legX[i], y + 8, 1, h, color));

  p.rect(bx, top, bw, bh, color);

  const armY = (off) => Math.max(top, Math.min(top + bh - 2, top + 4 + off));
  if (armL !== null) p.rect(bx - 2, armY(armL), 2, 2, color);
  if (armR !== null) p.rect(bx + bw, armY(armR), 2, 2, color);
  if (turn === 2) return;

  const [lookX, lookY] = look;
  const [styleL, styleR] = Array.isArray(eyes) ? eyes : [eyes, eyes];
  const ey = top + 2 + lookY;
  drawEye(p, styleL, bx + 2 + lookX, ey, false);
  drawEye(p, styleR, bx + bw - 3 + lookX, ey, true);

  const mx = bx + Math.floor(bw / 2);
  if (mouth === 'o') p.rect(mx, top + 5, 1, 1, INK);
  if (mouth === 'O') p.rect(mx - 1, top + 4, 3, 2, INK);
  if (mouth === 'w') p.rect(mx - 1, top + 5, 3, 1, INK);
}
