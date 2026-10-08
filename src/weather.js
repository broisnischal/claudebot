// The real weather outside, shown around the pet. No API key: the location comes from an
// IP lookup and the current conditions from Open-Meteo, with wttr.in as the fallback.
// Rain, snow and storms only show when the condition code says so *and* there is measured
// precipitation; a failed fetch, unknown data or a reading older than STALE shows nothing.
// Every decision is logged so it can be checked against the window.

import { STAGE, GROUND, WHITE } from './sprite.js';

const CACHE_KEY = 'claudebot.weather.v2';
const REFRESH = 15 * 60e3;
const STALE = 45 * 60e3;

// Open-Meteo (WMO) weather codes.
function kindOfWmo(code) {
  if (code === 0) return 'clear';
  if (code <= 3) return 'clouds';
  if (code === 45 || code === 48) return 'fog';
  if ((code >= 51 && code <= 67) || (code >= 80 && code <= 82)) return 'rain';
  if ((code >= 71 && code <= 77) || code === 85 || code === 86) return 'snow';
  if (code >= 95) return 'thunder';
  return 'unknown';
}

// Words for the common Open-Meteo codes, for the tray tooltip.
const WMO_WORDS = {
  0: 'clear', 1: 'mostly clear', 2: 'partly cloudy', 3: 'overcast', 45: 'fog', 48: 'fog',
  51: 'light drizzle', 53: 'drizzle', 55: 'heavy drizzle', 61: 'light rain', 63: 'rain', 65: 'heavy rain',
  71: 'light snow', 73: 'snow', 75: 'heavy snow', 80: 'showers', 81: 'showers', 82: 'heavy showers',
  95: 'thunderstorm', 96: 'thunderstorm', 99: 'thunderstorm',
};

// wttr.in (WWO) condition codes.
const WWO = {
  clear: [113],
  clouds: [116, 119, 122],
  fog: [143, 248, 260],
  rain: [176, 263, 266, 281, 284, 293, 296, 299, 302, 305, 308, 311, 314, 353, 356, 359],
  snow: [179, 182, 185, 227, 230, 317, 320, 323, 326, 329, 332, 335, 338, 350, 362, 365, 368, 371, 374, 377],
  thunder: [200, 386, 389, 392, 395],
};
const kindOfWwo = (code) => Object.keys(WWO).find((k) => WWO[k].includes(code)) ?? 'unknown';

// Wet weather needs water actually falling: a rain code with zero precipitation is cloud.
function decide(kind, precip) {
  if (kind === 'unknown' || !Number.isFinite(precip)) return kind === 'unknown' ? null : kind === 'rain' || kind === 'snow' ? 'clouds' : kind;
  if ((kind === 'rain' || kind === 'snow') && precip <= 0) return 'clouds';
  return kind;
}

async function getJson(url) {
  const res = await fetch(url, { signal: AbortSignal.timeout(9000) });
  if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`);
  return res.json();
}

export class Weather {
  constructor(log = () => {}) {
    this.log = log;
    this.enabled = true;
    this.sky = null; // { kind, intensity, temp, wind, desc, day, place, source, at }
    this.busy = false;
    try {
      const cached = JSON.parse(localStorage.getItem(CACHE_KEY) ?? 'null');
      if (cached && Date.now() - cached.at < STALE) this.sky = cached;
    } catch {}
  }

  start() {
    this.maybeRefresh();
    setInterval(() => this.maybeRefresh(), 5 * 60e3);
  }

  maybeRefresh() {
    if (this.enabled && !this.busy && (!this.sky || Date.now() - this.sky.at > REFRESH)) this.refresh();
  }

  async refresh() {
    this.busy = true;
    try {
      this.sky = await this.fromOpenMeteo().catch((e) => {
        this.log(`weather: open-meteo failed (${e.message ?? e}), trying wttr.in`);
        return this.fromWttr();
      });
      this.log(`weather: ${this.sky.source} at ${this.sky.place}: ${this.sky.raw} -> ${this.sky.kind ?? 'unknown, showing a clear sky'}`);
      try {
        localStorage.setItem(CACHE_KEY, JSON.stringify(this.sky));
      } catch {}
    } catch (e) {
      // Offline, or blocked: nothing reliable, so no weather at all rather than a guess.
      this.sky = null;
      this.log(`weather: no reading (${e.message ?? e}), showing a clear sky`);
    } finally {
      this.busy = false;
    }
  }

  async fromOpenMeteo() {
    const where = await getJson('https://ipwho.is/');
    if (!where.success && where.success !== undefined) throw new Error(where.message ?? 'ip lookup failed');
    const q = `latitude=${where.latitude}&longitude=${where.longitude}`
      + '&current=temperature_2m,weather_code,precipitation,rain,showers,snowfall,cloud_cover,wind_speed_10m,is_day';
    const c = (await getJson(`https://api.open-meteo.com/v1/forecast?${q}`)).current;
    // Precipitation is over the last 15 minutes; 0.5 mm in that time is a proper downpour.
    const precip = Math.max(c.precipitation ?? 0, (c.rain ?? 0) + (c.showers ?? 0), c.snowfall ?? 0);
    return {
      source: 'open-meteo',
      place: `${where.city}, ${where.country} (${where.latitude.toFixed(2)}, ${where.longitude.toFixed(2)})`,
      raw: `code ${c.weather_code}, precipitation ${c.precipitation} mm/15min, cloud ${c.cloud_cover}%, ${c.temperature_2m}C, wind ${c.wind_speed_10m} km/h`,
      kind: decide(kindOfWmo(c.weather_code), precip),
      intensity: Math.min(1, precip / 0.5),
      temp: c.temperature_2m, wind: c.wind_speed_10m, day: c.is_day === 1, desc: WMO_WORDS[c.weather_code] ?? '', at: Date.now(),
    };
  }

  async fromWttr() {
    const j = await getJson('https://wttr.in/?format=j1');
    const now = j.current_condition[0];
    const area = j.nearest_area?.[0];
    const precip = Number(now.precipMM);
    const h = new Date().getHours();
    return {
      source: 'wttr.in',
      place: area ? `${area.areaName?.[0]?.value}, ${area.country?.[0]?.value} (${area.latitude}, ${area.longitude})` : 'unknown place',
      raw: `code ${now.weatherCode} "${now.weatherDesc?.[0]?.value?.trim()}", precipitation ${now.precipMM} mm/h, cloud ${now.cloudcover}%, ${now.temp_C}C, wind ${now.windspeedKmph} km/h`,
      kind: decide(kindOfWwo(Number(now.weatherCode)), precip),
      intensity: Math.min(1, precip / 2),
      temp: Number(now.temp_C), wind: Number(now.windspeedKmph), day: h >= 6 && h < 18,
      desc: now.weatherDesc?.[0]?.value?.trim() ?? '', at: Date.now(),
    };
  }

  // What to draw right now, or null (a clear sky, nothing drawn) when off, unknown or stale.
  get now() {
    const s = this.sky;
    if (!this.enabled || !s || !s.kind || Date.now() - s.at > STALE) return null;
    return { kind: s.kind, intensity: s.intensity ?? 0.5, windy: s.wind >= 30, day: !!s.day, temp: s.temp, desc: s.desc };
  }

  // A short line for the tray tooltip, e.g. "19C light drizzle".
  get summary() {
    const s = this.now;
    if (!s) return '';
    const wet = s.kind === 'rain' ? (s.intensity < 0.3 ? 'light rain' : s.intensity < 0.7 ? 'rain' : 'heavy rain') : s.kind;
    return `${Math.round(s.temp)}C ${s.desc || wet}`.toLowerCase();
  }
}

// ---- drawing -------------------------------------------------------------
// The back layer goes behind the pet (sky, clouds, stars, puddle), the front layer over it
// (rain, snow, wind, fog, lightning). All of it is a handful of rects per frame.

const W = STAGE.w;

function cloud(p, x, y, color, alpha = 0.9) {
  p.rect(x + 1, y, 5, 1, color, alpha);
  p.rect(x, y + 1, 8, 2, color, alpha);
  p.rect(x + 5, y - 1, 2, 1, color, alpha);
}

export function drawSkyBack(p, s, t, petX) {
  if (!s) return;
  const drift = (speed, offset) => ((t / 1000) * speed + offset) % (W + 12) - 10;
  if (!s.day && (s.kind === 'clear' || s.kind === 'clouds')) {
    [[3, 2], [11, 4], [46, 3], [52, 6], [30, 1]].forEach(([x, y], i) => {
      if ((Math.floor(t / 700) + i) % 4) p.rect(x, y, 1, 1, WHITE, 0.8);
    });
    p.bitmap(['.##', '#..', '#..', '#..', '.##'], 6, 2, '#F3EFD8');
  }
  if (s.day && s.kind === 'clear') {
    const ray = Math.floor(t / 500) % 2;
    p.rect(4, 3, 3, 3, '#FFD54A');
    p.bitmap(ray ? ['#...#', '.....', '.....', '.....', '#...#'] : ['..#..', '.....', '#...#', '.....', '..#..'], 3, 2, '#FFE58A');
  }
  if (s.kind === 'clouds' || s.kind === 'rain' || s.kind === 'snow') {
    cloud(p, drift(1.2, 0), 3, s.day ? '#E3E7EC' : '#8E95A1');
    cloud(p, drift(0.8, 30), 6, s.day ? '#D3D8DF' : '#7C838F', 0.8);
  }
  if (s.kind === 'thunder') {
    cloud(p, drift(1.5, 10), 3, '#5E6470');
    cloud(p, drift(1.1, 34), 5, '#6B717C');
  }
  if (s.kind === 'rain' || s.kind === 'thunder') {
    p.rect(petX + 1, GROUND, 16, 1, '#5B8FCF', 0.55);
    p.rect(petX + 3 + (Math.floor(t / 400) % 10), GROUND, 2, 1, '#BFE0FF', 0.7);
  }
}

export function drawSkyFront(p, s, t) {
  if (!s) return;
  const sec = t / 1000;
  const slant = s.windy ? 0.5 : 0.15;
  const drops = Math.round(4 + 12 * (s.intensity ?? 0.5));
  if (s.kind === 'rain' || (s.kind === 'thunder' && s.intensity > 0)) {
    for (let i = 0; i < drops; i++) {
      const y = (sec * 34 + i * 13.7) % 30;
      const x = (i * 7.3 + y * slant + sec * (s.windy ? 9 : 2)) % W;
      p.rect(x, y, 1, 2, '#8FC1F0', 0.7);
    }
  }
  if (s.kind === 'snow') {
    for (let i = 0; i < drops + 2; i++) {
      const y = (sec * 6 + i * 11.3) % 30;
      const x = (i * 9.7 + Math.sin(sec * 1.3 + i) * 1.5 + sec * (s.windy ? 6 : 0.5)) % W;
      p.rect(x, y, 1, 1, WHITE, 0.9);
    }
  }
  if (s.windy && s.kind !== 'rain' && s.kind !== 'snow') {
    for (let i = 0; i < 4; i++) {
      const x = (sec * 30 + i * 17) % (W + 8) - 4;
      p.rect(x, 6 + i * 5, 3, 1, WHITE, 0.45);
    }
    p.rect((sec * 22) % W, 12 + Math.round(Math.sin(sec * 4) * 2), 1, 1, '#D98E3E');
  }
  if (s.kind === 'fog') {
    for (let i = 0; i < 3; i++) p.rect(((sec * (2 + i)) % 20) - 10, 10 + i * 6, W + 20, 2, '#D8DCE2', 0.13);
  }
  if (s.kind === 'thunder' && t % 7000 < 110) {
    p.rect(0, 0, W, 30, WHITE, 0.22);
    p.bitmap(['.#', '#.', '.#', '#.', '.#'], 40, 6, '#FFE45C');
  }
}

// Something to wear for the weather, while the pet is just hanging around.
export function drawWear(p, s, x, top) {
  if (!s) return;
  if (s.kind === 'rain' || s.kind === 'thunder') {
    p.rect(x + 3, top - 4, 11, 1, '#E5484D');
    p.rect(x + 5, top - 5, 7, 1, '#E5484D');
    p.rect(x + 2, top - 3, 1, 1, '#E5484D');
    p.rect(x + 14, top - 3, 1, 1, '#E5484D');
    p.rect(x + 8, top - 3, 1, 4, '#3B3B40');
  } else if (s.kind === 'snow') {
    p.rect(x + 3, top - 1, 11, 1, WHITE);
    p.rect(x + 5, top - 2, 6, 1, WHITE);
  } else if (s.kind === 'clear' && s.day) {
    p.rect(x + 3, top + 2, 3, 2, '#1A1A1A');
    p.rect(x + 11, top + 2, 3, 2, '#1A1A1A');
    p.rect(x + 6, top + 2, 5, 1, '#1A1A1A');
  }
}
