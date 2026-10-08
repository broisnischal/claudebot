// Physics for the pet's window: gravity, bounces, friction, throws, and a dangling spring
// while it's held. Everything is time-based and measured in stage units (scaled by the
// window's k, desktop pixels per unit), so it behaves the same at any frame rate or size.

import { SPRITE, GROUND, STAND_Y, HOME_X } from './sprite.js';

export const PHYS = {
  gravity: 380, // units/s²
  bounce: { floor: 0.36, wall: 0.55, ceiling: 0.4, side: 0.3 }, // share of speed kept
  bounceMin: 55, // units/s: slower impacts just land
  friction: 300, // units/s² while sliding on something
  airDrag: 0.35, // per second, sideways only
  slideMin: 6, // units/s: a slide slower than this stops
  throwMin: 60, // units/s: a slower release is a plain drop, which snaps to nearby edges
  throwMax: 900,
};

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

// The pet's body inside its window (bottom orientation), in desktop px.
export function box(w) {
  const k = w.k;
  const left = w.win.x + HOME_X * k;
  return { left, right: left + SPRITE.w * k, top: w.win.y + STAND_Y * k, feet: w.win.y + GROUND * k };
}

// The highest thing to land on below `fromFeet`: a window top under the pet's middle, or
// the floor. Checking from where the feet were last step means a fast fall can't tunnel
// through a window top between frames.
export function supportBelow(w, fromFeet) {
  const m = w.monitor();
  const b = box(w);
  const cx = (b.left + b.right) / 2;
  let best = { y: m.y + m.h, id: null };
  if (w.through) return best;
  for (const s of w.surfaces) {
    if (cx >= s.x && cx <= s.x + s.w && s.y >= fromFeet - 2 && s.y < best.y && s.y > m.y) best = { y: s.y, id: s.id };
  }
  return best;
}

// Real desktop edges are walls; an edge shared with another monitor lets the pet through.
function walls(w, prev, events) {
  const k = w.k;
  const m = w.monitor();
  let b = box(w);
  if (b.left < m.x && w.vx < 0 && w.outer('left', m)) {
    w.win.x += m.x - b.left;
    w.vx = -w.vx * PHYS.bounce.wall;
    events.push(['wall', Math.abs(w.vx) / k]);
  } else if (b.right > m.x + m.w && w.vx > 0 && w.outer('right', m)) {
    w.win.x -= b.right - (m.x + m.w);
    w.vx = -w.vx * PHYS.bounce.wall;
    events.push(['wall', Math.abs(w.vx) / k]);
  }
  b = box(w);
  if (b.top < m.y && w.vy < 0 && w.outer('top', m)) {
    w.win.y += m.y - b.top;
    w.vy = -w.vy * PHYS.bounce.ceiling;
    events.push(['wall', Math.abs(w.vy) / k]);
  }
  // Windows' sides are soft, and only from outside: a pet dropped in front of a window
  // falls past it instead of getting stuck inside.
  if (w.through) return;
  b = box(w);
  for (const s of w.surfaces) {
    if (!(b.feet > s.y + 2 * k && b.top < s.y + s.h)) continue;
    if (prev.right <= s.x && b.right > s.x && w.vx > 0) {
      w.win.x -= b.right - s.x;
      w.vx = -w.vx * PHYS.bounce.side;
      events.push(['wall', Math.abs(w.vx) / k]);
    } else if (prev.left >= s.x + s.w && b.left < s.x + s.w && w.vx < 0) {
      w.win.x += s.x + s.w - b.left;
      w.vx = -w.vx * PHYS.bounce.side;
      events.push(['wall', Math.abs(w.vx) / k]);
    }
  }
}

// One step of free flight. Events: ['bounce', speed], ['land', speed, support], ['wall', speed].
export function airStep(w, s) {
  const k = w.k;
  const events = [];
  const prev = box(w);
  w.vy += PHYS.gravity * k * s;
  w.vx *= Math.exp(-PHYS.airDrag * s);
  w.win.x += w.vx * s;
  w.win.y += w.vy * s;
  walls(w, prev, events);
  const b = box(w);
  const under = supportBelow(w, prev.feet);
  if (w.vy > 0 && b.feet >= under.y) {
    const speed = w.vy / k;
    w.win.y -= b.feet - under.y;
    if (speed > PHYS.bounceMin) {
      w.vy = -w.vy * PHYS.bounce.floor;
      w.vx *= 0.85;
      events.push(['bounce', speed]);
    } else {
      w.vy = 0;
      events.push(['land', speed, under]);
    }
  }
  return events;
}

// One step of sliding along whatever it stands on. Events: ['stop'], ['off'] (slid off
// the end of a window top and is airborne again), ['wall', speed].
export function slideStep(w, s) {
  const k = w.k;
  const events = [];
  const prev = box(w);
  const slow = PHYS.friction * k * s;
  w.vx = Math.abs(w.vx) <= slow ? 0 : w.vx - Math.sign(w.vx) * slow;
  w.win.x += w.vx * s;
  walls(w, prev, events);
  const b = box(w);
  if (supportBelow(w, prev.feet).y > b.feet + 2) events.push(['off']);
  else if (Math.abs(w.vx) < PHYS.slideMin * k) events.push(['stop']);
  return events;
}

// Recent cursor positions while dragging, for the speed it was let go at.
export class Trail {
  constructor() {
    this.points = [];
  }

  add(t, x, y) {
    this.points.push({ t, x, y });
    while (this.points.length > 2 && t - this.points[0].t > 250) this.points.shift();
  }

  // Desktop px/s over the last ~120 ms; zero if the cursor had stopped before the release.
  velocity(now) {
    const recent = this.points.filter((p) => now - p.t < 160);
    if (recent.length < 2) return { vx: 0, vy: 0 };
    const a = recent[0];
    const b = recent[recent.length - 1];
    const dt = (b.t - a.t) / 1000;
    if (dt < 0.03 || now - b.t > 90) return { vx: 0, vy: 0 };
    return { vx: (b.x - a.x) / dt, vy: (b.y - a.y) / dt };
  }

  clear() {
    this.points = [];
  }
}

// The swing while it hangs from the cursor: a damped spring that lets the body lag
// behind the motion and sway back when the cursor stops. `lean` is in stage units.
export class Dangle {
  constructor() {
    this.lean = 0;
    this.vel = 0;
  }

  step(s, cursorVx) {
    const target = clamp(-cursorVx * 0.012, -5, 5);
    this.vel += (target - this.lean) * 70 * s;
    this.vel *= Math.exp(-4.5 * s);
    this.lean = clamp(this.lean + this.vel * s, -6, 6);
  }

  reset() {
    this.lean = 0;
    this.vel = 0;
  }
}

export const capSpeed = (vx, vy, k) => {
  const max = PHYS.throwMax * k;
  const speed = Math.hypot(vx, vy);
  return speed > max ? [(vx / speed) * max, (vy / speed) * max] : [vx, vy];
};
