// The pet's side of the voice: a mic button over its head when I hover or tap it, voice commands
// that make it act things out, and its mouth moving while the voice talks. The call orb and the
// voice's status line live in the bottom-left HUD (hud.js), so they don't wander with the pet.
//
// Click the mic to talk (it turns the voice on first if it was off), click it again to hang up.
// Double-tap the pet for the voice panel. `v` while the pet has focus turns the voice on or off.
import { STAGE, SPRITE, STAND_Y } from './sprite.js';
import { Voice } from './voice.js';
import { drawOrb } from './voice-orb.js';

const CELLS = 9; // the button's diameter, in half units
const DOUBLE_TAP_MS = 320;
const HOVER_GRACE_MS = 1600;
const TAP_SHOW_MS = 5000; // how long the mic stays up after a tap

export class VoicePet {
  constructor(brain, invoke) {
    this.brain = brain;
    this.invoke = invoke;
    this.voice = new Voice();
    this.S = this.voice.state;
    this.now = 0;
    this.last = 0;
    this.hoverAt = -1e9;
    this.overButton = false;
    this.tapAt = -1e9;
    this.drawn = false;
    this.hint = '';
    this.hintUntil = 0;
    this.level = 0;
    this.mouth = null;
    this.mouthAt = 0;
    this.voice.on('call', (m) => {
      if (!m.active) return;
      if (brain.mood === 'sleeping') brain.setMood('idle');
      else brain.flash('hello');
    });
    this.voice.on('pet', (m) => this.act(m.action));
    // The pet reads desktop notifications out through the voice (its own quiet rules apply first).
    brain.voiceAnnounce = (text) => this.voice.send({ type: 'announce', text: String(text).slice(0, 300) });
    const report = () => this.invoke?.('set_voice_enabled', { on: this.enabled }).catch(() => {});
    this.voice.on('hello', report);
    this.voice.on('settings', report);
    addEventListener('keydown', (e) => {
      if (e.key === 'v' && !e.ctrlKey && !e.metaKey && !e.altKey) this.voice.send({ type: 'voice', action: 'toggle' });
    });

    this.armed = false; // the press went down on the mic; its release talks, wherever the pet went
    this.pressedAt = -1e9;
    // levels and the mouth move at the display's rate; the button itself is drawn by main.js
    const loop = (now) => {
      requestAnimationFrame(loop);
      this.update(now);
    };
    requestAnimationFrame(loop);
  }

  async start() {
    if (!this.invoke) return;
    const T = window.__TAURI__;
    // Commands from the menu, the tray or `claudebot --call` arrive here to go out to the engine.
    const drain = async () => {
      for (const cmd of await this.invoke('take_voice_commands').catch(() => [])) this.command(cmd);
    };
    await T.event.listen('voice-commands', drain);
    const log = (message) => this.invoke('log', { message }).catch(() => {});
    this.voice.on('engine', (i) => log(`voice engine ${i.state}${i.error ? `: ${i.error}` : ''}`));
    this.voice.on('connected', (up) => {
      log(up ? 'voice connected' : 'voice disconnected');
      if (up) drain();
    });
    await this.voice.start();
  }

  command(cmd) {
    const v = this.voice;
    if (cmd === 'call') this.talk();
    else if (cmd === 'voice') v.send({ type: 'voice', action: 'toggle' });
    else if (cmd === 'voice-on') v.send({ type: 'voice', on: true });
    else if (cmd === 'voice-off') v.send({ type: 'voice', on: false });
    else if (cmd === 'interrupt') v.send({ type: 'interrupt' });
    else if (cmd === 'mute') v.send({ type: 'mute', value: !this.S.muted });
    else if (cmd === 'ptt-start') v.send({ type: 'ptt', down: true });
    else if (cmd === 'ptt-stop') v.send({ type: 'ptt', down: false });
    else if (cmd.startsWith('say:')) v.send({ type: 'text', text: cmd.slice(4) });
  }

  // A pet_action from the voice: fly, dance, hide, peek, a corner and the rest.
  act(name) {
    this.brain.lastActive = this.now;
    this.brain.play(name);
  }

  // ---- state ----

  get enabled() {
    return this.S.settings.enabled !== false;
  }

  // Anything worth showing: a call, or a reply still being worked on or spoken.
  get active() {
    return this.S.connected && (this.S.call || this.S.phase !== 'idle');
  }

  get hovered() {
    return this.now - this.hoverAt < HOVER_GRACE_MS;
  }

  // Tucked behind a screen edge the button would be off screen too.
  get tucked() {
    const w = this.brain.world;
    return !!(w?.rim && w.rim.tuck > 0.2);
  }

  get visible() {
    return (this.hovered || this.armed) && !this.tucked && this.S.engine !== 'unavailable';
  }

  update(now) {
    const dt = Math.min(0.1, Math.max(0, (now - (this.last || now)) / 1000));
    this.last = this.now = now;
    // levels arrive 20 times a second; glide between them, quick up and slower down
    const target = this.voice.loudness;
    const tau = target > this.level ? 0.05 : 0.15;
    this.level += (target - this.level) * (1 - Math.exp(-dt / tau));
    // the mouth follows the voice with some hysteresis and a short hold, so it doesn't flicker
    const want = this.level > (this.mouth === 'O' ? 0.35 : 0.5) ? 'O' : this.level > (this.mouth ? 0.08 : 0.14) ? 'o' : null;
    if (want !== this.mouth && now - this.mouthAt > 90) {
      this.mouth = want;
      this.mouthAt = now;
    }
    this.brain.voice = { active: this.active, phase: this.S.phase, level: this.level, mouth: this.mouth };
  }

  // ---- geometry, in stage units ----

  // Diameter in units and the top-left corner, in stage units (main.js rotates the stage with the
  // pet on the side and top edges, and the button rotates with it). Beside the body at mid height,
  // left of the arm, or right of it near the stage's left edge: clear of the head, the thought
  // bubble, the status pill and the hats, and anchored to where the pet stands, not to its hops.
  spot() {
    const d = CELLS / 2;
    const y = STAND_Y + 4 - d / 2;
    let x = Math.round(this.brain.x) - d - 0.5;
    if (x < 0.5) x = Math.round(this.brain.x) + SPRITE.w + 0.5;
    x = Math.max(0.5, Math.min(STAGE.w - d - 0.5, x));
    return { x, y, d };
  }

  // Only drawn things take clicks, so main.js adds this to the window's hit region. A unit of
  // slack around the button so a slightly-off click still lands.
  rect() {
    if (!this.visible) return null;
    const { x, y, d } = this.spot();
    return { x: Math.floor(x - 1), y: Math.floor(y - 1), w: Math.ceil(d + 2), h: Math.ceil(d + 2) };
  }

  inside(u) {
    const r = this.rect();
    return !!(r && u && u.x >= r.x && u.x < r.x + r.w && u.y >= r.y && u.y < r.y + r.h);
  }

  // ---- input ----

  hover(u) {
    this.hoverAt = Math.max(this.hoverAt, this.now);
    this.overButton = this.inside(u);
  }

  leave() {
    this.overButton = false;
    this.armed = false; // dragged off the button before letting go: no click
  }

  // Pointer down. True when it landed on the mic: the press is the mic's from here on (main.js
  // starts no drag), shows pressed at once, and its release talks even if the pet moved under it.
  down(u) {
    if (!this.inside(u)) return false;
    this.armed = true;
    this.pressedAt = this.now;
    return true;
  }

  // Pointer up. True when the mic took it.
  up() {
    if (!this.armed) return false;
    this.armed = false;
    this.hoverAt = this.now;
    this.talk();
    return true;
  }

  // A click on the pet that didn't drag. A tap stays a poke (it wakes the pet and acknowledges the
  // "done" sign) and brings up the mic; two quick taps open the voice panel. Returns true when the
  // mic took it instead (for main.js versions that don't call down() and up()).
  press(u) {
    if (this.armed || this.inside(u)) {
      this.armed = false;
      this.hoverAt = this.now;
      this.talk();
      return true;
    }
    this.hoverAt = this.now + TAP_SHOW_MS - HOVER_GRACE_MS;
    if (this.now - this.tapAt < DOUBLE_TAP_MS) {
      this.tapAt = -1e9;
      this.invoke?.('toggle_panel').catch(() => {});
    } else {
      this.tapAt = this.now;
    }
    return false;
  }

  talk() {
    if (!this.S.connected) {
      this.say(this.S.engine === 'unavailable' ? 'Voice unavailable' : 'Voice is starting');
      return;
    }
    if (!this.enabled) {
      // clicking the mic means I want to talk: switch the voice back on and go live
      this.voice.send({ type: 'voice', on: true });
      this.voice.send({ type: 'call', action: 'start' });
      return;
    }
    this.voice.toggleCall();
  }

  say(text) {
    this.hint = text;
    this.hintUntil = this.now + 2400;
  }

  // ---- drawing ----

  // Only hints about the mic; the voice's own status is in the HUD.
  label() {
    if (this.now < this.hintUntil) return { icon: 'dots', text: this.hint };
    if (!this.hovered || !this.S.connected) return null;
    if (!this.enabled) return { icon: null, text: 'Voice is off', dim: 'click the mic' };
    return { icon: null, text: this.S.call ? 'Click the mic to hang up' : 'Click the mic to talk' };
  }

  // Called by main.js inside its stage transform, after the pet is drawn.
  draw(p) {
    if (!this.visible) return;
    const { x, y, d } = this.spot();
    const cell = Math.max(1, Math.round(p.px / 2));
    const ox = Math.round(p.ox + (x + d / 2) * p.px - (CELLS * cell) / 2);
    const oy = Math.round(p.oy + (y + d / 2) * p.px - (CELLS * cell) / 2);
    const phase = !this.enabled ? 'off' : this.S.call ? 'hangup' : 'idle';
    const pressed = this.armed || this.now - this.pressedAt < 160;
    drawOrb(p.ctx, ox, oy, cell, CELLS, { phase, now: this.now, hot: this.overButton || pressed, pressed });
  }
}
