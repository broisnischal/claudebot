// Moves the pet's window around the desktop: strolling along whatever it stands on,
// zooming, chasing the cursor, flying, and falling with gravity. Other windows are
// surfaces: drop the pet near a window's top and it snaps onto it, near a side (or the
// screen edge) and it clings there; move that window and the pet rides along.
// Coordinates come from the backend as-is (physical pixels on Windows, macOS and X11,
// layout pixels on Hyprland), so everything here is relative to the window's own size.

import { STAGE, SPRITE, GROUND, STAND_Y, HOME_X } from './sprite.js';

// Off the floor the pet can sit on any screen edge, rotated so its feet face the edge:
// the window turns portrait on the side walls and the canvas draws through a rotation.
// It travels between edges by walking the screen's perimeter and turning at corners.
export const EDGES = ['top', 'right', 'bottom', 'left']; // clockwise
const HALF = SPRITE.w / 2; // half the pet's length along an edge
const DEPTH = 10; // stage units from the feet to the top of the head
const TUCK = { sit: 0, out: 0.45, in: 0.86 }; // how far past the edge it pushes, as a share of DEPTH
const RIM_PACE = 22; // stage units per second along an edge
const CENTER = [HOME_X + HALF, GROUND - 5]; // middle of the body, in stage units

const GRAVITY = 380; // stage units per second squared
const SNAP = 7; // stage units: how close to an edge or a top counts as touching it
const CLING_MS = [20e3, 45e3]; // how long it hangs on before its arms get tired
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const rand = (a, b) => a + Math.random() * (b - a);

export class World {
  constructor(invoke) {
    this.invoke = invoke;
    this.backend = 'fixed';
    this.monitors = [];
    this.surfaces = []; // other windows: { id, x, y, w, h }
    this.win = null;
    this.cursor = null;
    this.enabled = true;
    this.target = null;
    this.speed = 0;
    this.vy = 0;
    this.falling = false;
    this.flight = null;
    // What the pet stands on or hangs from:
    //   { kind: 'floor' } | { kind: 'top', id, ox } | { kind: 'side', id, facing, oy, until }
    this.perch = null;
    // On a screen edge instead: { edge, s, tuck, mode: 'sit' | 'peek' | 'hide', route, out, flipAt, until }
    // s is where along the edge the middle of the pet is (x on top/bottom, y on the sides).
    this.rim = null;
    this.edge = 'bottom'; // the way the pet's feet point, which decides the window's rotation
    this.onOrient = null;
    this.afterLanding = null;
    this.onLand = null;
    this.inflight = false;
    this.queued = false;
  }

  get canRoam() {
    return this.enabled && this.backend !== 'fixed' && !!this.win && this.monitors.length > 0;
  }

  // Desktop pixels per stage unit.
  // The long side of the window is always STAGE.w units, whichever way it's turned.
  get k() {
    return this.win ? Math.max(this.win.w, this.win.h) / STAGE.w : 1;
  }

  get moving() {
    return this.target !== null || !!this.rim?.route.length;
  }

  get flying() {
    return this.flight !== null;
  }

  get clinging() {
    return this.perch?.kind === 'side';
  }

  // Walking direction in stage terms, so the legs and eyes turn the right way on any edge.
  get dir() {
    if (this.flight) return Math.sign(this.flight.tx - this.flight.x0);
    const r = this.rim;
    if (r?.route.length) {
      const d = r.route[0].edge === r.edge ? Math.sign(r.route[0].s - r.s) : 0;
      return r.edge === 'top' || r.edge === 'right' ? -d : d;
    }
    return this.target === null ? 0 : Math.sign(this.target - this.win.x);
  }

  // Walking speed in stage units per second.
  get pace() {
    return this.speed / this.k;
  }

  async refresh() {
    if (!this.invoke || this.moving || this.falling || this.flying) return;
    try {
      const w = await this.invoke('world');
      this.backend = w.backend;
      this.monitors = w.monitors ?? [];
      if (w.window && !this.rim) {
        // Right after turning, the compositor can still report the old shape; keep ours then.
        const fresh = w.window;
        const portrait = this.edge === 'left' || this.edge === 'right';
        this.win = !this.win || fresh.h > fresh.w === portrait ? fresh : { ...fresh, w: this.win.w, h: this.win.h };
      }
    } catch {
      // A missed reply keeps the last known state rather than switching roaming off.
    }
  }

  async pollSurfaces() {
    if (!this.invoke || this.backend === 'fixed') return;
    try {
      this.surfaces = (await this.invoke('surfaces')) ?? [];
    } catch {
      this.surfaces = []; // builds without the surfaces command: floor and screen edges only
    }
  }

  async pollCursor() {
    if (!this.invoke || this.backend === 'fixed') return;
    try {
      this.cursor = await this.invoke('cursor');
    } catch {
      this.cursor = null;
    }
  }

  // ---- geometry ----

  monitor() {
    const cx = this.win.x + this.win.w / 2;
    const cy = this.win.y + this.win.h / 2;
    const inside = this.monitors.find((m) => cx >= m.x && cx < m.x + m.w && cy >= m.y && cy < m.y + m.h);
    if (inside) return inside;
    const dist = (m) => Math.hypot(cx - (m.x + m.w / 2), cy - (m.y + m.h / 2));
    return [...this.monitors].sort((a, b) => dist(a) - dist(b))[0];
  }

  feet() {
    return this.win.y + GROUND * this.k;
  }

  centerX() {
    return this.win.x + (HOME_X + SPRITE.w / 2) * this.k;
  }

  // Window y that puts the feet on a line.
  standOn(y) {
    return y - GROUND * this.k;
  }

  // Window y that puts the feet on the bottom edge of the monitor's work area.
  restY(m) {
    return this.standOn(m.y + m.h);
  }

  surface(id) {
    return this.surfaces.find((s) => s.id === id);
  }

  // The highest thing under the pet's feet: a window top or the floor.
  support() {
    const m = this.monitor();
    const cx = this.centerX();
    const feet = this.feet();
    let best = { y: m.y + m.h, id: null };
    if (this.through) return best;
    for (const s of this.surfaces) {
      if (cx >= s.x && cx <= s.x + s.w && s.y >= feet - 2 && s.y < best.y && s.y > m.y) best = { y: s.y, id: s.id };
    }
    return best;
  }

  // Window x range for walking: the length of the window top it stands on, else the monitor.
  range() {
    const k = this.k;
    const s = this.perch?.kind === 'top' && this.surface(this.perch.id);
    if (s) return [s.x - (HOME_X + 4) * k, s.x + s.w - (HOME_X + SPRITE.w - 4) * k];
    const m = this.monitor();
    return [m.x - HOME_X * k, m.x + m.w - (HOME_X + SPRITE.w) * k];
  }

  // Window x that hangs the pet on a vertical edge. facing 1: the wall is on its right.
  sideX(edgeX, facing) {
    return facing > 0 ? edgeX - (HOME_X + SPRITE.w) * this.k : edgeX - HOME_X * this.k;
  }

  petCenter() {
    const [ox, oy] = this.mapPoint(this.edge, ...CENTER);
    return { x: this.win.x + ox, y: this.win.y + oy };
  }

  // A stage point (units) as an offset inside the window (desktop px), for a rotation.
  mapPoint(edge, x, y) {
    const k = this.k;
    const [W, H] = [STAGE.w * k, STAGE.h * k];
    [x, y] = [x * k, y * k];
    if (edge === 'top') return [W - x, H - y];
    if (edge === 'left') return [H - y, x];
    if (edge === 'right') return [y, W - x];
    return [x, y];
  }

  // A direction on screen turned into stage terms (for where the eyes look).
  toStage(dx, dy) {
    if (this.edge === 'top') return [-dx, -dy];
    if (this.edge === 'left') return [dy, -dx];
    if (this.edge === 'right') return [-dy, dx];
    return [dx, dy];
  }

  sizeFor(edge) {
    const k = this.k;
    return edge === 'left' || edge === 'right' ? { w: STAGE.h * k, h: STAGE.w * k } : { w: STAGE.w * k, h: STAGE.h * k };
  }

  sameMonitor(point) {
    const m = this.monitor();
    return point && point.x >= m.x && point.x < m.x + m.w && point.y >= m.y && point.y < m.y + m.h;
  }

  // ---- walking ----

  get canWalk() {
    return this.canRoam && !this.rim && !this.clinging && !this.flying && !this.falling;
  }

  walkTo(screenX, unitsPerSec) {
    if (!this.canWalk) return false;
    const [lo, hi] = this.range();
    const target = clamp(screenX - (HOME_X + SPRITE.w / 2) * this.k, lo, hi);
    if (Math.abs(target - this.win.x) < this.k) return false;
    this.target = target;
    this.speed = unitsPerSec * this.k;
    return true;
  }

  // Head somewhere at least `minUnits` away along the floor or window top.
  wander(minUnits, unitsPerSec) {
    if (this.rim?.mode === 'sit' && !this.rim.route.length) {
      const [lo, hi] = this.rimRange(this.rim.edge);
      const s = lo + Math.random() * (hi - lo);
      if (Math.abs(s - this.rim.s) < minUnits * this.k) return false;
      this.rim.route = [{ edge: this.rim.edge, s }];
      return true;
    }
    if (!this.canWalk) return false;
    const [lo, hi] = this.range();
    for (let i = 0; i < 8; i++) {
      const x = lo + Math.random() * (hi - lo);
      if (Math.abs(x - this.win.x) >= minUnits * this.k) {
        this.target = x;
        this.speed = unitsPerSec * this.k;
        return true;
      }
    }
    return false;
  }

  // Run to whichever end is further away.
  dash(unitsPerSec) {
    if (!this.canWalk) return false;
    const [lo, hi] = this.range();
    this.target = this.win.x - lo > hi - this.win.x ? lo : hi;
    this.speed = unitsPerSec * this.k;
    return true;
  }

  stop() {
    this.target = null;
    if (this.rim?.mode === 'sit' && this.rim.route.length === 1 && this.rim.route[0].edge === this.rim.edge) this.rim.route = [];
  }

  // Drop everything in progress, including a move already queued for the compositor,
  // so nothing yanks the window while someone drags it.
  grab() {
    this.target = null;
    this.flight = null;
    this.falling = false;
    this.perch = null;
    this.rim = null;
    this.afterLanding = null;
    this.queued = false;
  }

  // Stop hanging on or flying, and fall. A pet hiding on its own comes back out instead;
  // one that was told to hide stays hidden.
  letGo() {
    if (this.clinging || this.flying) {
      this.perch = null;
      this.flight = null;
      this.startFall();
    }
    if (this.rim && !this.rim.manual && this.rim.mode !== 'sit') this.rim.mode = 'sit';
  }

  // ---- flying ----

  // Lift off, cross the screen with a little bob, then let gravity bring it down.
  fly(unitsPerSec = 34) {
    if (!this.canRoam) return false;
    const m = this.monitor();
    const k = this.k;
    const [lo, hi] = [m.x - HOME_X * k, m.x + m.w - (HOME_X + SPRITE.w) * k];
    let tx = this.win.x;
    for (let i = 0; i < 8 && Math.abs(tx - this.win.x) < 40 * k; i++) tx = lo + Math.random() * (hi - lo);
    const peak = Math.max(m.y - STAND_Y * k + 12 * k, this.win.y - rand(30, 60) * k);
    this.flight = { x0: this.win.x, y0: this.win.y, tx, peak, t: 0, dur: Math.abs(tx - this.win.x) / (unitsPerSec * k) + 0.8 };
    this.target = null;
    this.perch = null;
    this.falling = false;
    return true;
  }

  // ---- landing and gravity ----

  startFall(through = false) {
    this.falling = true;
    this.through = through;
    this.vy = 0;
    this.perch = null;
  }

  // Called after a drop. Whatever is closest within reach wins: a window top, any screen
  // edge (the pet turns to sit on it), or a window's side to cling to. Else it falls.
  drop() {
    if (!this.canRoam) return false;
    const k = this.k;
    const reach = SNAP * k;
    const m = this.monitor();
    const c = this.petCenter();
    const half = 5 * k; // centre of the body to the feet
    const feet = c.y + half;
    const options = [];

    for (const s of this.surfaces) {
      if (c.x >= s.x && c.x <= s.x + s.w && s.y > m.y) options.push({ d: Math.abs(s.y - feet), go: () => this.perchOn(s) });
    }
    const gaps = { top: c.y - half - m.y, bottom: m.y + m.h - feet, left: c.x - half - m.x, right: m.x + m.w - c.x - half };
    for (const [edge, gap] of Object.entries(gaps)) {
      const go = edge === 'bottom' ? () => this.toFloor() : () => this.sitOn(edge, edge === 'top' ? c.x : c.y);
      options.push({ d: Math.max(0, gap), go });
    }
    for (const s of this.surfaces) {
      if (feet < s.y + 2 * k || c.y - half > s.y + s.h) continue;
      options.push({ d: Math.abs(c.x + HALF * k - s.x), go: () => this.clingTo(s, s.x, 1) });
      options.push({ d: Math.abs(c.x - HALF * k - (s.x + s.w)), go: () => this.clingTo(s, s.x + s.w, -1) });
    }
    const best = options.filter((o) => o.d < reach).sort((a, b) => a.d - b.d)[0];
    if (best) {
      best.go();
      this.onLand?.();
      return true;
    }

    this.reorient('bottom');
    const { y, id } = this.support();
    if (Math.abs(this.win.y - this.standOn(y)) <= 2) {
      this.settle(y, id);
      return false;
    }
    this.startFall();
    return true;
  }

  perchOn(s) {
    this.reorient('bottom');
    this.win.y = this.standOn(s.y);
    this.perch = { kind: 'top', id: s.id, ox: this.win.x - s.x, sx: s.x, sy: s.y };
    this.send();
  }

  toFloor() {
    this.reorient('bottom');
    this.win.y = this.restY(this.monitor());
    this.perch = { kind: 'floor' };
    this.send();
  }

  clingTo(s, edgeX, facing) {
    this.reorient('bottom');
    this.win.x = this.sideX(edgeX, facing);
    this.perch = { kind: 'side', id: s.id, facing, oy: this.win.y - s.y, until: performance.now() + rand(...CLING_MS) };
    this.send();
  }

  // ---- screen edges ----

  // Range of `s` on an edge that keeps the whole pet on the monitor.
  rimRange(edge) {
    const m = this.monitor();
    const k = this.k;
    return edge === 'top' || edge === 'bottom'
      ? [m.x + HALF * k, m.x + m.w - HALF * k]
      : [m.y + HALF * k, m.y + m.h - HALF * k];
  }

  // Window position for a spot on an edge, pushed `tuck` of the way past it.
  placeOn(edge, s, tuck) {
    const m = this.monitor();
    const shift = tuck * DEPTH * this.k;
    const [fx, fy] = this.mapPoint(edge, HOME_X + HALF, GROUND);
    if (edge === 'bottom') return { x: s - fx, y: m.y + m.h + shift - fy };
    if (edge === 'top') return { x: s - fx, y: m.y - shift - fy };
    if (edge === 'left') return { x: m.x - shift - fx, y: s - fy };
    return { x: m.x + m.w + shift - fx, y: s - fy };
  }

  // Turn the window for another edge, keeping the pet where it is on screen.
  reorient(edge) {
    if (edge === this.edge) return;
    const c = this.petCenter();
    this.edge = edge;
    Object.assign(this.win, this.sizeFor(edge));
    const [ox, oy] = this.mapPoint(edge, ...CENTER);
    this.win.x = c.x - ox;
    this.win.y = c.y - oy;
    this.onOrient?.(edge);
    this.send();
  }

  sitOn(edge, s) {
    const [lo, hi] = this.rimRange(edge);
    this.perch = null;
    this.target = null;
    this.rim = { edge, s: clamp(s, lo, hi), tuck: 0, mode: 'sit', route: [], goal: null, out: false, flipAt: 0, until: 0, manual: false };
    this.reorient(edge);
  }

  // Is this side of the monitor the real edge of the desktop (no monitor beyond it)?
  outer(edge, m = this.monitor()) {
    return !this.monitors.some((o) => {
      if (o === m) return false;
      const vertical = o.y < m.y + m.h && o.y + o.h > m.y;
      const horizontal = o.x < m.x + m.w && o.x + o.w > m.x;
      if (edge === 'left') return vertical && Math.abs(o.x + o.w - m.x) < 2;
      if (edge === 'right') return vertical && Math.abs(o.x - (m.x + m.w)) < 2;
      if (edge === 'top') return horizontal && Math.abs(o.y + o.h - m.y) < 2;
      return horizontal && Math.abs(o.y - (m.y + m.h)) < 2;
    });
  }

  // Where along the perimeter a spot is, measured clockwise from the top-left corner.
  around(edge, s, m) {
    if (edge === 'top') return s - m.x;
    if (edge === 'right') return m.w + (s - m.y);
    if (edge === 'bottom') return m.w + m.h + (m.x + m.w - s);
    return 2 * m.w + m.h + (m.y + m.h - s);
  }

  // Walk the shorter way round the perimeter, turning at each corner.
  routeTo(edge, s) {
    const r = this.rim;
    const m = this.monitor();
    const total = 2 * (m.w + m.h);
    const cw = (((this.around(edge, s, m) - this.around(r.edge, r.s, m)) % total) + total) % total;
    const clockwise = cw <= total - cw;
    const forward = { top: 1, right: 1, bottom: -1, left: -1 }; // clockwise direction of s on each edge
    const route = [];
    let at = r.edge;
    for (let i = 0; at !== edge && i < 4; i++) {
      const [lo, hi] = this.rimRange(at);
      route.push({ edge: at, s: (clockwise ? forward[at] : -forward[at]) > 0 ? hi : lo });
      const next = EDGES[(EDGES.indexOf(at) + (clockwise ? 1 : 3)) % 4];
      const [nlo, nhi] = this.rimRange(next);
      route.push({ edge: next, s: (clockwise ? forward[next] : -forward[next]) > 0 ? nlo : nhi });
      at = next;
    }
    const [lo, hi] = this.rimRange(edge);
    route.push({ edge, s: clamp(s, lo, hi) });
    r.route = route;
  }

  // Voice and menu commands. Returns false when this desktop can't move the window.
  //   hide, peek, peek:<edge>, edge:<edge>, corner:<top|bottom>-<left|right>, home
  command(name) {
    if (!this.canRoam) return false;
    // From a window top, a side or mid-air, get down to the floor first.
    if (!this.rim && (this.falling || this.flying || this.perch?.kind !== 'floor')) {
      this.afterLanding = () => this.command(name);
      this.perch = null;
      this.flight = null;
      if (!this.falling) this.startFall(true);
      return true;
    }
    if (name === 'home') return this.goHome(), true;
    if (!this.rim) this.sitOn('bottom', this.centerX());
    const r = this.rim;
    const m = this.monitor();
    const [cmd, arg] = name.split(':');
    let edge = r.edge;
    let s = r.s;
    let mode = 'sit';
    if (cmd === 'hide' || cmd === 'peek') mode = cmd;
    if (arg && cmd !== 'corner') edge = arg;
    if (cmd === 'corner') {
      const [v, h] = arg.split('-');
      edge = v;
      const [lo, hi] = this.rimRange(v);
      s = h === 'left' ? lo : hi;
    } else if (edge !== r.edge) {
      const c = this.petCenter();
      s = edge === 'top' || edge === 'bottom' ? c.x : m.y + m.h * 0.6;
    }
    r.manual = true;
    r.until = 0;
    r.home = false;
    this.goTo(edge, s, mode);
    return true;
  }

  goTo(edge, s, mode) {
    const r = this.rim;
    r.mode = 'sit';
    r.goal = mode;
    r.out = false;
    this.routeTo(edge, s);
  }

  // A trip of its own: off to a real edge of the desktop to peek or sit for a while.
  explore() {
    if (!this.canRoam || this.rim || this.perch?.kind !== 'floor') return false;
    const m = this.monitor();
    const spots = ['left', 'right', 'top'].filter((e) => this.outer(e, m));
    if (!spots.length) return false;
    this.sitOn('bottom', this.centerX());
    const edge = spots[Math.floor(Math.random() * spots.length)];
    const [lo, hi] = this.rimRange(edge);
    this.goTo(edge, lo + Math.random() * (hi - lo), Math.random() < 0.6 ? 'peek' : 'sit');
    this.rim.until = performance.now() + rand(25e3, 60e3);
    return true;
  }

  // Back to the floor: sliding up out of a bottom hide, or letting go and dropping.
  goHome() {
    const r = this.rim;
    if (!r) return;
    if (r.edge === 'bottom') {
      r.route = [];
      r.mode = 'sit';
      r.goal = null;
      r.home = true;
      return;
    }
    this.rim = null;
    this.reorient('bottom');
    this.startFall(true);
  }

  rimTick(s) {
    const r = this.rim;
    const now = performance.now();
    if (r.route.length) {
      const wp = r.route[0];
      if (wp.edge !== r.edge) {
        r.edge = wp.edge;
        r.s = wp.s;
        r.route.shift();
        this.reorient(wp.edge);
      } else {
        const step = RIM_PACE * this.k * s;
        const d = wp.s - r.s;
        if (Math.abs(d) <= step) {
          r.s = wp.s;
          r.route.shift();
        } else {
          r.s += Math.sign(d) * step;
        }
      }
      if (!r.route.length && r.goal) {
        r.mode = r.goal;
        r.goal = null;
        r.flipAt = now + 700;
      }
    }
    if (r.mode === 'peek' && !r.route.length && now > r.flipAt) {
      r.out = !r.out;
      r.flipAt = now + (r.out ? rand(2200, 4200) : rand(1600, 4800));
    }
    const want = r.route.length || r.mode === 'sit' ? TUCK.sit : r.mode === 'hide' || !r.out ? TUCK.in : TUCK.out;
    const ease = 1.4 * s;
    r.tuck += clamp(want - r.tuck, -ease, ease);
    if (r.home && r.tuck < 0.01) {
      this.rim = null;
      this.toFloor();
      return;
    }
    if (r.until && now > r.until && !r.route.length) {
      r.until = 0;
      this.goHome();
      if (!this.rim) return;
    }
    const pos = this.placeOn(r.edge, r.s, r.tuck);
    if (Math.abs(pos.x - this.win.x) > 0.3 || Math.abs(pos.y - this.win.y) > 0.3) {
      this.win.x = pos.x;
      this.win.y = pos.y;
      this.send();
    }
  }

  settle(y, id) {
    this.win.y = this.standOn(y);
    const s = id && this.surface(id);
    this.perch = s ? { kind: 'top', id, ox: this.win.x - s.x, sx: s.x, sy: s.y } : { kind: 'floor' };
  }

  // Twice a second: keep the pet on what it stands on. Windows that move carry it
  // along, windows that vanish drop it, and tired arms let go.
  watch() {
    if (!this.canRoam || this.falling || this.flying || this.moving || this.rim) return;
    const p = this.perch;
    if (p?.kind === 'side') {
      if (performance.now() > p.until) return this.letGo();
      if (!p.id) return;
      const s = this.surface(p.id);
      if (!s) return this.letGo();
      const x = this.sideX(p.facing > 0 ? s.x : s.x + s.w, p.facing);
      const y = s.y + p.oy;
      if (x !== this.win.x || y !== this.win.y) {
        this.win.x = x;
        this.win.y = y;
        this.send();
      }
      return;
    }
    if (p?.kind === 'top') {
      const s = this.surface(p.id);
      if (!s) return this.startFall();
      if (s.x !== p.sx || s.y !== p.sy) {
        this.win.x = s.x + p.ox;
        this.win.y = this.standOn(s.y);
        p.sx = s.x;
        p.sy = s.y;
        this.send();
      }
      return;
    }
    // On the floor, or nobody knows: make sure something is underneath.
    const { y, id } = this.support();
    const rest = this.standOn(y);
    if (this.win.y < rest - 2) return this.startFall();
    if (this.win.y > rest + 2) {
      this.win.y = rest;
      this.send();
    }
    this.settle(y, id);
  }

  tick(dt) {
    if (!this.win || !this.canRoam) {
      this.falling = false;
      this.flight = null;
      this.target = null;
      return;
    }
    const s = dt / 1000;
    if (this.rim) {
      this.rimTick(s);
    } else if (this.flight) {
      const f = this.flight;
      f.t += s;
      const u = Math.min(1, f.t / f.dur);
      const ease = u < 0.5 ? 2 * u * u : 1 - (-2 * u + 2) ** 2 / 2;
      this.win.x = f.x0 + (f.tx - f.x0) * ease;
      const climb = Math.min(1, u / 0.25);
      this.win.y = f.y0 + (f.peak - f.y0) * (1 - (1 - climb) ** 2) + Math.sin(f.t * 7) * 1.5 * this.k * climb;
      if (u >= 1) {
        this.flight = null;
        this.startFall();
      }
      this.send();
    } else if (this.falling) {
      const { y, id } = this.support();
      const rest = this.standOn(y);
      this.vy += GRAVITY * this.k * s;
      this.win.y = Math.min(rest, this.win.y + this.vy * s);
      if (this.win.y >= rest) {
        this.falling = false;
        this.through = false;
        this.vy = 0;
        this.settle(y, id);
        this.onLand?.();
        const next = this.afterLanding;
        this.afterLanding = null;
        next?.();
      }
      this.send();
    } else if (this.target !== null) {
      const d = this.target - this.win.x;
      const step = this.speed * s;
      if (Math.abs(d) <= step) {
        this.win.x = this.target;
        this.target = null;
      } else {
        this.win.x += Math.sign(d) * step;
      }
      const p = this.perch;
      if (p?.kind === 'top') p.ox = this.win.x - p.sx;
      this.send();
    }
  }

  // One move in flight at a time; the latest position wins.
  send() {
    if (this.inflight) {
      this.queued = true;
      return;
    }
    this.inflight = true;
    this.invoke('move_window', { x: Math.round(this.win.x), y: Math.round(this.win.y) })
      .catch(() => {})
      .finally(() => {
        this.inflight = false;
        if (this.queued) {
          this.queued = false;
          this.send();
        }
      });
  }
}
