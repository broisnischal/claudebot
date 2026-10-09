// The pet's side of the voice: voice commands that make it act things out, and its mouth moving
// while the voice talks. The mic button and the voice's status live in the bottom-left HUD
// (hud.js), so they stay put while the pet wanders.
//
// Double-tap the pet for the voice panel. `v` while the pet has focus turns the voice on or off.
import { Voice } from './voice.js';

const DOUBLE_TAP_MS = 320;

export class VoicePet {
  constructor(brain, invoke) {
    this.brain = brain;
    this.invoke = invoke;
    this.voice = new Voice();
    this.S = this.voice.state;
    this.now = 0;
    this.last = 0;
    this.tapAt = -1e9;
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

    // levels and the mouth move at the display's rate
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

  // ---- input ----

  // A click on the pet that didn't drag (main.js pokes it too). Two quick taps open the voice panel.
  tap() {
    if (this.now - this.tapAt < DOUBLE_TAP_MS) {
      this.tapAt = -1e9;
      this.invoke?.('toggle_panel').catch(() => {});
    } else {
      this.tapAt = this.now;
    }
  }

  // `claudebot --call` and the menu: talk, or hang up. The HUD's mic does the same.
  talk() {
    if (!this.S.connected) {
      this.say(this.S.engine === 'unavailable' ? 'Voice unavailable' : 'Voice is starting');
      return;
    }
    if (!this.enabled) {
      // asking to talk means I want the voice: switch it back on and go live
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

  // A short hint over the pet's head ("Voice is starting"); the voice's own status is in the HUD.
  label() {
    return this.now < this.hintUntil ? { icon: 'dots', text: this.hint } : null;
  }
}
