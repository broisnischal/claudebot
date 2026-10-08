// Subagents show up as mini Clawds that walk in, work beside the pet, and walk off when done.

import { STAGE, GROUND, GLYPHS, CLAUDE, drawClawd, spinnerFrame } from './sprite.js';
import * as P from './props.js';

// Where each mini Clawd stands (left edge, in stage units). The first two flank the pet.
const SLOTS = [11, 46, 2];
const STEP_MS = 90;

const exitX = (slot) => (SLOTS[slot] < STAGE.w / 2 ? -12 : STAGE.w + 2);

export class Crew {
  constructor() {
    this.agents = [];
  }

  get working() {
    return this.agents.filter((a) => a.state === 'enter' || a.state === 'work').length;
  }

  find(id) {
    return this.agents.find((a) => a.id === id);
  }

  freeSlot() {
    const used = new Set(this.agents.map((a) => a.slot));
    const i = SLOTS.findIndex((_, i) => !used.has(i));
    return i < 0 ? null : i;
  }

  spawn(id, session, type, now) {
    const existing = this.find(id);
    if (existing) return existing;
    const slot = this.freeSlot();
    const agent = {
      id, session, type: type || 'Agent',
      mood: 'thinking', state: 'enter',
      at: now, last: now, doneAt: 0,
      slot, x: slot === null ? null : exitX(slot), stepAt: 0, steps: 0,
    };
    this.agents.push(agent);
    return agent;
  }

  // A tool call made inside a subagent.
  event(h, mood, now) {
    const a = this.find(h.agent) ?? this.spawn(h.agent, h.session, h.agentType, now);
    a.last = now;
    if (mood && a.state !== 'done') {
      a.mood = mood;
      a.at = now;
    }
  }

  finish(id, session, now) {
    const a = (id && this.find(id)) || this.agents.find((x) => x.session === session && x.state !== 'done' && x.state !== 'leave');
    if (!a) return null;
    a.state = 'done';
    a.mood = 'done';
    a.doneAt = a.at = now;
    return a;
  }

  dropSession(session) {
    for (const a of this.agents) if (a.session === session) a.state = 'leave';
  }

  update(now) {
    for (const a of this.agents) {
      if (a.state === 'done' && now - a.doneAt > 2200) a.state = 'leave';
      if ((a.state === 'enter' || a.state === 'work') && now - a.last > 15 * 60e3) a.state = 'leave';
      if (a.slot === null && a.state !== 'leave') {
        a.slot = this.freeSlot();
        if (a.slot !== null) a.x = exitX(a.slot);
      }
      if (a.slot === null) {
        if (a.state === 'leave') a.state = 'gone';
        continue;
      }
      const target = a.state === 'leave' ? exitX(a.slot) : SLOTS[a.slot];
      if (a.x !== target && now >= a.stepAt) {
        a.stepAt = now + STEP_MS;
        a.x += Math.sign(target - a.x);
        a.steps++;
      }
      if (a.state === 'enter' && a.x === target) a.state = 'work';
      if (a.state === 'leave' && a.x === target) a.state = 'gone';
    }
    this.agents = this.agents.filter((a) => a.state !== 'gone');
  }

  draw(p, now, color) {
    const px = Math.max(1, Math.floor(p.px / 2));
    const scale = px / p.px;
    for (const a of this.agents) {
      if (a.slot === null) continue;
      const mp = p.child(px, a.x, GROUND - 10 * scale);
      const t = now - a.at;
      const walking = a.state === 'enter' || a.state === 'leave';
      const pose = {
        x: 0, y: 0, color,
        look: walking ? [Math.sign((a.state === 'leave' ? exitX(a.slot) : SLOTS[a.slot]) - a.x), 0] : [0, 0],
        legs: walking ? (a.steps % 2 ? [2, 1, 2, 1] : [1, 2, 1, 2]) : [2, 2, 2, 2],
      };
      (MINI[walking && a.mood !== 'done' ? 'walk' : a.mood] ?? MINI.thinking)(mp, pose, t);
    }
  }
}

// Mini scenes reuse the full-size props; the child painter shrinks them.
const MINI = {
  walk(p, pose) {
    drawClawd(p, pose);
  },
  thinking(p, pose, t) {
    pose.look = [0, -1];
    drawClawd(p, pose);
    p.bitmap(spinnerFrame(Math.floor(t / 110)), 6, -7, CLAUDE);
  },
  building(p, pose, t) {
    const ph = t % 700;
    const frame = ph < 380 ? 'up' : ph < 460 ? 'mid' : 'down';
    pose.armR = { up: -3, mid: -1, down: 1 }[frame];
    pose.look = [1, 0];
    drawClawd(p, pose);
    P.hardHat(p, 0, 0);
    P.hammer(p, 0, 0, frame);
  },
  testing(p, pose, t) {
    pose.armR = -2;
    drawClawd(p, pose);
    P.goggles(p, 0, 0);
    P.flask(p, 0, 0, t);
  },
  typing(p, pose, t) {
    pose.look = [0, 1];
    drawClawd(p, pose);
    P.laptop(p, 0, 0, t);
  },
  planning(p, pose, t) {
    drawClawd(p, pose);
    P.clipboard(p, 0, 0, t);
  },
  reading(p, pose, t) {
    pose.look = [0, 1];
    drawClawd(p, pose);
    P.book(p, 0, 0, t);
  },
  searching(p, pose, t) {
    const side = Math.floor(t / 1100) % 2;
    pose.eyes = side ? ['open', 'big'] : ['big', 'open'];
    drawClawd(p, pose);
    P.magnifier(p, side ? 12 : 4, 2);
  },
  surfing(p, pose, t) {
    const bob = P.surf(p, 0, 0, t);
    pose.y -= 1 + bob;
    drawClawd(p, pose);
  },
  done(p, pose, t) {
    pose.y -= t < 500 ? [0, 2, 3, 2, 0][Math.floor(t / 100)] : 0;
    pose.eyes = 'happy';
    pose.armL = pose.armR = -4;
    drawClawd(p, pose);
    p.outlined(GLYPHS.check, 6, -7, '#3DBA5C');
  },
};
