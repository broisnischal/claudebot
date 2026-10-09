// Fetch, from the pet's side. The ball lives on the game layer (play.js), a see-through window over
// the pet's monitor, and I throw it with the mouse. Here the pet plays along: it runs for where the
// ball will come down, hops for it when it drops close by, carries it back to my cursor and drops it
// there for another throw. Its tricks that throw things (stones, a kicked ball) go through the layer
// too, so they fly across the screen instead of vanishing at the edge of the pet's own window.

const CHASE = 52; // units a second, running for the ball
const CARRY = 24; // walking it back
const REACH = 5; // units from where it holds the ball: close enough to grab it
const QUIT_MS = 40e3; // no throw this long and it puts the ball away
const LINGER_MS = 6000; // the layer stays this long after the last stone or kick

export class Game {
  constructor(brain, world, invoke) {
    this.brain = brain;
    this.world = world;
    this.invoke = invoke;
    this.T = window.__TAURI__;
    this.active = false;
    this.layer = null; // the monitor the layer covers, while it is open
    this.opening = null;
    this.ready = false;
    this.ball = null; // the ball as the layer last reported it, in desktop pixels
    this.phase = 'idle'; // serve | carry | present | wait | chase
    this.lastThrow = 0;
    this.effectsUntil = 0;
    this.target = null;
    this.hopAt = 0;
    this.presentAt = 0;
    this.lastDir = 1;
    this.T?.event.listen('play:ball', (e) => { this.ball = e.payload; });
    this.T?.event.listen('play:ready', () => { this.ready = true; });
    this.T?.event.listen('play:event', (e) => this.onEvent(e.payload));
    // a game layer left over from before this window reloaded runs old code: close it
    this.invoke?.('play_layer', { open: false, x: 0, y: 0, width: 1, height: 1 }).catch(() => {});
  }

  get available() {
    return !!this.invoke && this.world.canRoam;
  }

  emit(name, payload) {
    this.T?.event.emit(name, payload).catch(() => {});
  }

  cmd(cmd, extra = {}) {
    this.emit('play:cmd', { cmd, ...extra });
  }

  // ---- the layer --------------------------------------------------------------------

  openLayer() {
    if (this.layer && this.ready) return Promise.resolve(true);
    if (!this.opening) {
      this.opening = (async () => {
        const m = this.world.monitor();
        this.ready = false;
        try {
          await this.invoke('play_layer', { open: true, x: m.x, y: m.y, width: m.w, height: m.h });
        } catch {
          return false;
        }
        this.layer = { x: m.x, y: m.y, w: m.w, h: m.h };
        // it says it's ready when it loads; one that was open already answers when asked
        for (let i = 0; i < 60 && !this.ready; i++) {
          if (i % 5 === 0) this.emit('play:hello', {});
          await new Promise((r) => setTimeout(r, 50));
        }
        this.sendPet();
        return this.ready;
      })().finally(() => { this.opening = null; });
    }
    return this.opening;
  }

  closeLayer() {
    if (!this.layer) return;
    this.layer = null;
    this.ready = false;
    this.ball = null;
    this.invoke?.('play_layer', { open: false, x: 0, y: 0, width: 1, height: 1 }).catch(() => {});
  }

  // Where the pet holds the ball: just past its body, on the side it faces.
  hold() {
    const c = this.world.petCenter();
    const k = this.world.k;
    return { x: c.x + this.dir() * 9 * k, y: c.y + 1.5 * k };
  }

  dir() {
    const b = this.ball;
    const c = this.world.petCenter();
    let d = 0;
    if (this.world.moving) d = this.world.dir;
    else if (b && b.state !== 'carried') d = Math.sign(b.x - c.x);
    else if (this.world.cursor) d = Math.sign(this.world.cursor.x - c.x);
    if (d) this.lastDir = d;
    return this.lastDir;
  }

  sendPet() {
    if (!this.layer || !this.world.win) return;
    this.emit('play:pet', { mouth: this.hold(), center: this.world.petCenter(), dir: this.dir(), k: this.world.k, monitor: this.layer });
  }

  // What the pet looks at while it plays: the ball.
  lookAt() {
    return this.active && this.ball && this.ball.state !== 'carried' ? this.ball : null;
  }

  // ---- a game of fetch --------------------------------------------------------------

  toggle(name) {
    if (name === 'fetch:stop' || this.active) this.stop();
    else this.start();
  }

  async start() {
    if (this.active) return;
    if (!this.available) {
      this.brain.toast?.("Fetch needs a desktop where I can move around");
      return;
    }
    this.active = true;
    this.brain.playing = true;
    this.brain.overlay = null;
    this.brain.act = null;
    if (this.brain.mood === 'sleeping') this.brain.setMood('idle', true);
    this.world.command('home'); // down to the floor first
    if (!(await this.openLayer())) {
      this.active = false;
      this.brain.playing = false;
      this.brain.toast?.("The game didn't open");
      return;
    }
    this.cmd('start', { monitor: this.layer });
    this.phase = 'serve';
    this.lastThrow = performance.now();
    this.presentAt = performance.now() + 900; // a beat to land, then it brings the ball
    this.brain.flash('hello');
  }

  stop(why = '') {
    if (!this.active) return;
    this.active = false;
    this.brain.playing = false;
    this.phase = 'idle';
    this.world.stop();
    this.cmd('stop');
    this.effectsUntil = performance.now() + 400;
    if (why === 'bored') this.brain.flash('yawn');
  }

  onEvent(e) {
    if (!this.active) return;
    if (e.type === 'thrown') {
      this.lastThrow = performance.now();
      // the ball's own update can lag the throw by a frame and still say it's in my hand
      if (this.ball) Object.assign(this.ball, { state: 'flying', held: false });
      this.phase = 'chase';
      this.target = null;
    } else if (e.type === 'grabbed') {
      this.phase = 'wait';
      this.world.stop();
    }
  }

  tick() {
    const now = performance.now();
    if (!this.layer) return;
    this.sendPet();
    if (!this.active) {
      if (now > this.effectsUntil && !this.opening) this.closeLayer();
      return;
    }
    if (this.brain.dragging) return; // I'm carrying the pet; it plays on once I let go
    const m = this.world.monitor();
    if (m.x !== this.layer.x || m.y !== this.layer.y) return this.stop('another screen');
    if (now - this.lastThrow > QUIT_MS && this.phase !== 'chase') return this.stop('bored');

    const k = this.world.k;
    const c = this.world.petCenter();
    const b = this.ball;
    const grounded = !this.world.falling && !this.world.flying && !this.world.sliding;

    if (this.phase === 'serve') {
      if (now < this.presentAt || !grounded) return;
      this.cmd('carry'); // the ball appears in its mouth
      this.phase = 'carry';
      this.target = null;
      return;
    }
    if (!b) return;

    if (this.phase === 'carry') {
      // back to me: to where my cursor is, on the floor
      const cur = this.world.cursor;
      const want = cur && this.world.sameMonitor(cur) ? cur.x : c.x;
      const close = Math.abs(want - c.x) < 14 * k;
      if (close || (!this.world.moving && this.target !== null && Math.abs(this.target - want) < 3 * k)) {
        this.world.stop();
        this.phase = 'present';
        this.presentAt = now + 450;
      } else if (grounded && (this.target === null || Math.abs(this.target - want) > 3 * k)) {
        this.target = want;
        this.world.walkTo(want, CARRY);
      }
      return;
    }

    if (this.phase === 'present') {
      if (now < this.presentAt) return;
      const toward = this.world.cursor ? Math.sign(this.world.cursor.x - c.x) || this.lastDir : this.lastDir;
      this.cmd('drop', { vx: toward * 8, vy: -45 }); // a little toss that lands in front of it
      this.phase = 'wait';
      this.lastThrow = now;
      return;
    }

    if (this.phase === 'wait') return; // the ball is mine to throw; it watches it

    if (this.phase === 'chase') {
      if (b.held && now - this.lastThrow > 300) {
        this.phase = 'wait';
        this.world.stop();
        return;
      }
      // grab it when it's within reach of where it holds the ball
      const h = this.hold();
      if (Math.hypot(b.x - h.x, b.y - h.y) < REACH * k || (Math.abs(b.x - c.x) < 9 * k && Math.abs(b.y - c.y) < 7 * k)) {
        this.cmd('carry');
        this.world.stop();
        this.phase = 'carry';
        this.target = null;
        return;
      }
      // a ball dropping close by, above its head: hop for it
      if (b.airborne && b.vy > 0 && grounded && now > this.hopAt && Math.abs(b.x - c.x) < 10 * k
          && b.y < c.y - 5 * k && b.y > c.y - 45 * k) {
        this.hopAt = now + 900;
        this.world.launch(Math.sign(b.x - c.x) * 12, -120, { gentle: true });
        return;
      }
      // run for where it comes down, or for the ball itself once it's down or nearly
      const want = b.state === 'flying' && b.landT > 0.25 ? b.landX : b.x;
      if (grounded && (this.target === null || Math.abs(this.target - want) > 2 * k || !this.world.moving)) {
        this.target = want;
        this.world.walkTo(want, CHASE);
      }
    }
  }

  // ---- the pet's tricks ---------------------------------------------------------------

  // Called when a throwing trick starts, so the layer is open by the time something flies.
  prepare() {
    if (!this.available) return;
    this.effectsUntil = performance.now() + LINGER_MS + 5000;
    this.openLayer();
  }

  // One stone skimmed along the floor, away from the nearer screen edge. False when there's no layer.
  stone() {
    if (!this.layer || !this.ready) return false;
    const c = this.world.petCenter();
    const k = this.world.k;
    const dir = c.x > this.layer.x + this.layer.w / 2 ? -1 : 1;
    this.cmd('stone', { x: c.x + dir * 9 * k, y: c.y - 1 * k, dir });
    this.effectsUntil = performance.now() + LINGER_MS;
    return true;
  }

  kick() {
    if (!this.layer || !this.ready) return false;
    const c = this.world.petCenter();
    const k = this.world.k;
    const dir = c.x > this.layer.x + this.layer.w / 2 ? -1 : 1;
    this.cmd('kick', { x: c.x + dir * 9 * k, y: c.y + 3 * k, dir });
    this.effectsUntil = performance.now() + LINGER_MS;
    return true;
  }
}
