// The voice engine's WebSocket, shared by the pet and the panel. Each window holds one client.
// The engine does all the audio itself; windows only watch the conversation and send commands.

const T = window.__TAURI__;

export class Voice {
  constructor() {
    this.state = {
      engine: 'starting', error: '', connected: false,
      phase: 'idle', call: false, started: 0, muted: false, tool: '', approval: null,
      level: { mic: 0, out: 0 }, settings: {}, voices: [], models: [], devices: { input: [], output: [] },
      fleet: [], history: [], memory: [], music: { playing: false, paused: false, title: '', query: '' },
      host: '', audioError: '',
    };
    this.handlers = new Map();
    this.ws = null;
    this.info = null;
    this.retry = 0;
  }

  on(type, fn) {
    if (!this.handlers.has(type)) this.handlers.set(type, new Set());
    this.handlers.get(type).add(fn);
    return () => this.handlers.get(type).delete(fn);
  }

  emit(type, data) {
    for (const fn of this.handlers.get(type) ?? []) {
      try { fn(data); } catch (err) { console.error(err); }
    }
    for (const fn of this.handlers.get('*') ?? []) {
      try { fn(type, data); } catch (err) { console.error(err); }
    }
  }

  async start() {
    if (!T) return;
    await T.event.listen('voice-status', (e) => this.status(e.payload));
    this.status(await T.core.invoke('voice_info'));
  }

  status(info) {
    const changed = !this.info || info.token !== this.info.token || info.port !== this.info.port;
    this.info = info;
    this.state.engine = info.state;
    this.state.error = info.error;
    this.emit('engine', info);
    if (info.state === 'running' && (changed || !this.ws)) this.connect();
  }

  get available() {
    return this.state.connected;
  }

  connect() {
    clearTimeout(this.timer);
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.close();
    }
    const { port, token } = this.info;
    const ws = new WebSocket(`ws://127.0.0.1:${port}/ws?token=${encodeURIComponent(token)}`);
    this.ws = ws;
    ws.onopen = () => {
      this.retry = 0;
      this.state.connected = true;
      this.emit('connected', true);
    };
    ws.onmessage = (e) => {
      try { this.handle(JSON.parse(e.data)); } catch (err) { console.error(err); }
    };
    ws.onclose = () => {
      if (this.ws !== ws) return;
      this.ws = null;
      const was = this.state.connected;
      Object.assign(this.state, { connected: false, call: false, phase: 'idle', approval: null, level: { mic: 0, out: 0 } });
      if (was) this.emit('connected', false);
      // The engine restarts on its own; Claude Bot sends a new voice-status once it is back.
      if (this.state.engine === 'running') {
        this.timer = setTimeout(() => this.connect(), Math.min(5000, 250 * 2 ** this.retry++));
      }
    };
  }

  send(msg) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
      return true;
    }
    return false;
  }

  toggleCall() {
    return this.send({ type: 'call', action: this.state.call ? 'end' : 'start' });
  }

  // One level for whoever is talking: the voice while it speaks, the mic otherwise.
  get loudness() {
    const { phase, level } = this.state;
    if (phase === 'speaking') return Math.min(1, level.out * 5);
    return Math.min(1, Math.max(0, (level.mic - 0.004) * 9));
  }

  // In `tauri dev` the windows come from a local dev server; reload them when their files change,
  // so a UI tweak shows up without restarting the app (and dropping the call).
  checkBuild(build) {
    if (!build) return;
    const dev = location.protocol === 'http:' && /^(localhost|127\.0\.0\.1)$/.test(location.hostname);
    if (this.build && build !== this.build && dev) location.reload();
    this.build = build;
  }

  handle(m) {
    const S = this.state;
    if (m.type === 'hello' || m.type === 'build') this.checkBuild(m.build);
    switch (m.type) {
      case 'hello':
        Object.assign(S, {
          settings: m.settings, voices: m.voices, models: m.models, devices: m.devices, fleet: m.fleet,
          history: m.history, phase: m.phase, muted: m.muted, approval: m.approval, call: m.call.active,
          started: m.call.started, memory: m.memory, music: m.music, host: m.host, audioError: m.audio_error,
        });
        break;
      case 'phase':
        S.phase = m.phase;
        if (m.phase === 'listening' || m.phase === 'idle') S.tool = '';
        break;
      case 'call':
        S.call = m.active;
        S.started = m.started;
        if (!m.active) S.level = { mic: 0, out: 0 };
        break;
      case 'muted': S.muted = m.value; break;
      case 'level': S.level = { mic: m.mic, out: m.out }; break;
      case 'tool': S.tool = m.text || m.name.replace(/^(jarvis|pc) /, '').replace(/_/g, ' '); break;
      case 'log': S.history.push(m.entry); if (S.history.length > 300) S.history.shift(); break;
      case 'history': S.history = m.history; break;
      case 'fleet': S.fleet = m.agents; break;
      case 'approval': S.approval = m.approval; break;
      case 'settings': S.settings = m.settings; break;
      case 'memory': S.memory = m.items; break;
      case 'music': S.music = m.music; break;
    }
    this.emit(m.type, m);
  }
}
