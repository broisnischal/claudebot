// The dotted sphere. Latitude rings of dots, tilted toward me, reacting to whichever voice is active.
const TAU = Math.PI * 2;

const LOOKS = {
  idle:         { spin: 0.10, react: 0.0, glow: 0.62, scan: 0, size: 1.00, color: [236, 236, 236] },
  listening:    { spin: 0.16, react: 1.0, glow: 0.85, scan: 0, size: 1.00, color: [244, 244, 244] },
  hearing:      { spin: 0.24, react: 1.7, glow: 1.00, scan: 0, size: 1.04, color: [255, 255, 255] },
  transcribing: { spin: 0.55, react: 0.2, glow: 0.90, scan: 1, size: 0.97, color: [214, 214, 214] },
  thinking:     { spin: 0.70, react: 0.2, glow: 0.90, scan: 1, size: 0.96, color: [214, 214, 214] },
  speaking:     { spin: 0.22, react: 1.5, glow: 1.00, scan: 0, size: 1.02, color: [255, 255, 255] },
  approval:     { spin: 0.12, react: 0.8, glow: 1.00, scan: 1, size: 1.03, color: [255, 255, 255] },
  muted:        { spin: 0.06, react: 0.0, glow: 0.32, scan: 0, size: 0.94, color: [150, 150, 150] },
};

export class Orb {
  constructor(canvas) {
    this.canvas = canvas;
    this.g = canvas.getContext('2d');
    this.t = 0;
    this.rot = 0;
    this.energy = 0;
    this.look = structuredClone(LOOKS.idle);
    this.calm = matchMedia('(prefers-reduced-motion: reduce)').matches;
    this.points = [];
    const rings = 17;
    for (let i = 0; i < rings; i++) {
      const lat = -Math.PI / 2 + ((i + 0.5) * Math.PI) / rings;
      const n = Math.max(6, Math.round(Math.cos(lat) * 46));
      for (let j = 0; j < n; j++) {
        this.points.push({ lat, lon: ((j + (i % 2) * 0.5) / n) * TAU, seed: (i * 7.31 + j * 3.17) % TAU });
      }
    }
    new ResizeObserver(() => this.resize()).observe(canvas);
    this.resize();
  }

  resize() {
    const r = this.canvas.getBoundingClientRect();
    const d = Math.min(2, devicePixelRatio || 1);
    this.canvas.width = Math.round(r.width * d);
    this.canvas.height = Math.round(r.height * d);
  }

  frame(dt, phase, level) {
    const target = LOOKS[phase] || LOOKS.idle;
    const k = 1 - Math.exp(-dt * 4);
    const L = this.look;
    for (const key of ['spin', 'react', 'glow', 'scan', 'size']) L[key] += (target[key] - L[key]) * k;
    for (let i = 0; i < 3; i++) L.color[i] += (target.color[i] - L.color[i]) * k;

    const want = Math.min(1, level * L.react);
    const rate = want > this.energy ? 22 : 5; // fast attack, slow release
    this.energy += (want - this.energy) * (1 - Math.exp(-dt * rate));
    this.t += dt;
    this.rot += dt * L.spin * (this.calm ? 0.4 : 1);
    this.draw();
  }

  draw() {
    const { g, canvas: c, look: L, t } = this;
    const W = c.width, H = c.height;
    g.clearRect(0, 0, W, H);
    const cx = W / 2, cy = H / 2;
    const R = Math.min(W, H) * 0.38 * L.size * (1 + Math.sin(t * 1.3) * 0.012);
    const tilt = -0.36, ct = Math.cos(tilt), st = Math.sin(tilt);
    const base = Math.max(1.2, R * 0.02);
    const e = this.calm ? this.energy * 0.4 : this.energy;
    const scanY = Math.sin(t * 1.9);
    const [r, gr, b] = L.color.map((v) => v | 0);

    for (const p of this.points) {
      const lon = p.lon + this.rot;
      const cl = Math.cos(p.lat);
      const x = cl * Math.cos(lon), y = Math.sin(p.lat), z = cl * Math.sin(lon);
      const y2 = y * ct - z * st, z2 = y * st + z * ct;
      const wave = Math.sin(p.lat * 5 + t * 3.1 + p.seed * 0.4) * Math.cos(lon * 3 - t * 2.4);
      const d = 1 + e * (0.15 * wave + 0.05);
      const scan = L.scan * Math.exp(-((y - scanY) ** 2) * 22);
      const depth = (z2 + 1) / 2; // 0 at the back, 1 facing me
      const size = base * (0.4 + 0.8 * depth) * (1 + scan * 0.7 + e * 0.25);
      const alpha = Math.min(1, (0.1 + 0.9 * depth ** 1.5) * L.glow + scan * 0.55);
      g.fillStyle = `rgba(${r},${gr},${b},${alpha.toFixed(3)})`;
      g.beginPath();
      g.arc(cx + x * R * d, cy - y2 * R * d, size, 0, TAU);
      g.fill();
    }
  }
}
