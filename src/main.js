import { STAGE, SPRITE, STAND_Y, GROUND, COLORS, CLAUDE, Painter, spinnerFrame } from './sprite.js';
import { drawText, textWidth, fit } from './font.js';
import { Brain } from './brain.js';
import { World } from './world.js';
import { VoicePet } from './voice-pet.js';

const UNIT = { small: 4, medium: 5, large: 7 };
const T = window.__TAURI__;
const win = T?.window.getCurrentWindow();
const invoke = T ? (cmd, args) => T.core.invoke(cmd, args) : null;

if (invoke) {
  const report = (msg) => invoke('log', { message: String(msg) }).catch(() => {});
  window.addEventListener('error', (e) => report(`${e.message} at ${e.filename}:${e.lineno}`));
  window.addEventListener('unhandledrejection', (e) => report(e.reason?.stack ?? e.reason));
}

const canvas = document.getElementById('stage');
const ctx = canvas.getContext('2d');
const world = new World(invoke);
const brain = new Brain(world);
const voice = new VoicePet(brain, invoke);
let config = { size: 'medium', color: 'pink', sleepAfterMins: 5, roam: true, notify: true, label: true };
let painter;
let unit = UNIT.medium;
let dpr = 0;
// Which way the pet's feet point. On the side walls the window turns portrait, and the
// stage is drawn through a rotation so every scene works on every edge.
let orient = 'bottom';
const portrait = () => orient === 'left' || orient === 'right';

function layout() {
  unit = UNIT[config.size] ?? UNIT.medium;
  dpr = window.devicePixelRatio || 1;
  const px = Math.max(1, Math.round(unit * dpr));
  canvas.width = (portrait() ? STAGE.h : STAGE.w) * px;
  canvas.height = (portrait() ? STAGE.w : STAGE.h) * px;
  canvas.style.width = `${canvas.width / dpr}px`;
  canvas.style.height = `${canvas.height / dpr}px`;
  painter = new Painter(ctx, px);
  hitKey = '';
}

function stageTransform() {
  const W = STAGE.w * painter.px;
  const H = STAGE.h * painter.px;
  if (orient === 'top') ctx.setTransform(-1, 0, 0, -1, W, H);
  else if (orient === 'left') ctx.setTransform(0, 1, -1, 0, H, 0);
  else if (orient === 'right') ctx.setTransform(0, -1, 1, 0, 0, W);
  else ctx.setTransform(1, 0, 0, 1, 0, 0);
}

function fitWindow() {
  const [w, h] = portrait() ? [STAGE.h, STAGE.w] : [STAGE.w, STAGE.h];
  return invoke?.('fit_window', { width: w * unit, height: h * unit });
}

world.onOrient = (edge) => {
  orient = edge;
  layout();
  fitWindow()?.catch(() => {});
};

async function applyConfig(next) {
  config = { ...config, ...next };
  brain.color = COLORS[config.color] ?? COLORS.pink;
  brain.sleepAfter = Math.max(1, config.sleepAfterMins) * 60e3;
  brain.notifyEnabled = config.notify;
  world.enabled = config.roam;
  if (!config.roam) world.stop();
  layout();
  if (invoke) {
    await fitWindow();
    await world.refresh();
    world.watch();
  }
}

// ---- status pill ---------------------------------------------------------

const ICONS = {
  bang: { rows: ['..#..', '..#..', '..#..', '.....', '..#..'], color: '#FF6B6B' },
  check: { rows: ['.....', '....#', '...#.', '#.#..', '.#...'], color: '#5BD27A' },
  dots: { rows: ['.....', '.....', '.....', '.....', '#.#.#'], color: '#F4EFE6' },
};

function drawLabel(now) {
  const label = config.label && (voice.label() ?? brain.label());
  if (!label) return null;
  const tpx = Math.max(1, Math.round(painter.px / 2.5));
  const p = painter.child(tpx, 0, 0);
  const perUnit = painter.px / tpx;
  const stageW = Math.floor(STAGE.w * perUnit);
  const iconW = label.icon ? 7 : 0;
  const text = fit(label.text, stageW - 8 - iconW);
  const room = stageW - 8 - iconW - textWidth(text);
  const dim = label.dim && room > 14 ? fit(`  ${label.dim}`, room) : '';
  const w = 5 + iconW + textWidth(text) + (dim ? textWidth(dim) : 0);
  const h = 9;
  const cx = (brain.x + SPRITE.w / 2) * perUnit;
  const x = Math.round(Math.max(1, Math.min(stageW - w - 1, cx - w / 2)));
  const y = 1;
  p.rect(x + 1, y, w - 2, h, '#1C1B1A', 0.9);
  p.rect(x, y + 1, w, h - 2, '#1C1B1A', 0.9);
  let tx = x + 3;
  if (label.icon === 'spin') p.bitmap(spinnerFrame(Math.floor(now / 110)), tx, y + 2, CLAUDE);
  else if (label.icon) p.bitmap(ICONS[label.icon].rows, tx, y + 2, ICONS[label.icon].color);
  tx += iconW;
  drawText(p, text, tx, y + 2, '#F4EFE6');
  if (dim) drawText(p, dim, tx + textWidth(text), y + 2, '#9C968C');
  return text + dim;
}

// ---- render loop ---------------------------------------------------------

let last = performance.now();
let status = '';
function frame(now) {
  requestAnimationFrame(frame);
  // 25 fps while things move, half that when the pet is just breathing or asleep.
  const calm = (brain.view === 'idle' || brain.view === 'sleeping') && !brain.walking && !brain.act && !brain.particles.length && !voice.visible;
  if (now - last < (calm ? 80 : 40)) return;
  const dt = Math.min(now - last, 120);
  last = now;
  if ((window.devicePixelRatio || 1) !== dpr) layout();
  if (!brain.dragging) world.tick(dt);
  brain.update(now, dt);
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  painter.clear();
  stageTransform();
  brain.draw(painter); // the voice orb draws itself on its own canvas, see voice-pet.js
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  // The status line only reads well upright and in view, so it rests while the pet is
  // on another edge or tucked away.
  const upright = orient === 'bottom' && !(world.rim && world.rim.tuck > 0.3);
  const shown = (upright && drawLabel(now)) || '';
  updateHitRegion();
  if (shown !== status && invoke) {
    status = shown;
    invoke('set_status', { text: shown ? `Claude Bot: ${shown}` : 'Claude Bot' }).catch(() => {});
  }
}

// Only the pet itself catches the mouse; the rest of the window lets clicks through.
let hitKey = '';
function updateHitRegion() {
  if (!invoke) return;
  const r = {
    x: (brain.x - 1) * unit,
    y: (STAND_Y - 6) * unit,
    width: (SPRITE.w + 2) * unit,
    height: (GROUND - STAND_Y + 7) * unit,
  };
  const mic = voice.rect(); // the mic button and the orb sit above the head
  if (mic && mic.y * unit < r.y) {
    r.height += r.y - mic.y * unit;
    r.y = mic.y * unit;
  }
  const hit = toWindowRect(r);
  const key = `${orient}:${hit.x},${hit.y},${hit.width},${hit.height}`;
  if (key === hitKey) return;
  hitKey = key;
  invoke('set_hit_region', hit).catch(() => {});
}

// A rectangle on the stage (CSS px) as it lands in the rotated window.
function toWindowRect(r) {
  const W = STAGE.w * unit;
  const H = STAGE.h * unit;
  if (orient === 'top') return { x: W - r.x - r.width, y: H - r.y - r.height, width: r.width, height: r.height };
  if (orient === 'left') return { x: H - r.y - r.height, y: r.x, width: r.height, height: r.width };
  if (orient === 'right') return { x: r.y, y: W - r.x - r.width, width: r.height, height: r.width };
  return r;
}

// ---- input ---------------------------------------------------------------
// Press and move to carry the pet around, click to poke it, right-click for the menu.

let press = null;
let dragAt = 0;

// Pointer position in stage units, undoing the window's rotation.
function toUnits(e) {
  const [x, y] = [e.offsetX, e.offsetY];
  const W = STAGE.w * unit;
  const H = STAGE.h * unit;
  if (orient === 'top') return { x: (W - x) / unit, y: (H - y) / unit };
  if (orient === 'left') return { x: y / unit, y: (H - x) / unit };
  if (orient === 'right') return { x: (W - y) / unit, y: x / unit };
  return { x: x / unit, y: y / unit };
}

function endDrag() {
  if (brain.dragging && performance.now() - dragAt > 200) brain.dragEnd();
}

// Wayland compositors never tell the window that a move has finished, and the
// pointer can leave without crossing the pet again. So while dragging, compare the
// cursor with the window: the cursor moving on its own means the pet was dropped.
let dragProbe = null;
setInterval(async () => {
  if (!invoke || !brain.dragging || performance.now() - dragAt < 300) {
    dragProbe = null;
    return;
  }
  const [state, cursor] = await Promise.all([invoke('world').catch(() => null), invoke('cursor').catch(() => null)]);
  const pos = state?.window;
  if (!pos || !cursor) {
    if (performance.now() - dragAt > 8000) brain.dragEnd();
    return;
  }
  if (dragProbe) {
    const cursorMoved = Math.hypot(cursor.x - dragProbe.cursor.x, cursor.y - dragProbe.cursor.y) > 6;
    const windowMoved = Math.hypot(pos.x - dragProbe.pos.x, pos.y - dragProbe.pos.y) > 1;
    if (cursorMoved && !windowMoved) {
      dragProbe = null;
      brain.dragEnd();
      return;
    }
  }
  dragProbe = { cursor, pos };
}, 150);

canvas.addEventListener('pointerdown', (e) => {
  if (e.button !== 0) return;
  press = { x: e.screenX, y: e.screenY };
});

canvas.addEventListener('pointermove', (e) => {
  // The OS swallows pointer events while it moves the window, so the first event
  // after a drag means the pet has been put down.
  endDrag();
  brain.pointer = toUnits(e);
  voice.hover(brain.pointer);
  if (!press || Math.hypot(e.screenX - press.x, e.screenY - press.y) < 4) return;
  press = null;
  brain.dragStart();
  dragAt = performance.now();
  if (win) {
    win.startDragging().then(() => {
      // Windows and macOS resolve once the drag finishes; Linux resolves right away.
      if (performance.now() - dragAt > 300) brain.dragEnd();
    });
  }
});

canvas.addEventListener('pointerup', (e) => {
  if (brain.dragging) brain.dragEnd();
  else if (press && !voice.press(toUnits(e))) brain.poke();
  press = null;
});

canvas.addEventListener('pointerleave', () => {
  endDrag();
  brain.pointer = null;
  voice.leave();
  press = null;
});

canvas.addEventListener('contextmenu', (e) => {
  e.preventDefault();
  invoke?.('show_menu', { x: e.offsetX, y: e.offsetY });
});

// Number keys preview scenes while the pet has focus (handy in a plain browser too).
const KEYS = ['idle', 'thinking', 'building', 'typing', 'searching', 'alert', 'done', 'compacting', 'sleeping', 'celebrate'];
window.addEventListener('keydown', (e) => {
  const i = '1234567890'.indexOf(e.key);
  if (i >= 0) brain.play(KEYS[i]);
  if (e.key === 'a') brain.play('agent');
  if (e.key === 'd') brain.play('dance');
  if (e.key === 'z') brain.play('zoomies');
});

// ---- boot ----------------------------------------------------------------

async function boot() {
  if (T) {
    brain.onNotify = (title, body) => invoke('notify', { title, body }).catch(() => {});
    await T.event.listen('hook', (e) => brain.onHook(e.payload));
    await T.event.listen('play', (e) => brain.play(e.payload));
    await T.event.listen('config', (e) => applyConfig(e.payload));
    await applyConfig(await invoke('get_config'));
    voice.start();
    setInterval(() => world.refresh(), 4000);
    setInterval(() => world.pollCursor(), 150);
    // Keep the pet on whatever it stands on: windows that move carry it, windows that go drop it.
    setInterval(async () => {
      await world.pollSurfaces();
      if (!brain.dragging) world.watch();
    }, 500);
  } else {
    await applyConfig({});
    window.brain = brain;
  }
  brain.update(performance.now(), 0);
  painter.clear();
  brain.draw(painter);
  requestAnimationFrame(frame);
  if (win) {
    await win.show();
    // The window only has a position once it's mapped; drop it onto the floor then.
    setTimeout(async () => {
      await world.refresh();
      world.watch();
    }, 400);
  }
}

boot();
