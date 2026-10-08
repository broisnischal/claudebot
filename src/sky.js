// Monochrome pixel-art sky. A tileable value-noise cloud field, computed once per resize, drifts past a fixed
// framing mask (clouds gather at the sides, part around the orb) and is quantized to a small palette
// with ordered dithering.
const BAYER = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5].map((v) => v / 16 - 0.5);
const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));

const PALETTE = [
  '#050505', '#0a0a0a', '#101010', '#171717', '#1f1f1f', '#292929', '#343434', '#414141', '#505050',
  '#616161', '#747474', '#898989', '#a0a0a0', '#b8b8b8', '#d0d0d0', '#e6e6e6', '#f7f7f7',
].map(hex);
const SKY = [[0, '#141414'], [0.5, '#262626'], [0.82, '#3c3c3c'], [1, '#585858']].map(([t, c]) => [t, hex(c)]);
const CLOUD = [[0, '#222222'], [0.25, '#444444'], [0.45, '#727272'], [0.62, '#9c9c9c'], [0.8, '#bcbcbc'], [1, '#dedede']]
  .map(([t, c]) => [t, hex(c)]);
const GROUND = [[0, '#151515'], [0.35, '#0b0b0b'], [1, '#040404']].map(([t, c]) => [t, hex(c)]);

const clamp = (v) => (v < 0 ? 0 : v > 255 ? 255 : v | 0);
const clamp01 = (v) => (v < 0 ? 0 : v > 1 ? 1 : v);
const smooth = (a, b, v) => {
  const t = clamp01((v - a) / (b - a));
  return t * t * (3 - 2 * t);
};

function gradient(stops, t) {
  for (let i = 1; i < stops.length; i++) {
    if (t <= stops[i][0]) {
      const [t0, a] = stops[i - 1], [t1, b] = stops[i];
      const k = (t - t0) / (t1 - t0 || 1);
      return [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k];
    }
  }
  return stops[stops.length - 1][1].slice();
}

function hash(x, y) {
  let h = Math.imul(x, 374761393) ^ Math.imul(y, 668265263);
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}

// Value noise that wraps every `period` lattice cells in x, so the field tiles horizontally.
function noise(x, y, period) {
  const xi = Math.floor(x), yi = Math.floor(y);
  const xf = x - xi, yf = y - yi;
  const u = xf * xf * (3 - 2 * xf), v = yf * yf * (3 - 2 * yf);
  const x0 = ((xi % period) + period) % period, x1 = (x0 + 1) % period;
  const a = hash(x0, yi), b = hash(x1, yi), c = hash(x0, yi + 1), d = hash(x1, yi + 1);
  return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v;
}

function fbm(x, y, period) {
  let sum = 0, amp = 0.5, norm = 0;
  for (let o = 0; o < 5; o++) {
    sum += amp * noise(x, y, period);
    norm += amp;
    x *= 2; y *= 2; period *= 2; amp *= 0.5;
  }
  return sum / norm;
}

export function startSky(canvas) {
  const g = canvas.getContext('2d', { alpha: false });
  const calm = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const lut = new Int16Array(32768).fill(-1);
  const cloudRamp = Array.from({ length: 65 }, (_, i) => gradient(CLOUD, i / 64));
  let W = 0, H = 0, FW = 0, field, img, drift = 400 + Math.random() * 600, last = 0;

  function nearest(r, gr, b) {
    const key = ((r >> 3) << 10) | ((gr >> 3) << 5) | (b >> 3);
    let best = lut[key];
    if (best >= 0) return best;
    let dist = Infinity;
    for (let p = 0; p < PALETTE.length; p++) {
      const c = PALETTE[p];
      const d = (c[0] - r) ** 2 * 0.3 + (c[1] - gr) ** 2 * 0.59 + (c[2] - b) ** 2 * 0.11;
      if (d < dist) { dist = d; best = p; }
    }
    lut[key] = best;
    return best;
  }

  function resize() {
    const px = innerWidth > 1600 ? 5 : 4;
    W = Math.max(1, Math.ceil(innerWidth / px));
    H = Math.max(1, Math.ceil(innerHeight / px));
    canvas.width = W;
    canvas.height = H;
    img = g.createImageData(W, H);
    FW = W * 2;
    const period = 7, sx = period / FW, sy = sx * 2.6;
    const rows = Math.ceil(H * 0.72) + 4; // nothing below the haze line needs clouds
    field = new Float32Array(FW * rows);
    for (let r = 0; r < rows; r++) {
      for (let x = 0; x < FW; x++) field[r * FW + x] = fbm(x * sx, (r - 2) * sy + 11.3, period);
    }
    draw();
  }

  function draw() {
    const d = img.data;
    const off = Math.floor(drift) % FW;
    const rows = field.length / FW;
    for (let y = 0; y < H; y++) {
      const v = y / H;
      const sky = gradient(SKY, Math.min(1, v / 0.6));
      const fade = smooth(0.4, 0.7, v);
      const ground = gradient(GROUND, smooth(0.5, 1, v));
      const lift = 1 - smooth(0.05, 0.6, v) * 0.55;
      const row = (y + 2) * FW, up = y * FW, down = (y + 4) * FW;
      const clouds = y + 4 < rows && fade < 0.999;
      for (let x = 0; x < W; x++) {
        let r = ground[0], gr = ground[1], b = ground[2];
        if (clouds) {
          r = sky[0]; gr = sky[1]; b = sky[2];
          const fx = (x + off) % FW;
          const side = Math.abs(x / W - 0.5) * 2;
          const mask = (0.1 + 0.9 * smooth(0.2, 0.95, side)) * lift;
          const dens = field[row + fx] * 1.25 + mask * 0.5 - 0.86;
          if (dens > -0.05) {
            const light = clamp01(0.42 + (field[down + fx] - field[up + fx]) * 7 + dens * 1.6);
            const c = cloudRamp[(light * 64) | 0];
            const a = smooth(-0.05, 0.06, dens);
            r += (c[0] - r) * a; gr += (c[1] - gr) * a; b += (c[2] - b) * a;
          }
          r += (ground[0] - r) * fade; gr += (ground[1] - gr) * fade; b += (ground[2] - b) * fade;
        }
        const t = BAYER[((y & 3) << 2) | (x & 3)] * 30;
        const c = PALETTE[nearest(clamp(r + t), clamp(gr + t), clamp(b + t))];
        const o = (y * W + x) * 4;
        d[o] = c[0]; d[o + 1] = c[1]; d[o + 2] = c[2]; d[o + 3] = 255;
      }
    }
    g.putImageData(img, 0, 0);
  }

  function tick(now) {
    if (!document.hidden && now - last > 250) {
      if (last) drift += ((now - last) / 1000) * 0.8;
      last = now;
      draw();
    }
    requestAnimationFrame(tick);
  }

  let pending;
  addEventListener('resize', () => {
    clearTimeout(pending);
    pending = setTimeout(resize, 120);
  });
  resize();
  if (!calm) requestAnimationFrame(tick);
}
