import { STAGE, SPRITE, STAND_Y, HOME_X, GLYPHS, WHITE } from './sprite.js';
import { VIEWS, THINK_VIEWS } from './views.js';
import { Crew } from './crew.js';
import { randomVerb, styleFor } from './verbs.js';

const MIN_X = 1;
const MAX_X = STAGE.w - SPRITE.w - 1;

// Moods follow Claude Code. Overlays are one-shot reactions played on top of the mood.
export const MOODS = [
  'idle', 'thinking', 'building', 'testing', 'typing', 'reading', 'searching', 'surfing',
  'planning', 'delegating', 'alert', 'waiting', 'done', 'compacting', 'error', 'sleeping',
];
const BUSY = new Set(['thinking', 'building', 'testing', 'typing', 'reading', 'searching', 'surfing', 'planning', 'delegating', 'compacting']);
// Claude Code sends nothing when a turn dies quietly, so every mood expires on its own.
const STALE = { thinking: 180e3, compacting: 300e3, alert: 900e3, waiting: 300e3, done: 600e3, error: 7e3 };
const TOOL_STALE = 600e3;
const OVERLAY_MS = {
  hello: 1600, celebrate: 2600, poke: 650, giggle: 800, land: 450, wake: 1300, yawn: 1700,
  dizzy: 2200, notice: 700, shrug: 1600, oops: 1100, remind: 1500,
};
const ACT_MS = { look: 2600, walk: 0, zoomies: 0, chase: 0, fly: 3200, explore: 0, hop: 700, wave: 1500, sit: 5000, dance: 3200, yawn: 1700, stretch: 1400, trip: 2400, sneeze: 1500 };
// Acts that move the pet; they end on arrival instead of after a fixed time.
const WALKING_ACTS = new Set(['walk', 'zoomies', 'chase', 'fly']);
// Screen-edge commands: hide, peek, peek:<edge>, edge:<edge>, corner:<top|bottom>-<left|right>, home.
export const EDGE_COMMAND = /^(hide|peek|home)$|^(peek|edge):(top|right|bottom|left)$|^corner:(top|bottom)-(left|right)$/;
// A turn shorter than this just gets confetti; longer ones hold up the "done" sign.
const REMIND_AFTER = 10e3;
const NOTIFY_AFTER = 20e3;
// The status line should read calmly: a spinner verb lasts the whole turn (or 3 minutes
// of a long one), and any other text stays up at least 4 seconds so bursts of tool calls
// don't flicker it. Anything that needs me (a "!" or a check mark) shows at once.
const VERB_ROTATE = 180e3;
const LABEL_HOLD = 4000;

// Labels shown while previewing a scene from the menu.
const DEMO = {
  building: 'Running cargo build', testing: 'Running npm test', typing: 'Editing main.rs',
  reading: 'Reading README.md', searching: 'Searching "TODO"', surfing: 'Browsing docs.rs',
  planning: 'Planning', delegating: 'Delegating: explore the repo', alert: 'Needs your OK',
  done: 'Done in 2m 14s', error: 'API error',
};

const rand = (a, b) => a + Math.random() * (b - a);
const pick = (xs) => xs[Math.floor(Math.random() * xs.length)];
const clampX = (x) => Math.max(MIN_X, Math.min(MAX_X, x));
const base = (path = '') => path.split(/[\\/]/).filter(Boolean).pop() ?? '';

function weighted(options) {
  const total = options.reduce((s, [, w]) => s + w, 0);
  let r = Math.random() * total;
  for (const [name, w] of options) if ((r -= w) < 0) return name;
  return options[0][0];
}

export function toolMood(tool = '', input = {}) {
  if (/^(Bash|PowerShell)$/.test(tool)) {
    return /\b(test|tests|pytest|jest|vitest|mocha|rspec|phpunit|ctest)\b/.test(input.command ?? '') ? 'testing' : 'building';
  }
  if (/^(Edit|Write|MultiEdit|NotebookEdit)$/.test(tool)) return 'typing';
  if (/^(Read|NotebookRead)$/.test(tool)) return 'reading';
  if (/^(Grep|Glob|LS|ToolSearch)$/.test(tool)) return 'searching';
  if (/^(WebFetch|WebSearch)$/.test(tool)) return 'surfing';
  if (/^(TodoWrite|TaskCreate|TaskUpdate)$/.test(tool)) return 'planning';
  if (/^(Task|Agent)$/.test(tool)) return 'delegating';
  if (/^(AskUserQuestion|ExitPlanMode)$/.test(tool)) return 'alert';
  return 'building';
}

export function describe(tool = '', input = {}) {
  const cmd = (input.command ?? '').split('\n')[0].replace(/\s+/g, ' ').trim();
  let host = '';
  try {
    host = new URL(input.url).hostname.replace(/^www\./, '');
  } catch {}
  switch (tool) {
    case 'Bash':
    case 'PowerShell': return `Running ${cmd}`;
    case 'Edit':
    case 'MultiEdit':
    case 'NotebookEdit': return `Editing ${base(input.file)}`;
    case 'Write': return `Writing ${base(input.file)}`;
    case 'Read':
    case 'NotebookRead': return `Reading ${base(input.file)}`;
    case 'Grep': return `Searching "${input.pattern ?? ''}"`;
    case 'Glob': return `Finding ${input.pattern ?? 'files'}`;
    case 'LS': return 'Looking around';
    case 'WebFetch': return `Browsing ${host || 'the web'}`;
    case 'WebSearch': return `Searching "${input.query ?? ''}"`;
    case 'TodoWrite':
    case 'TaskCreate':
    case 'TaskUpdate': return 'Planning';
    case 'Task':
    case 'Agent': return `Delegating: ${input.description || input.subagentType || 'a task'}`;
    case 'AskUserQuestion': return 'Has a question';
    case 'ExitPlanMode': return 'Plan ready';
  }
  // mcp__plugin_pc_pc__hover -> "pc: hover", mcp__claude_ai_Notion__search -> "Notion: search"
  const [, server, name] = tool.split('__');
  if (tool.startsWith('mcp__') && name) {
    const short = server.replace(/^claude_ai_/, '').replace(/^plugin_[^_]+_/, '');
    const action = name.toLowerCase().startsWith(`${short.toLowerCase()}-`) ? name.slice(short.length + 1) : name;
    return `${short}: ${action.replace(/[-_]/g, ' ')}`;
  }
  return `Using ${tool}`;
}

export function duration(ms) {
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return m < 60 ? `${m}m ${s % 60}s` : `${Math.floor(m / 60)}h ${m % 60}m`;
}

export class Brain {
  constructor(world = null) {
    this.world = world;
    this.color = '#D78787';
    this.sleepAfter = 5 * 60e3;
    this.notifyEnabled = true;
    this.onNotify = null;
    this.now = 0;

    this.mood = 'idle';
    this.moodAt = 0;
    this.pendingMood = null;
    this.demoUntil = 0;
    this.overlay = null;
    this.overlayAt = 0;
    this.overlayThen = null;

    this.sessions = new Map();
    this.focus = null;
    this.crew = new Crew();
    this.verb = 'Thinking';
    this.style = 'bubble';
    this.toastText = '';
    this.toastUntil = 0;
    this.remindAt = 0;

    this.lastEvent = 0;
    this.lastActive = 0;

    this.x = HOME_X;
    this.targetX = HOME_X;
    this.stepAt = 0;
    this.stepMs = 110;
    this.steps = 0;

    this.blinkAt = 2000;
    this.blinkUntil = 0;
    this.act = null;
    this.nextActAt = 3000;
    this.nextPaceAt = 0;
    this.emitAt = 0;
    this.near = false;
    this.noticeAt = 0;
    this.sneezed = false;

    this.pointer = null;
    this.stageRim = null;
    this.dragging = false;
    this.pokes = [];
    this.particles = [];

    this.swing = -1;
    this.hits = 0;
    this.bricks = 0;

    if (world) world.onLand = () => this.landed();
  }

  get canRoam() {
    return !!this.world?.canRoam;
  }

  get walking() {
    return this.x !== this.targetX || !!this.world?.moving;
  }

  get walkDir() {
    return this.world?.moving ? this.world.dir : Math.sign(this.targetX - this.x);
  }

  get view() {
    if (this.dragging) return 'dragged';
    if (this.world?.falling) return 'falling';
    if (this.world?.flying) return 'flying';
    if (this.world?.clinging && !this.overlay) return 'clinging';
    const rim = this.world?.rim;
    if ((rim && rim.mode !== 'sit' && !rim.route.length) || this.stageRim) return 'peeking';
    return this.overlay ?? this.mood;
  }

  // ---- Claude Code events ----------------------------------------------

  session(h) {
    const id = h.session || 'default';
    let s = this.sessions.get(id);
    if (!s) {
      s = { id, mood: 'idle', at: this.now, turnAt: 0, project: '', detail: '', message: '', verb: 'Thinking', style: 'bubble', verbAt: 0 };
      this.sessions.set(id, s);
    }
    if (h.cwd) s.project = base(h.cwd);
    if (h.title) s.title = h.title;
    s.last = this.now;
    return s;
  }

  setSession(s, mood) {
    s.mood = mood;
    s.at = this.now;
  }

  pickVerb(s, style) {
    s.verb = randomVerb(style);
    s.style = styleFor(s.verb);
    s.verbAt = this.now;
  }

  onHook(h) {
    const now = this.now;
    this.lastEvent = this.lastActive = now;
    this.demoUntil = 0;
    const input = h.input ?? {};

    // Tool calls made inside a subagent drive that agent's mini Clawd, not the pet.
    if (h.agent && h.event !== 'SubagentStart' && h.event !== 'SubagentStop') {
      if (h.event === 'PreToolUse') this.crew.event(h, toolMood(h.tool, input), now);
      else if (h.event === 'PostToolUse' || h.event === 'PostToolUseFailure') this.crew.event(h, 'thinking', now);
      else this.crew.event(h, null, now);
      return;
    }

    const s = this.session(h);
    switch (h.event) {
      case 'SessionStart':
        if (h.source === 'compact') {
          this.setSession(s, 'thinking');
        } else {
          this.setSession(s, 'idle');
          this.flash('hello');
        }
        break;
      case 'UserPromptSubmit':
        s.turnAt = now;
        this.bricks = this.hits = 0;
        this.pickVerb(s);
        this.setSession(s, 'thinking');
        break;
      case 'PreToolUse': {
        const mood = toolMood(h.tool, input);
        s.detail = describe(h.tool, input);
        if (mood === 'alert') s.message = s.detail;
        this.setSession(s, mood);
        break;
      }
      case 'PostToolUse':
        this.setSession(s, 'thinking');
        break;
      case 'PostToolUseFailure':
        if (h.interrupt) {
          s.turnAt = 0;
          this.setSession(s, 'idle');
          this.flash('shrug');
        } else {
          this.setSession(s, 'thinking');
          this.flash('oops');
        }
        break;
      case 'PermissionRequest':
        s.message = 'Needs your OK';
        this.setSession(s, 'alert');
        break;
      case 'Notification':
        if (h.kind === 'idle_prompt') {
          if (s.mood === 'done') this.remind();
          else this.setSession(s, 'waiting');
        } else if (h.kind !== 'auth_success') {
          s.message = h.kind === 'permission_prompt' ? 'Needs your OK' : 'Needs you';
          this.setSession(s, 'alert');
          this.ping('Claude needs you', [s.project, h.message || s.message].filter(Boolean).join(': '));
        }
        break;
      case 'Stop':
        this.finishTurn(s);
        break;
      case 'StopFailure':
        s.turnAt = 0;
        s.detail = 'API error';
        this.setSession(s, 'error');
        break;
      case 'PreCompact':
        this.setSession(s, 'compacting');
        break;
      case 'PostCompact':
        this.setSession(s, s.turnAt ? 'thinking' : 'idle');
        break;
      case 'SubagentStart':
        this.crew.spawn(h.agent, s.id, h.agentType, now);
        break;
      case 'SubagentStop': {
        const a = this.crew.finish(h.agent, s.id, now);
        if (a) this.toast(`${a.type} finished`);
        break;
      }
      case 'SessionEnd':
        this.sessions.delete(s.id);
        this.crew.dropSession(s.id);
        if (this.sessions.size === 0) {
          this.recompute();
          this.flash('yawn', () => this.setMood('sleeping'));
          return;
        }
        break;
    }
    this.recompute();
  }

  finishTurn(s) {
    const took = s.turnAt ? this.now - s.turnAt : 0;
    s.turnAt = 0;
    this.flash('celebrate');
    if (took < REMIND_AFTER) {
      this.setSession(s, 'idle');
      return;
    }
    s.detail = `Done in ${duration(took)}`;
    this.setSession(s, 'done');
    this.remindAt = this.now + 45e3;
    if (took >= NOTIFY_AFTER) this.ping('Claude is done', [s.project, `finished in ${duration(took)}`].filter(Boolean).join(': '));
  }

  // The pet follows the session that needs attention most: waiting on you beats
  // working, working beats finished.
  recompute() {
    const list = [...this.sessions.values()];
    const newest = (mood) => list.filter(mood).sort((a, b) => b.at - a.at)[0];
    // Stay with the session already on show while it keeps working, so two busy sessions
    // don't trade the pet back and forth on every tool call.
    const current = this.focus && this.sessions.get(this.focus.id) === this.focus && BUSY.has(this.focus.mood) ? this.focus : null;
    const s = list.find((x) => x.mood === 'alert')
      ?? current
      ?? newest((x) => BUSY.has(x.mood))
      ?? newest((x) => x.mood === 'error')
      ?? newest((x) => x.mood === 'done')
      ?? newest((x) => x.mood === 'waiting');
    this.focus = s ?? null;
    if (s) {
      this.verb = s.verb;
      this.style = s.style;
    }
    const mood = s ? s.mood : 'idle';
    if (mood === 'idle' && this.mood === 'sleeping') return;
    this.setMood(mood);
  }

  ping(title, body) {
    if (this.notifyEnabled) this.onNotify?.(title, body);
  }

  toast(text) {
    this.toastText = text;
    this.toastUntil = this.now + 2600;
  }

  remind() {
    this.remindAt = this.now + 45e3;
    if (this.overlay || this.dragging) return;
    this.flash('remind');
    const c = this.world?.cursor;
    if (this.canRoam && this.world.sameMonitor(c)) this.world.walkTo(c.x, 16);
  }

  // ---- menu previews ---------------------------------------------------

  play(name) {
    this.lastActive = this.now;
    if (EDGE_COMMAND.test(name)) {
      this.overlay = null;
      this.act = null;
      if (this.mood === 'sleeping') this.setMood('idle', true);
      // Where the window can't move, hide and peek happen inside the stage instead.
      if (!this.world?.command(name)) this.stageCommand(name);
      return;
    }
    if (name.startsWith('think:')) {
      const style = name.slice(6);
      this.verb = randomVerb(style);
      this.style = THINK_VIEWS[style] ? style : 'bubble';
      this.setMood('thinking', true);
      this.moodAt = this.now;
      this.demoUntil = this.now + 10000;
    } else if (name === 'agent') {
      const id = `demo-${Math.round(this.now)}`;
      const a = this.crew.spawn(id, 'demo', pick(['Explore', 'Plan', 'general-purpose']), this.now);
      const moods = ['searching', 'reading', 'building', 'typing'];
      moods.forEach((m, i) => setTimeout(() => this.crew.event({ agent: id, session: 'demo' }, m, this.now), 1500 + i * 1800));
      setTimeout(() => this.crew.finish(id, 'demo', this.now) && this.toast(`${a.type} finished`), 9000);
    } else if (MOODS.includes(name)) {
      this.setMood(name, true);
      this.demoUntil = name === 'idle' || name === 'sleeping' ? 0 : this.now + 8000;
    } else if (name in OVERLAY_MS) {
      this.flash(name);
    } else if (name in ACT_MS) {
      this.setMood('idle', true);
      this.overlay = null;
      this.startAct(name);
    }
  }

  // ---- interaction -----------------------------------------------------

  // Hide and peek inside the stage, for desktops that won't let the window move.
  stageCommand(name) {
    if (name === 'home') this.stageRim = null;
    else if (name === 'hide' || name === 'peek' || name.startsWith('peek:')) {
      this.stageRim = { mode: name === 'hide' ? 'hide' : 'peek', tuck: this.stageRim?.tuck ?? 0, out: false, flipAt: this.now + 700 };
    } else {
      this.toast("Can't move the window here");
    }
  }

  stageRimTick(now, dt) {
    const r = this.stageRim;
    if (!r) return;
    if (r.mode === 'peek' && now > r.flipAt) {
      r.out = !r.out;
      r.flipAt = now + (r.out ? rand(2200, 4200) : rand(1600, 4800));
    }
    const want = r.mode === 'hide' || !r.out ? 0.86 : 0.45;
    const ease = 1.4 * (dt / 1000);
    r.tuck += Math.max(-ease, Math.min(ease, want - r.tuck));
  }

  poke() {
    const now = this.now;
    this.lastActive = now;
    this.pokes = this.pokes.filter((t) => now - t < 2000);
    this.pokes.push(now);
    if (this.mood === 'sleeping') {
      this.setMood('idle');
      return;
    }
    // Poking a hidden pet coaxes it out.
    const rim = this.world?.rim;
    if ((rim && rim.mode !== 'sit') || this.stageRim) {
      if (rim) rim.mode = 'sit';
      this.stageRim = null;
      this.flash('hello');
      return;
    }
    // Poking the pet while it holds the "done" sign means "got it".
    if (this.mood === 'done' || this.mood === 'waiting') {
      for (const s of this.sessions.values()) if (s.mood === 'done' || s.mood === 'waiting') this.setSession(s, 'idle');
      this.recompute();
      this.flash('hello');
      return;
    }
    if (this.pokes.length >= 4) {
      this.pokes = [];
      this.flash('dizzy');
      return;
    }
    this.flash(pick(['poke', 'poke', 'giggle']));
    this.spawn({ kind: 'glyph', glyph: GLYPHS.heart, color: '#F06A7A', x: this.x + 14, y: STAND_Y - 3, vx: 2, vy: -6, life: 0.9 });
  }

  dragStart() {
    this.dragging = true;
    this.lastActive = this.now;
    this.overlay = null;
    this.act = null;
    this.world?.grab();
    if (this.mood === 'sleeping') this.mood = 'idle';
  }

  async dragEnd() {
    if (!this.dragging) return;
    this.dragging = false;
    this.lastActive = this.now;
    if (this.world) {
      await this.world.refresh();
      await this.world.pollSurfaces();
      // Snaps onto a nearby window top or edge, or falls; either way onLand fires.
      if (this.world.drop()) return;
    }
    this.landed();
  }

  landed() {
    this.flash('land');
    for (const dir of [-1, 1]) {
      this.spawn({ x: this.x + (dir < 0 ? 3 : 13), y: STAND_Y + 9, vx: dir * rand(8, 14), vy: -rand(2, 5), g: 20, life: 0.4, color: '#CFC7BC' });
    }
  }

  // ---- state -----------------------------------------------------------

  setMood(mood, force = false) {
    const now = this.now;
    if (mood === this.mood) {
      this.pendingMood = null;
      return;
    }
    const hold = this.mood === 'thinking' ? 600 : 1200;
    if (!force && BUSY.has(this.mood) && BUSY.has(mood) && now - this.moodAt < hold) {
      this.pendingMood = mood;
      return;
    }
    if (this.mood === 'sleeping' && !this.overlay) this.flash('wake');
    this.pendingMood = null;
    this.mood = mood;
    this.moodAt = now;
    this.act = null;
    this.swing = -1;
    this.world?.stop();
    // Work happens on solid ground: let go of an edge, or come down from a flight.
    if (mood !== 'idle' && mood !== 'sleeping') this.world?.letGo();
    this.targetX = mood === 'idle' || mood === 'sleeping' ? this.x : HOME_X;
  }

  flash(name, then = null) {
    this.overlay = name;
    this.overlayAt = this.now;
    this.overlayThen = then;
    this.act = null;
    if (name === 'celebrate') {
      const colors = ['#F6C945', '#6FD3A8', '#7DB7F5', '#F27D9B', '#B79CF2', '#FFFFFF'];
      for (let i = 0; i < 28; i++) {
        this.spawn({ x: this.x + rand(4, 13), y: STAND_Y - 2, vx: rand(-14, 14), vy: rand(-26, -10), g: 32, life: rand(1.3, 2.2), color: pick(colors) });
      }
    }
  }

  startAct(name) {
    const now = this.now;
    this.act = { name, at: now, until: now + ACT_MS[name] };
    this.sneezed = false;
    this.stepMs = name === 'zoomies' ? 45 : 110;
    if (!WALKING_ACTS.has(name)) {
      this.world?.stop();
      this.targetX = this.x;
    }
    if (name === 'walk') {
      if (!this.world?.wander(6, 8)) this.stageWalk(3);
    } else if (name === 'zoomies') {
      if (!this.world?.dash(45)) this.targetX = this.x < STAGE.w / 2 - SPRITE.w / 2 ? MAX_X : MIN_X;
    } else if (name === 'fly') {
      // Across the screen when the window can move; otherwise a hop-flight inside the stage.
      if (this.world?.fly()) this.act.until = now;
    } else if (name === 'explore') {
      this.world?.explore();
      this.act.until = now;
    } else if (name === 'chase') {
      const c = this.world?.cursor;
      if (!(this.canRoam && this.world.sameMonitor(c) && this.world.walkTo(c.x, 16))) this.act.until = now;
    }
  }

  stageWalk(minDist) {
    let tx = this.x;
    for (let i = 0; i < 10 && Math.abs(tx - this.x) < minDist; i++) tx = clampX(Math.round(rand(MIN_X, MAX_X)));
    this.targetX = tx;
  }

  spawn(pt) {
    this.particles.push({ kind: 'px', w: 1, h: 1, g: 0, age: 0, vx: 0, vy: 0, ...pt });
  }

  update(now, dt) {
    this.now = now;

    if (this.overlay && now - this.overlayAt > OVERLAY_MS[this.overlay]) {
      const then = this.overlayThen;
      this.overlay = null;
      this.overlayThen = null;
      then?.();
    }
    if (this.pendingMood && now - this.moodAt >= (this.mood === 'thinking' ? 600 : 1200)) this.setMood(this.pendingMood);
    if (this.demoUntil && now > this.demoUntil) {
      this.demoUntil = 0;
      this.recompute();
      if (this.mood !== 'idle' && !this.focus) this.setMood('idle', true);
    }

    let changed = false;
    for (const s of this.sessions.values()) {
      const limit = STALE[s.mood] ?? (BUSY.has(s.mood) ? TOOL_STALE : 0);
      if (limit && now - s.at > limit) {
        this.setSession(s, 'idle');
        changed = true;
      }
      if (s.mood === 'idle' && now - (s.last ?? 0) > 3 * 3600e3) this.sessions.delete(s.id);
    }
    if (changed && !this.demoUntil) this.recompute();

    // Rotate the spinner verb now and then, like a long Claude turn does.
    if (this.mood === 'thinking' && this.focus && !this.demoUntil && now - this.focus.verbAt > VERB_ROTATE) {
      this.pickVerb(this.focus);
      this.verb = this.focus.verb;
      this.style = this.focus.style;
      this.moodAt = now;
    }
    if (this.mood === 'done' && now > this.remindAt) this.remind();

    if (this.voice?.active) this.lastActive = now; // never nod off mid-conversation
    const restful = this.mood === 'idle' || this.mood === 'waiting';
    if (restful && !this.overlay && !this.dragging && now - this.lastActive > this.sleepAfter) {
      this.lastActive = now;
      this.world?.stop();
      this.flash('yawn', () => this.setMood('sleeping'));
    }

    if (now > this.blinkAt) {
      this.blinkUntil = now + 130;
      this.blinkAt = now + (Math.random() < 0.2 ? 260 : rand(1800, 5500));
    }

    this.noticeCursor(now);
    if (this.mood === 'idle' && !this.overlay && !this.dragging) this.idleTick(now);
    if (this.mood === 'thinking' && this.style === 'wander' && !this.walking && now > this.nextPaceAt) {
      this.stepMs = 140;
      if (!this.world?.wander(4, 6)) this.stageWalk(3);
      this.nextPaceAt = now + rand(800, 2500);
    }
    if (this.mood === 'searching' && !this.canRoam && !this.walking && now > this.nextPaceAt) {
      this.targetX = HOME_X + pick([-2, 0, 2]);
      this.nextPaceAt = now + rand(1500, 3200);
    }

    if (!this.dragging && this.x !== this.targetX && now >= this.stepAt) {
      this.stepAt = now + this.stepMs;
      this.x += Math.sign(this.targetX - this.x);
      this.steps++;
    }

    this.stageRimTick(now, dt);
    this.crew.update(now);
    this.emit(now);

    const s = dt / 1000;
    this.particles = this.particles.filter((pt) => {
      pt.age += s;
      pt.vy += pt.g * s;
      pt.x += pt.vx * s;
      pt.y += pt.vy * s;
      return pt.age < pt.life;
    });
  }

  // A little "!" when the cursor comes close after being away.
  noticeCursor(now) {
    const w = this.world;
    if (!w?.cursor || !w.win) return;
    const c = w.petCenter();
    const d = Math.hypot(w.cursor.x - c.x, w.cursor.y - c.y) / w.k;
    const near = d < 22;
    if (near && !this.near && this.mood === 'idle' && !this.overlay && !this.act && now > this.noticeAt) {
      this.flash('notice');
      this.noticeAt = now + 30e3;
    }
    this.near = near;
  }

  idleTick(now) {
    const a = this.act;
    const airborne = this.world?.flying || this.world?.falling;
    if (a && (WALKING_ACTS.has(a.name) ? !this.walking && !airborne && now > a.until : now > a.until)) {
      if (a.name === 'chase' && !a.sat && now - a.at > 300) {
        a.sat = true;
        a.until = now + 2600;
        return;
      }
      this.act = null;
      this.stepMs = 110;
      this.nextActAt = now + rand(2500, 8000);
    }
    const rim = this.world?.rim;
    if (this.act || now < this.nextActAt || this.world?.clinging || this.stageRim || rim?.mode === 'hide' || rim?.mode === 'peek') return;
    const lonely = now - this.lastActive > 60e3;
    const onFloor = this.canRoam && !rim;
    const cursorHere = onFloor && this.world.sameMonitor(this.world.cursor);
    this.startAct(weighted([
      ['look', 4], ['walk', 5], ['hop', 2], ['wave', 1], ['sit', 2], ['stretch', 1],
      ['dance', 0.6], ['zoomies', onFloor ? 0.8 : 0], ['chase', cursorHere ? 1.2 : 0],
      ['trip', rim ? 0 : 0.3], ['sneeze', 0.4], ['yawn', lonely ? 2 : 0], ['fly', onFloor ? 0.25 : 0],
      ['explore', onFloor ? 0.35 : 0],
    ]));
  }

  emit(now) {
    const view = this.view;
    const at = this.act ? now - this.act.at : 0;
    if (view === 'idle' && this.act?.name === 'sneeze' && at > 950 && !this.sneezed) {
      this.sneezed = true;
      for (let i = 0; i < 9; i++) {
        this.spawn({ x: this.x + 8, y: STAND_Y + 5, vx: rand(-18, 18), vy: rand(-12, 2), g: 30, life: rand(0.4, 0.8), color: '#DDF3FF' });
      }
    }
    if (now < this.emitAt) return;
    this.emitAt = now + 100;
    if (view === 'sleeping') {
      this.emitAt = now + 1400;
      const big = Math.random() < 0.5;
      this.spawn({ kind: 'glyph', glyph: big ? GLYPHS.Z : GLYPHS.z, color: WHITE, x: this.x + 16, y: STAND_Y - 3, vx: 1.6, vy: -2.4, wobble: 1, life: 3.2 });
    } else if (view === 'typing' && !this.walking) {
      this.emitAt = now + 230;
      this.spawn({ w: Math.round(rand(1, 4)), x: this.x + rand(4, 10), y: STAND_Y + 2, vy: -5, life: 0.9, color: pick(['#7FD6FF', '#A7F3A1', '#FFD479', '#F7A1D6']) });
    } else if ((view === 'idle' && this.act?.name === 'dance') || (view === 'thinking' && this.style === 'vibe')) {
      this.emitAt = now + 650;
      this.spawn({ kind: 'glyph', glyph: GLYPHS.note, color: pick(['#F6C945', '#7DB7F5', '#F27D9B']), x: this.x + pick([-3, 18]), y: STAND_Y + 1, vx: rand(-2, 2), vy: -4, life: 1.4 });
    } else if (view === 'idle' && this.act?.name === 'zoomies' && this.walking) {
      this.emitAt = now + 60;
      const behind = this.walkDir > 0 ? 2 : 14;
      this.spawn({ w: 2, x: this.x + behind, y: STAND_Y + 8, vx: -this.walkDir * rand(4, 10), vy: -rand(1, 4), life: 0.45, color: '#CFC7BC' });
    } else if (view === 'thinking' && this.style === 'wizard') {
      this.emitAt = now + 180;
      this.spawn({ x: this.x + 20 + rand(-2, 2), y: STAND_Y - 3, vx: rand(-3, 3), vy: rand(-5, -1), life: 0.8, color: pick(['#F6D35B', '#9FE2FF', '#F49AC2']) });
    }
  }

  hammerTick(t, pose) {
    const cycle = Math.floor(t / 700);
    const ph = t % 700;
    if (ph >= 460 && cycle !== this.swing) {
      this.swing = cycle;
      for (let i = 0; i < 5; i++) {
        this.spawn({ x: pose.x + 20, y: pose.y + 8, vx: rand(-6, 12), vy: rand(-16, -6), g: 45, life: rand(0.3, 0.6), color: pick(['#FFD54A', '#FFB13B', '#FFFFFF']) });
      }
      if (++this.hits % 3 === 0) {
        if (this.bricks === 3) {
          this.bricks = 0;
          for (let i = 0; i < 8; i++) {
            this.spawn({ x: pose.x + 25 + rand(-2, 2), y: pose.y + rand(6, 9), vx: rand(-6, 6), vy: rand(-8, -2), life: 0.6, color: '#BDB6AC' });
          }
        } else {
          this.bricks++;
        }
      }
    }
    return ph < 380 ? 'up' : ph < 460 ? 'mid' : 'down';
  }

  // ---- drawing ---------------------------------------------------------

  lookDir() {
    const w = this.world;
    if (w?.cursor && w.win) {
      const c = w.petCenter();
      const [dx, dy] = w.toStage((w.cursor.x - c.x) / w.k, (w.cursor.y - c.y) / w.k);
      return [dx < -6 ? -1 : dx > 6 ? 1 : 0, dy < -8 ? -1 : dy > 12 ? 1 : 0];
    }
    if (this.pointer) {
      const { x, y } = this.pointer;
      return [x < this.x + 5 ? -1 : x > this.x + 11 ? 1 : 0, y < STAND_Y ? -1 : 0];
    }
    return [0, 0];
  }

  basePose() {
    const pose = {
      x: this.x,
      y: STAND_Y,
      color: this.color,
      eyes: this.now < this.blinkUntil ? 'blink' : 'open',
      look: this.lookDir(),
      legs: [2, 2, 2, 2],
    };
    // In a voice call it looks up at the orb while listening and moves its mouth while talking.
    const v = this.voice;
    if (v?.active) {
      if (v.phase === 'speaking') pose.mouth = v.mouth;
      else if (v.phase === 'listening' || v.phase === 'hearing') pose.look = [0, -1];
    }
    if (this.walking) {
      const ms = this.world?.moving ? Math.max(45, Math.min(160, 1000 / Math.max(1, this.world.pace))) : this.stepMs;
      pose.look = [this.walkDir, 0];
      pose.legs = Math.floor(this.now / ms) % 2 ? [2, 1, 2, 1] : [1, 2, 1, 2];
    }
    return pose;
  }

  breath(period = 900) {
    return this.walking ? 0 : Math.floor(this.now / period) % 3 === 2 ? 1 : 0;
  }

  draw(p) {
    const view = this.view;
    const since = this.dragging || view === 'falling' ? this.now : this.overlay ? this.overlayAt : this.moodAt;
    this.crew.draw(p, this.now, this.color);
    (VIEWS[view] ?? VIEWS.idle)(this, p, this.basePose(), this.now - since);
    for (const pt of this.particles) {
      const fade = Math.min(1, (pt.life - pt.age) / (pt.life * 0.35));
      const x = pt.x + (pt.wobble ? Math.sin(pt.age * 3) * pt.wobble : 0);
      if (pt.kind === 'glyph') p.outlined(pt.glyph, x, pt.y, pt.color, fade);
      else p.rect(x, pt.y, pt.w, pt.h, pt.color, fade);
    }
  }

  // Bubble anchored above the head, flipped left when it would leave the stage.
  bubbleSpot(pose, w, gap = 0) {
    const right = pose.x + 15 + gap;
    return right + w <= STAGE.w ? { x: right, side: 1 } : { x: pose.x + 2 - w - gap, side: -1 };
  }

  // Status line above the pet, like Claude Code's spinner row, held steady for LABEL_HOLD.
  label() {
    const next = this.liveLabel();
    const key = next ? `${next.icon}|${next.text}|${next.dim ?? ''}` : '';
    const held = this.heldLabel;
    if (held && key === held.key) return held.label;
    const urgent = next?.icon === 'bang' || next?.icon === 'check';
    if (!held?.label || urgent || this.now - held.at >= LABEL_HOLD) {
      this.heldLabel = { key, label: next, at: this.now };
      return next;
    }
    return held.label;
  }

  liveLabel() {
    if (this.now < this.toastUntil) return { icon: 'check', text: this.toastText };
    const view = this.view;
    const s = this.focus;
    const detail = this.demoUntil ? DEMO[view] : s?.detail;
    const agents = this.crew.working;
    const extra = agents ? `+${agents} agent${agents > 1 ? 's' : ''}` : this.sessions.size > 1 ? s?.project : '';
    switch (view) {
      case 'thinking': return { icon: 'spin', text: `${this.verb}...`, dim: extra };
      case 'building': case 'testing': case 'typing': case 'reading':
      case 'searching': case 'surfing': case 'planning': case 'delegating':
        return { icon: 'spin', text: detail || 'Working...', dim: extra };
      case 'alert': return { icon: 'bang', text: (this.demoUntil ? DEMO.alert : s?.message) || 'Needs you', dim: s?.project };
      case 'waiting': return { icon: 'dots', text: 'Your turn', dim: s?.project };
      case 'done': case 'remind': return { icon: 'check', text: detail || 'Done', dim: s?.project };
      case 'compacting': return { icon: 'spin', text: 'Compacting...', dim: extra };
      case 'error': return { icon: 'bang', text: detail || 'Something broke', dim: s?.project };
      case 'shrug': return { icon: null, text: 'Interrupted' };
    }
    return null;
  }
}
