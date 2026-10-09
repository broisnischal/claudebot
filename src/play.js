// The game layer: a see-through window over the pet's monitor. It holds the ball I play fetch with
// and the stones and balls the pet throws, so they fly across the whole screen instead of inside the
// pet's small window. Only the ball takes clicks; everything else goes through to what's underneath.
//
// The pet's window (game.js) moves the pet. The two talk through Tauri events: the pet sends where
// its mouth is ('play:pet') and what it does with the ball ('play:cmd'); this window sends where the
// ball is and where it will land ('play:ball'). Positions on the wire are desktop pixels.
import { Painter } from './sprite.js';
import { drawText, textWidth } from './font.js';

const T = window.__TAURI__;
const invoke = T ? (cmd, args) => T.core.invoke(cmd, args) : null;
const emit = (name, payload) => T?.event.emit(name, payload).catch(() => {});

const canvas = document.getElementById('play');
const ctx = canvas.getContext('2d');

let k = 7; // desktop pixels per pet unit; sizes and gravity follow the pet's
let origin = { x: 0, y: 0 }; // this window's top left on the desktop
let W = innerWidth, H = innerHeight;
let pet = null; // { mouth: {x, y}, center: {x, y}, dir } in window pixels
let game = false; // a game of fetch is on; otherwise only the pet's throws fly here

// `mine`: the last throw was mine, so the pet's catch scores; its own drops never do
const ball = { state: 'gone', x: 0, y: 0, vx: 0, vy: 0, spin: 0, bounces: 0, restAt: 0, mine: false };
const bits = []; // stones and kicked balls: { x, y, vx, vy, w, h, color, age, life, rest }
const puffs = []; // dust where something hits the floor
let grip = null; // { dx, dy, moved } while I hold the ball
let trail = [];
let score = 0;
let best = 0;
try { best = Number(localStorage.getItem('fetch-best-2')) || 0; } catch { /* storage can be off */ }
let banner = null; // { text, color, at } a word over the ball: CATCH! +3
let hint = null; // { text, until } a line over the ball: GRAB THE BALL AND THROW IT

const R = () => 2.6 * k; // ball radius: big enough to grab without aiming
const G = () => 380 * k; // gravity, as the pet falls
const FLOOR = () => H; // the window's bottom is the monitor's floor, where the pet stands
const MAX_SPEED = () => 520 * k;

// ---- layout ------------------------------------------------------------------------

function layout() {
  const dpr = window.devicePixelRatio || 1;
  W = innerWidth;
  H = innerHeight;
  canvas.width = Math.round(W * dpr);
  canvas.height = Math.round(H * dpr);
  canvas.style.width = `${W}px`;
  canvas.style.height = `${H}px`;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.imageSmoothingEnabled = false;
}
addEventListener('resize', layout);
layout();

// ---- messages from the pet ---------------------------------------------------------

const local = (p) => ({ x: p.x - origin.x, y: p.y - origin.y });

const listening = [];
listening.push(T?.event.listen('play:pet', (e) => {
  const m = e.payload;
  k = m.k || k;
  if (m.monitor) origin = { x: m.monitor.x, y: m.monitor.y };
  pet = { mouth: local(m.mouth), center: local(m.center), dir: m.dir || 1 };
}));

listening.push(T?.event.listen('play:cmd', (e) => {
  const c = e.payload;
  // only a game hands the ball over, so that means one is on even if its start went missing
  if (c.cmd === 'carry' || c.cmd === 'drop') game = true;
  if (c.cmd === 'start') {
    game = true;
    score = 0;
    if (c.monitor) origin = { x: c.monitor.x, y: c.monitor.y };
  } else if (c.cmd === 'stop') {
    game = false;
    ball.state = 'gone';
    hint = null;
  } else if (c.cmd === 'carry' && pet) {
    // the pet has it in its mouth: a catch if my throw was still in the air, a fetch off the floor
    if (game && ball.mine && (ball.state === 'flying' || ball.state === 'rest')) {
      score_(ball.state === 'flying' && ball.y < FLOOR() - R() - k * 2, ball.bounces);
    }
    ball.mine = false;
    ball.state = 'carried';
    grip = null;
    canvas.classList.remove('held');
  } else if (c.cmd === 'drop' && pet) {
    // it lets go in front of me: a little toss toward the cursor
    Object.assign(ball, { state: 'flying', x: pet.mouth.x, y: pet.mouth.y, vx: (c.vx || 0) * k, vy: (c.vy || -40) * k, bounces: 0, mine: false });
    hint = { text: 'GRAB THE BALL AND THROW IT', until: performance.now() + 6000 };
  } else if (c.cmd === 'stone') {
    const p = local(c);
    bits.push({ kind: 'stone', x: p.x, y: p.y, vx: c.dir * rand(70, 110) * k, vy: -rand(35, 55) * k,
      w: pick([2, 2.5, 3]), h: pick([1.5, 2]), color: pick(['#8D8A84', '#A7A39B', '#6F6B66']), age: 0, life: 6, bounce: 0.55, keep: 0.86 });
  } else if (c.cmd === 'kick') {
    const p = local(c);
    bits.push({ kind: 'ball', x: p.x, y: p.y, vx: c.dir * rand(120, 170) * k, vy: -rand(60, 90) * k,
      w: 3.4, h: 3.4, color: '#E5533D', age: 0, life: 7, bounce: 0.6, keep: 0.8 });
  } else if (c.cmd === 'say') {
    hint = { text: String(c.text || '').toUpperCase(), until: performance.now() + (c.ms || 3000) };
  }
}));

function score_(air, bounces) {
  const wall = bounces > 0;
  const points = air ? (wall ? 5 : 3) : 1;
  score += points;
  if (score > best) {
    best = score;
    try { localStorage.setItem('fetch-best-2', String(best)); } catch { /* fine */ }
  }
  banner = { text: air ? (wall ? `OFF THE WALL! +${points}` : `CATCH! +${points}`) : `GOT IT +${points}`,
    color: air ? '#F6C945' : '#F4EFE6', at: performance.now() };
}

// ---- my hand -----------------------------------------------------------------------

canvas.addEventListener('pointerdown', (e) => {
  if (e.button !== 0 || ball.state === 'gone') return;
  if (Math.hypot(e.clientX - ball.x, e.clientY - ball.y) > R() + 16) return;
  canvas.setPointerCapture(e.pointerId);
  grip = { dx: ball.x - e.clientX, dy: ball.y - e.clientY, moved: 0, x0: e.clientX, y0: e.clientY };
  trail = [{ t: performance.now(), x: e.clientX, y: e.clientY }];
  ball.state = 'held';
  ball.bounces = 0;
  hint = null;
  canvas.classList.add('held');
  if (game) emit('play:event', { type: 'grabbed' });
});

canvas.addEventListener('pointermove', (e) => {
  if (!grip) return;
  if (!(e.buttons & 1)) return release(e);
  grip.moved = Math.max(grip.moved, Math.hypot(e.clientX - grip.x0, e.clientY - grip.y0));
  ball.x = clamp(e.clientX + grip.dx, R(), W - R());
  ball.y = clamp(e.clientY + grip.dy, R(), FLOOR() - R());
  const now = performance.now();
  trail.push({ t: now, x: ball.x, y: ball.y });
  while (trail.length > 2 && now - trail[0].t > 120) trail.shift();
});

canvas.addEventListener('pointerup', (e) => release(e));
canvas.addEventListener('lostpointercapture', (e) => release(e));

function release() {
  if (!grip) return;
  const now = performance.now();
  const a = trail[0], b = trail[trail.length - 1];
  const dt = Math.max(0.016, (b.t - a.t) / 1000);
  let vx = (b.x - a.x) / dt, vy = (b.y - a.y) / dt;
  if (grip.moved < 6 || now - b.t > 100) {
    // a click, or held still before letting go: a gentle toss up
    vx = rand(-20, 20) * k;
    vy = -70 * k;
  }
  const speed = Math.hypot(vx, vy);
  if (speed > MAX_SPEED()) [vx, vy] = [vx / speed * MAX_SPEED(), vy / speed * MAX_SPEED()];
  Object.assign(ball, { state: 'flying', vx, vy, bounces: 0, mine: true });
  grip = null;
  canvas.classList.remove('held');
  if (game) emit('play:event', { type: 'thrown', speed: Math.round(Math.hypot(vx, vy) / k) });
}

// ---- physics ----------------------------------------------------------------------

// One step for anything that flies here; returns 'floor' when it hit the floor this step.
function step(o, s, r, bounce, keep) {
  o.vy += G() * s;
  o.x += o.vx * s;
  o.y += o.vy * s;
  let hit = null;
  if (o.x < r && o.vx < 0) { o.x = r; o.vx = -o.vx * 0.6; hit = 'wall'; }
  if (o.x > W - r && o.vx > 0) { o.x = W - r; o.vx = -o.vx * 0.6; hit = 'wall'; }
  if (o.y < r && o.vy < 0) { o.y = r; o.vy = -o.vy * 0.5; }
  if (o.y > FLOOR() - r && o.vy > 0) {
    o.y = FLOOR() - r;
    if (o.vy > 25 * k) {
      o.vy = -o.vy * bounce;
      o.vx *= keep;
      hit = 'floor';
    } else {
      o.vy = 0;
      o.vx *= Math.exp(-2.2 * s); // rolling to a stop
      hit = hit || 'rolling';
    }
  }
  return hit;
}

// Where the ball will first come down to the floor, and how soon: what the pet runs for.
function landing() {
  const o = { x: ball.x, y: ball.y, vx: ball.vx, vy: ball.vy };
  const r = R();
  for (let t = 0; t < 3; t += 1 / 120) {
    o.vy += G() / 120;
    o.x += o.vx / 120;
    o.y += o.vy / 120;
    if (o.x < r || o.x > W - r) { o.x = clamp(o.x, r, W - r); o.vx = -o.vx * 0.6; }
    if (o.y >= FLOOR() - r && o.vy > 0) return { x: o.x, t };
  }
  return { x: o.x, t: 3 };
}

let last = performance.now();
let hitKey = '';
let sentAt = 0;

function frame(now) {
  requestAnimationFrame(frame);
  const s = Math.min(0.05, (now - last) / 1000);
  last = now;

  if (ball.state === 'flying') {
    const n = Math.ceil(s * 240);
    for (let i = 0; i < n; i++) {
      const hit = step(ball, s / n, R(), 0.55, 0.85);
      if (hit === 'wall') ball.bounces++;
      if (hit === 'floor' && Math.abs(ball.vy) > 60 * k) puff(ball.x, FLOOR(), 3);
    }
    ball.spin += ball.vx * s / (R() * 2);
    if (ball.y >= FLOOR() - R() - 0.5 && Math.abs(ball.vx) < 6 * k && ball.vy === 0) {
      ball.state = 'rest';
      ball.restAt = now;
    }
  } else if (ball.state === 'carried' && pet) {
    ball.x = pet.mouth.x;
    ball.y = pet.mouth.y;
  }

  for (const b of bits) {
    b.age += s;
    const n = Math.ceil(s * 240);
    for (let i = 0; i < n; i++) {
      const hit = step(b, s / n, Math.max(b.w, b.h) * k / 2, b.bounce, b.keep);
      if (hit === 'floor') puff(b.x, FLOOR(), b.kind === 'stone' ? 2 : 3);
    }
  }
  for (let i = bits.length - 1; i >= 0; i--) if (bits[i].age > bits[i].life) bits.splice(i, 1);
  for (const p of puffs) p.age += s;
  for (let i = puffs.length - 1; i >= 0; i--) if (puffs[i].age > 0.5) puffs.splice(i, 1);

  // tell the pet where the ball is, about 30 times a second
  if (game && ball.state !== 'gone' && now - sentAt > 33) {
    sentAt = now;
    const land = ball.state === 'flying' ? landing() : { x: ball.x, t: 0 };
    emit('play:ball', {
      state: ball.state, x: ball.x + origin.x, y: ball.y + origin.y, vx: ball.vx, vy: ball.vy,
      landX: land.x + origin.x, landT: land.t, airborne: ball.y < FLOOR() - R() - k, bounces: ball.bounces,
      restFor: ball.state === 'rest' ? now - ball.restAt : 0, held: !!grip,
    });
  }

  draw(now);
  // only the ball takes clicks; with no ball, nothing does
  const r = ball.state === 'gone' ? null : R() + 16;
  const key = r ? `${Math.round(ball.x / 4)},${Math.round(ball.y / 4)}` : 'none';
  if (invoke && key !== hitKey) {
    hitKey = key;
    const rect = r ? { x: ball.x - r, y: ball.y - r, width: 2 * r, height: 2 * r } : { x: -10, y: -10, width: 1, height: 1 };
    invoke('set_hit_region', rect).catch(() => {});
  }
}

function puff(x, y, n) {
  for (let i = 0; i < n; i++) puffs.push({ x: x + rand(-1, 1) * k, y, vx: rand(-14, 14) * k, vy: -rand(4, 12) * k, age: 0 });
}

// ---- drawing ----------------------------------------------------------------------

// A 7 by 7 ball in half-unit cells, lit from the top left.
const BALL = ['..###..', '.#####.', '#######', '#######', '#######', '.#####.', '..###..'];

function drawBall(x, y, now) {
  const cell = Math.max(3, Math.round((2 * R()) / 7));
  const p = new Painter(ctx, cell, Math.round(x - 3.5 * cell), Math.round(y - 3.5 * cell));
  const seam = ((Math.floor(ball.spin * 2) % 4) + 4) % 4;
  BALL.forEach((row, j) => [...row].forEach((c, i) => {
    if (c !== '#') return;
    const lit = i + j < 4;
    const dark = i + j > 8;
    let color = lit ? '#F2FF9C' : dark ? '#A9B83A' : '#D7E650';
    // the white seam rolls round as it spins
    if ((i === seam + 1 && j > 0 && j < 6) || (i === 5 - seam && j > 0 && j < 6 && seam % 2)) color = '#FAFBEF';
    p.rect(i, j, 1, 1, color);
  }));
  // its shadow on the floor, smaller the higher it flies
  const up = FLOOR() - y; // how high it flies
  if (up < 80 * k) {
    const w = Math.max(2, 7 - up / (12 * k)) * cell;
    ctx.globalAlpha = Math.max(0.08, 0.35 - up / (230 * k));
    ctx.fillStyle = '#000';
    ctx.fillRect(Math.round(x - w / 2), FLOOR() - cell, Math.round(w), cell);
    ctx.globalAlpha = 1;
  }
}

function pill(text, cx, y, color = '#F4EFE6', alpha = 1) {
  const fpx = Math.max(2, Math.round(k / 3.5));
  const w = textWidth(text) + 6;
  const p = new Painter(ctx, fpx, Math.round(cx - (w * fpx) / 2), Math.round(y));
  p.rect(1, 0, w - 2, 9, '#1C1B1A', 0.88 * alpha);
  p.rect(0, 1, w, 7, '#1C1B1A', 0.88 * alpha);
  drawText(p, text, 3, 2, color, alpha);
}

function draw(now) {
  ctx.clearRect(0, 0, W, H);
  for (const p of puffs) {
    ctx.globalAlpha = 0.5 * (1 - p.age / 0.5);
    ctx.fillStyle = '#CFC7BC';
    const c = Math.max(2, Math.round(k / 2));
    ctx.fillRect(Math.round(p.x + p.vx * p.age), Math.round(p.y + p.vy * p.age - c), c, c);
  }
  ctx.globalAlpha = 1;
  for (const b of bits) {
    const fade = Math.min(1, (b.life - b.age) / 0.6);
    ctx.globalAlpha = fade;
    ctx.fillStyle = b.color;
    const w = Math.round(b.w * k), h = Math.round(b.h * k);
    ctx.fillRect(Math.round(b.x - w / 2), Math.round(b.y - h / 2), w, h);
    if (b.kind === 'ball') {
      ctx.fillStyle = '#FFB2A6';
      ctx.fillRect(Math.round(b.x - w / 2), Math.round(b.y - h / 2), Math.round(w / 3), Math.round(h / 3));
    }
  }
  ctx.globalAlpha = 1;
  if (ball.state !== 'gone') drawBall(ball.x, ball.y, now);

  if (game) {
    pill(`FETCH ${score}   BEST ${best}`, W / 2, Math.round(2 * k));
    if (banner) {
      const age = (now - banner.at) / 1000;
      if (age > 1.4) banner = null;
      else pill(banner.text, ball.x, ball.y - R() - 5 * k - age * 6 * k, banner.color, Math.min(1, 2 - age * 1.2));
    }
    if (hint && now < hint.until && ball.state !== 'held') pill(hint.text, clamp(ball.x, 30 * k, W - 30 * k), ball.y - R() - 5 * k);
  }
}

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const rand = (a, b) => a + Math.random() * (b - a);
const pick = (xs) => xs[Math.floor(Math.random() * xs.length)];

requestAnimationFrame(frame);
listening.push(T?.event.listen('play:hello', () => emit('play:ready', {})));
// ready only once every listener is in: a start sent before that would be lost
Promise.all(listening).then(() => emit('play:ready', {}));
