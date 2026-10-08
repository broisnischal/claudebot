// One drawing function per scene. Each gets the brain, the painter, a base pose
// (position, blink, walking legs, where the eyes look) and ms since the scene began.

import { GROUND, GLYPHS, CLAUDE, OUTLINE, WHITE, drawClawd, spinnerFrame } from './sprite.js';
import * as P from './props.js';
import { drawWear } from './weather.js';

const top = (pose) => pose.y + (pose.squash ?? 0);

function yawnPose(pose, t) {
  const mid = t > 250 && t < 1300;
  pose.squash = mid ? -1 : 0;
  pose.armL = pose.armR = mid ? -4 : 0;
  pose.eyes = mid ? 'closed' : 'blink';
  pose.mouth = mid ? 'O' : null;
}

// ---- thinking styles, picked from the spinner verb -----------------------

const THINK = {
  bubble(b, p, pose, t) {
    pose.squash = b.breath(1100);
    if (!b.walking) pose.look = Math.floor(t / 1600) % 3 === 2 ? [-1, -1] : [1, -1];
    pose.armL = -1;
    drawClawd(p, pose);
    const { x: bx, side } = b.bubbleSpot(pose, 9, 2);
    const by = pose.y - 12;
    p.dot(side > 0 ? pose.x + 14 : pose.x + 2, pose.y - 2, 1);
    p.dot(side > 0 ? pose.x + 15 : pose.x, pose.y - 5, 2);
    p.bubble(bx, by, 9, 9);
    p.bitmap(spinnerFrame(Math.floor(t / 110)), bx + 2, by + 2, CLAUDE);
  },

  ponder(b, p, pose, t) {
    pose.squash = b.breath(1200);
    pose.look = Math.floor(t / 2000) % 2 ? [-1, -1] : [1, -1];
    pose.armR = -2;
    drawClawd(p, pose);
    const k = Math.floor(t / 500) % 7;
    for (let i = 0; i < Math.min(k, 3); i++) p.dot(pose.x + 14 + i * 2, pose.y - 3 - i * 2, 1);
    if (k >= 4) p.outlined(GLYPHS.ask, pose.x + 20, pose.y - 11, WHITE);
  },

  pontificate(b, p, pose, t) {
    const ground = pose.y + 10;
    const k = Math.floor(t / 200);
    pose.y -= 3;
    pose.armR = k % 4 < 2 ? -4 : -2;
    pose.armL = k % 6 === 0 ? -1 : 0;
    pose.mouth = k % 2 ? 'O' : 'o';
    pose.look = [k % 8 < 4 ? -1 : 1, 0];
    P.soapbox(p, pose.x, ground);
    drawClawd(p, pose);
    if (k % 2) {
      p.rect(pose.x + 19, pose.y + 2, 1, 1, WHITE);
      p.rect(pose.x + 20, pose.y, 1, 1, WHITE);
      p.rect(pose.x + 20, pose.y + 4, 1, 1, WHITE);
    }
  },

  cook(b, p, pose, t) {
    pose.look = [0, 1];
    pose.armR = Math.floor(t / 180) % 2 ? 0 : 1;
    drawClawd(p, pose);
    P.chefHat(p, pose.x, top(pose));
    P.pot(p, pose.x, pose.y, t);
  },

  wizard(b, p, pose, t) {
    pose.armR = -3;
    pose.look = [1, -1];
    if (Math.floor(t / 300) % 4 === 3) pose.eyes = 'happy';
    drawClawd(p, pose);
    P.wizardHat(p, pose.x, top(pose));
    P.wand(p, pose.x, top(pose), t);
  },

  vibe(b, p, pose, t) {
    const k = Math.floor(t / 220) % 4;
    pose.x += [0, 1, 0, -1][k];
    pose.squash = k % 2;
    pose.armL = k < 2 ? -4 : 0;
    pose.armR = k < 2 ? 0 : -4;
    pose.legs = k % 2 ? [2, 2, 1, 2] : [2, 1, 2, 2];
    pose.eyes = 'none';
    drawClawd(p, pose);
    P.shades(p, pose.x, top(pose));
  },

  gears(b, p, pose, t) {
    pose.look = [0, -1];
    pose.squash = b.breath(700);
    drawClawd(p, pose);
    P.gears(p, pose.x, top(pose), t);
  },

  hatch(b, p, pose, t) {
    const cycle = t % 9000;
    pose.legs = [0, 0, 0, 0];
    pose.y += 2;
    pose.look = [1, 1];
    pose.armR = Math.floor(t / 400) % 2 ? 0 : 1;
    if (cycle > 7600) pose.eyes = 'happy';
    else if (cycle > 5200) pose.eyes = 'wide';
    drawClawd(p, pose);
    P.egg(p, pose.x + 19, GROUND, t);
  },

  spin(b, p, pose, t) {
    const k = Math.floor(t / 110);
    if (Math.floor(t / 2600) % 2) {
      pose.eyes = k % 2 ? 'x' : 'plus';
      pose.x += k % 2;
      drawClawd(p, pose);
      return;
    }
    pose.turn = k % 4;
    drawClawd(p, pose);
    p.rect(pose.x - 2, pose.y + 3 + (k % 2), 1, 1, WHITE, 0.7);
    p.rect(pose.x + 19, pose.y + 5 - (k % 2), 1, 1, WHITE, 0.7);
  },

  wander(b, p, pose, t) {
    if (!b.walking) pose.look = [Math.floor(t / 900) % 2 ? 1 : -1, 0];
    drawClawd(p, pose);
    if (/Spelunking|Burrowing/.test(b.verb)) P.lantern(p, pose.x, top(pose), t);
  },

  garden(b, p, pose, t) {
    pose.armR = -1;
    pose.look = [1, 1];
    drawClawd(p, pose);
    P.wateringCan(p, pose.x, top(pose), t);
    P.sprout(p, pose.x + 23, GROUND, t);
  },

  space(b, p, pose, t) {
    const lift = 3 + (Math.floor(t / 500) % 2);
    const a = t / 500;
    const behind = Math.sin(a) < 0;
    p.rect(pose.x + 4, GROUND - 1, 9, 1, '#000000', 0.22);
    pose.y -= lift;
    pose.legs = [1, 2, 1, 2];
    pose.armL = pose.armR = -2;
    const cx = pose.x + 8 + Math.round(Math.cos(a) * 12);
    const cy = pose.y + 4 + Math.round(Math.sin(a) * 2);
    if (behind) P.planet(p, cx, cy);
    drawClawd(p, pose);
    if (!behind) P.planet(p, cx, cy);
    [[-3, -4], [20, -2], [1, -9], [22, -8]].forEach(([sx, sy], i) => {
      if ((Math.floor(t / 300) + i) % 3) p.rect(pose.x + sx, pose.y + sy, 1, 1, WHITE);
    });
  },

  weather(b, p, pose, t) {
    const storm = /Thundering|Gusting|Precipitating/.test(b.verb);
    pose.look = [0, -1];
    pose.squash = b.breath(1000);
    if (storm && t % 2600 < 160) pose.eyes = 'wide';
    drawClawd(p, pose);
    P.rainCloud(p, pose.x, top(pose), t, storm);
  },

  doodle(b, p, pose, t) {
    pose.look = [0, 1];
    pose.armR = Math.floor(t / 150) % 2 ? 0 : 1;
    drawClawd(p, pose);
    P.sketchPad(p, pose.x, pose.y, t);
  },

  forge(b, p, pose, t) {
    const f = Math.floor(t / 160) % 2;
    pose.armR = f ? 0 : 1;
    pose.look = [1, 1];
    drawClawd(p, pose);
    P.wrench(p, pose.x, top(pose), f);
    P.robot(p, pose.x + 22, GROUND, t);
    if (f) {
      p.rect(pose.x + 21, top(pose) + 3, 1, 1, '#FFD54A');
      p.rect(pose.x + 22, top(pose) + 2, 1, 1, '#FFFFFF');
    }
  },
};

export const THINK_VIEWS = THINK;

// ---- scenes ------------------------------------------------------------

export const VIEWS = {
  idle(b, p, pose, t) {
    const a = b.act;
    const at = a ? b.now - a.at : 0;
    if (!b.walking) pose.squash = b.breath();
    switch (a?.name) {
      case 'look': {
        const seq = [[-1, 0], [-1, 0], [0, 0], [1, 0], [1, 0], [1, -1], [0, 0]];
        pose.look = seq[Math.min(seq.length - 1, Math.floor(at / 380))];
        break;
      }
      case 'hop': {
        const k = Math.floor(at / 70);
        pose.y -= [0, 1, 2, 3, 3, 2, 1, 0, 0, 0][Math.min(k, 9)];
        pose.squash = k === 0 || k === 8 ? 1 : 0;
        break;
      }
      case 'wave':
        pose.armR = Math.floor(at / 180) % 2 ? -4 : -2;
        pose.eyes = 'happy';
        break;
      case 'sit':
        pose.legs = [0, 0, 0, 0];
        pose.y += 2;
        pose.armL = pose.armR = 1;
        break;
      case 'stretch':
        pose.squash = -1;
        pose.armL = pose.armR = -4;
        if (at > 300 && at < 1000) pose.eyes = 'closed';
        break;
      case 'yawn':
        yawnPose(pose, at);
        break;
      case 'dance': {
        const k = Math.floor(at / 220) % 4;
        pose.x += [0, 1, 0, -1][k];
        pose.squash = k % 2;
        pose.armL = k < 2 ? -4 : 0;
        pose.armR = k < 2 ? 0 : -4;
        pose.legs = k % 2 ? [2, 2, 1, 2] : [2, 1, 2, 2];
        pose.eyes = 'happy';
        break;
      }
      case 'zoomies':
        pose.eyes = 'happy';
        pose.armL = pose.armR = -3;
        pose.squash = 0;
        break;
      case 'chase':
        if (!b.walking) {
          pose.legs = [0, 0, 0, 0];
          pose.y += 2;
          pose.look = [0, -1];
          pose.eyes = Math.floor(at / 700) % 3 === 2 ? 'happy' : pose.eyes;
        }
        break;
      case 'trip':
        if (at < 250) {
          pose.eyes = 'wide';
          pose.look = [1, 1];
        } else if (at < 1400) {
          pose.squash = 4;
          pose.eyes = 'x';
          pose.legs = [1, 1, 1, 1];
          pose.armL = pose.armR = 1;
        } else if (at < 1900) {
          pose.squash = 1;
          pose.eyes = 'blink';
        } else {
          pose.x += Math.floor(at / 80) % 2 ? 1 : -1;
        }
        break;
      case 'fly': {
        // Desktops that won't let the window move get a hop-flight inside the stage.
        const lift = Math.round(Math.sin((Math.PI * Math.min(at, 3200)) / 3200) * 7);
        pose.y -= lift;
        pose.armL = pose.armR = Math.floor(at / 90) % 2 ? -4 : 0;
        pose.legs = lift > 1 ? [1, 1, 1, 1] : pose.legs;
        pose.eyes = 'happy';
        break;
      }
      case 'sneeze':
        if (at < 900) {
          pose.squash = -1;
          pose.eyes = 'closed';
          pose.mouth = at > 400 ? 'O' : 'o';
        } else if (at < 1100) {
          pose.squash = 2;
          pose.eyes = 'squeeze';
          pose.x -= 1;
        } else {
          pose.eyes = 'blink';
        }
        break;
    }
    drawClawd(p, pose);
    drawWear(p, b.sky, pose.x, top(pose));
    if (a?.name === 'chase' && !b.walking) p.outlined(GLYPHS.heart, pose.x + 16, pose.y - 1 - (Math.floor(at / 300) % 2), '#F06A7A');
  },

  thinking(b, p, pose, t) {
    (THINK[b.style] ?? THINK.bubble)(b, p, pose, t);
  },

  building(b, p, pose, t) {
    const frame = b.walking ? 'up' : b.hammerTick(t, pose);
    const impact = frame === 'down' && t % 700 < 540;
    pose.squash = impact ? 1 : 0;
    pose.look = [1, frame === 'down' ? 1 : 0];
    pose.armR = { up: -3, mid: -1, down: 1 }[frame];
    drawClawd(p, pose);
    P.hardHat(p, pose.x, top(pose));
    P.hammer(p, pose.x, top(pose), frame);
    P.brickPile(p, pose.x, pose.y, b.bricks);
  },

  testing(b, p, pose, t) {
    pose.armR = -2;
    pose.look = [1, -1];
    drawClawd(p, pose);
    P.goggles(p, pose.x, top(pose));
    P.flask(p, pose.x, top(pose), t);
  },

  typing(b, p, pose, t) {
    const k = Math.floor(t / 110);
    if (!b.walking) {
      pose.look = [0, 1];
      pose.armL = k % 2 ? 1 : 0;
      pose.armR = k % 2 ? 0 : 1;
    }
    drawClawd(p, pose);
    P.laptop(p, pose.x, pose.y, t);
  },

  reading(b, p, pose, t) {
    pose.look = [[-1, 1], [0, 1], [1, 1], [0, 1]][Math.floor(t / 600) % 4];
    drawClawd(p, pose);
    P.book(p, pose.x, top(pose), t);
  },

  searching(b, p, pose, t) {
    const side = Math.floor(t / 1100) % 2;
    pose.look = [0, 0];
    pose.eyes = side ? ['open', 'big'] : ['big', 'open'];
    pose.armR = -1;
    drawClawd(p, pose);
    P.magnifier(p, pose.x + (side ? 12 : 4), top(pose) + 2);
    if (t % 3300 > 2300) p.outlined(GLYPHS.ask, pose.x + 7, pose.y - 7, WHITE);
  },

  surfing(b, p, pose, t) {
    const bob = P.surf(p, pose.x, pose.y, t);
    pose.y -= 1 + bob;
    pose.armL = -2;
    pose.armR = -1;
    pose.look = [1, 0];
    if (Math.floor(t / 1200) % 3 === 2) pose.eyes = 'happy';
    drawClawd(p, pose);
  },

  planning(b, p, pose, t) {
    pose.look = [0, 1];
    drawClawd(p, pose);
    P.clipboard(p, pose.x, top(pose), t);
  },

  delegating(b, p, pose, t) {
    pose.armR = null;
    pose.armL = Math.floor(t / 500) % 2 ? -3 : -1;
    pose.mouth = Math.floor(t / 250) % 2 ? 'O' : 'o';
    pose.look = [1, 0];
    drawClawd(p, pose);
    P.megaphone(p, pose.x, top(pose), t);
  },

  alert(b, p, pose, t) {
    const k = Math.floor(t / 150);
    const hopping = t % 2400 < 1200;
    if (hopping) pose.y -= [0, 2, 3, 2][k % 4];
    pose.armL = pose.armR = hopping && k % 2 ? -4 : -1;
    pose.eyes = 'wide';
    pose.look = [0, 0];
    drawClawd(p, pose);
    const { x: bx, side } = b.bubbleSpot(pose, 5);
    const by = pose.y - 10;
    p.bubble(bx, by, 5, 9);
    p.rect(side > 0 ? bx : bx + 4, by + 8, 1, 2, OUTLINE);
    p.bitmap(GLYPHS.bang, bx + 2, by + 2, '#E5484D');
  },

  waiting(b, p, pose, t) {
    pose.squash = b.breath(1200);
    pose.legs = [2, 2, 2, Math.floor(t / 280) % 2 ? 1 : 2];
    drawClawd(p, pose);
    drawWear(p, b.sky, pose.x, top(pose));
    const { x: bx } = b.bubbleSpot(pose, 9);
    const by = pose.y - 6;
    p.bubble(bx, by, 9, 5);
    const n = Math.floor(t / 450) % 4;
    for (let i = 0; i < n; i++) p.rect(bx + 2 + i * 2, by + 2, 1, 1, OUTLINE);
  },

  done(b, p, pose, t) {
    const ph = t % 3000;
    if (ph < 600) pose.y -= [0, 2, 3, 2, 1, 0][Math.floor(ph / 100)];
    pose.eyes = 'happy';
    pose.armR = -1;
    pose.armL = Math.floor(t / 300) % 2 ? -3 : 0;
    drawClawd(p, pose);
    P.doneSign(p, pose.x, top(pose), t);
  },

  remind(b, p, pose, t) {
    const k = Math.min(14, Math.floor(t / 100));
    pose.y -= [0, 2, 4, 5, 4, 2, 0, 0, 2, 4, 5, 4, 2, 0, 0][k];
    pose.eyes = 'wide';
    pose.armL = -4;
    pose.armR = -1;
    drawClawd(p, pose);
    P.doneSign(p, pose.x, top(pose), t);
  },

  compacting(b, p, pose, t) {
    const squash = [0, 1, 2, 3, 4, 3, 2, 1][Math.floor(t / 160) % 8];
    pose.squash = squash;
    pose.widen = Math.min(2, Math.floor(squash / 2));
    pose.eyes = squash > 1 ? 'squeeze' : 'open';
    pose.look = [0, 0];
    drawClawd(p, pose);
    P.press(p, pose.x, top(pose));
  },

  error(b, p, pose, t) {
    pose.eyes = 'sad';
    pose.look = [0, 1];
    pose.squash = 1;
    pose.armL = pose.armR = 1;
    drawClawd(p, pose);
    P.rainCloud(p, pose.x, top(pose), t, true);
  },

  sleeping(b, p, pose, t) {
    pose.legs = [0, 0, 0, 0];
    pose.y += 2;
    pose.squash = Math.floor(t / 1600) % 2 ? 2 : 1;
    pose.eyes = 'closed';
    pose.look = [0, 0];
    pose.armL = pose.armR = 1;
    drawClawd(p, pose);
    P.nightcap(p, pose.x, top(pose));
    P.snotBubble(p, pose.x, top(pose), t);
  },

  // ---- one-shot reactions ----

  // Hanging from the cursor: the body swings behind the motion and sways back.
  dragged(b, p, pose) {
    const k = Math.floor(b.now / 120) % 2;
    const lean = b.world?.dangle.lean ?? 0;
    pose.y -= 1;
    pose.x += Math.round(lean * 0.7);
    pose.legs = lean > 1.2 ? [2, 2, 3, 3] : lean < -1.2 ? [3, 3, 2, 2] : k ? [3, 2, 3, 2] : [2, 3, 2, 3];
    pose.armL = pose.armR = -4;
    pose.eyes = 'wide';
    pose.look = [0, 0];
    pose.mouth = 'o';
    drawClawd(p, pose);
  },

  flying(b, p, pose) {
    const flap = Math.floor(b.now / 90) % 2;
    const dir = b.world?.dir || 1;
    pose.armL = pose.armR = flap ? -4 : 0;
    pose.legs = [1, 1, 1, 1];
    pose.eyes = 'happy';
    pose.look = [dir, 0];
    pose.squash = flap ? 0 : 1;
    drawClawd(p, pose);
    const tail = dir > 0 ? pose.x - 2 : pose.x + 17;
    for (let i = 0; i < 3; i++) {
      p.rect(tail - dir * ((Math.floor(b.now / 60) + i * 2) % 5), pose.y + 2 + i * 3, 2, 1, WHITE, 0.7);
    }
  },

  // Tucked behind a screen edge with its hands on the rim. The window's rotation points
  // "up" into the screen, so the same pose works on every edge.
  peeking(b, p, pose, t) {
    const rim = b.world?.rim;
    const tuck = rim ? rim.tuck : b.stageRim?.tuck ?? 0;
    if (!rim) pose.y += Math.round(tuck * 10); // inside the stage on desktops that can't move it
    const out = tuck < 0.6;
    pose.armL = pose.armR = -4;
    pose.squash = 0;
    if (out) pose.look = [[-1, -1], [1, -1], [0, -1], [1, 0], [-1, 0]][Math.floor(t / 900) % 5];
    else pose.eyes = 'closed';
    drawClawd(p, pose);
  },

  // Hanging on to a window's side or the screen edge, turned toward it.
  clinging(b, p, pose) {
    const facing = b.world?.perch?.facing ?? 1;
    const sway = Math.floor(b.now / 600) % 2;
    pose.turn = facing > 0 ? 1 : 3;
    pose.x += facing * 3;
    pose.legs = [2, 2 + sway, 3 - sway, 2];
    if (facing > 0) pose.armR = -3;
    else pose.armL = -3;
    pose.look = [0, 0];
    drawClawd(p, pose);
  },

  falling(b, p, pose) {
    const k = Math.floor(b.now / 90) % 2;
    // Stretches out when dropping fast.
    if ((b.world?.vy ?? 0) / (b.world?.k || 1) > 200) pose.squash = -1;
    pose.legs = k ? [3, 2, 3, 2] : [2, 3, 2, 3];
    pose.armL = k ? -4 : -2;
    pose.armR = k ? -2 : -4;
    pose.eyes = 'wide';
    pose.look = [0, 0];
    pose.mouth = 'O';
    drawClawd(p, pose);
  },

  // Squash on touchdown, deeper for harder landings.
  land(b, p, pose, t) {
    const seq = { 1: [1, 0], 2: [2, 1, 0], 3: [3, 2, 1, 0] }[b.landPower] ?? [2, 1, 0];
    pose.squash = seq[Math.min(seq.length - 1, Math.floor(t / 110))];
    if (b.landPower > 1) pose.widen = pose.squash > 1 ? 1 : 0;
    if (t < 250) pose.eyes = b.landPower > 2 ? 'squeeze' : 'blink';
    drawClawd(p, pose);
  },

  // Skidding to a stop after a throw: leaning back, arms out, legs braced.
  sliding(b, p, pose) {
    const dir = Math.sign(b.world?.vx ?? 0) || 1;
    pose.look = [dir, 0];
    pose.squash = 1;
    pose.armL = dir > 0 ? -3 : 0;
    pose.armR = dir > 0 ? 0 : -3;
    pose.eyes = 'wide';
    pose.x -= dir;
    drawClawd(p, pose);
  },

  poke(b, p, pose, t) {
    pose.y -= [0, 2, 3, 2, 0, 0, 0, 0][Math.min(7, Math.floor(t / 80))];
    pose.eyes = 'happy';
    pose.armL = pose.armR = -2;
    drawClawd(p, pose);
  },

  giggle(b, p, pose, t) {
    pose.x += Math.floor(t / 80) % 2 ? 1 : -1;
    pose.eyes = 'happy';
    pose.squash = Math.floor(t / 160) % 2;
    drawClawd(p, pose);
  },

  notice(b, p, pose, t) {
    if (t < 300) pose.y -= [0, 2, 3][Math.floor(t / 100)];
    pose.eyes = 'wide';
    drawClawd(p, pose);
    p.outlined(GLYPHS.bang, pose.x + 8, pose.y - 7, '#F6C945');
  },

  hello(b, p, pose, t) {
    pose.armR = Math.floor(t / 170) % 2 ? -4 : -2;
    pose.eyes = 'happy';
    if (t < 400) pose.y -= [0, 2, 3, 1][Math.floor(t / 100)];
    drawClawd(p, pose);
    if (t > 300) p.outlined(GLYPHS.sparkle, pose.x + 19, pose.y - 1, '#F6C945');
  },

  celebrate(b, p, pose, t) {
    const k = Math.floor(t / 90) % 10;
    pose.y -= [0, 2, 4, 5, 5, 4, 2, 0, 0, 0][k];
    pose.squash = k >= 7 ? 1 : 0;
    pose.eyes = 'happy';
    pose.armL = pose.armR = -4;
    drawClawd(p, pose);
  },

  shrug(b, p, pose, t) {
    pose.armL = pose.armR = -3;
    pose.eyes = t < 400 ? 'wide' : 'open';
    pose.look = [0, 0];
    pose.mouth = 'w';
    drawClawd(p, pose);
    p.outlined(GLYPHS.ask, pose.x + 7, pose.y - 7, WHITE);
  },

  oops(b, p, pose, t) {
    pose.eyes = 'x';
    pose.squash = t < 200 ? 2 : 0;
    drawClawd(p, pose);
    const tp = top(pose);
    p.rect(pose.x + 5, tp + 5, 1, 1, '#3B3B3B');
    p.rect(pose.x + 11, tp + 4, 1, 1, '#3B3B3B');
    p.rect(pose.x + 8, tp + 6, 1, 1, '#3B3B3B');
    const rise = Math.floor(t / 150);
    for (let i = 0; i < 5; i++) {
      p.rect(pose.x + 3 + i * 2 + (i % 2), tp - 2 - rise - (i % 2), 2, 2, '#6B6B6B', Math.max(0, 1 - t / 1100));
    }
  },

  // ---- gestures ----

  // Three stones, one after another: wind up, throw, follow through.
  stones(b, p, pose, t) {
    const k = t - 200;
    const throws = Math.floor(k / 1200);
    const ph = ((k % 1200) + 1200) % 1200;
    if (throws < 3 && k >= 0 && ph < 500) {
      pose.armR = -4;
      pose.x -= 1;
      pose.eyes = 'squeeze';
      pose.look = [1, 0];
    } else if (throws < 3 && k >= 0 && ph < 750) {
      pose.armR = 0;
      pose.x += 1;
      pose.look = [1, 0];
      pose.eyes = 'happy';
    } else {
      pose.look = [1, 0];
    }
    drawClawd(p, pose);
    if (throws < 3 && k >= 0 && ph < 500) p.rect(pose.x + 17, top(pose), 1, 1, '#8D8A84');
  },

  kick(b, p, pose, t) {
    pose.look = [1, 1];
    if (t < 600) {
      p.rect(pose.x + 17, GROUND - 2, 2, 2, '#F2F2EE');
      p.rect(pose.x + 17, GROUND - 2, 1, 1, '#E5484D');
    } else if (t < 900) {
      pose.legs = [2, 2, 2, 1];
      pose.x -= 1;
      pose.armL = -2;
      p.rect(pose.x + 18, GROUND - 2, 2, 2, '#F2F2EE');
    } else if (t < 1200) {
      pose.legs = [2, 2, 1, 2];
      pose.x += 1;
      pose.armR = -3;
      pose.eyes = 'squeeze';
    } else {
      pose.eyes = 'happy';
      pose.armL = pose.armR = Math.floor(t / 200) % 2 ? -4 : -1;
    }
    drawClawd(p, pose);
  },

  // Three balls passed from hand to hand in a fountain.
  juggle(b, p, pose, t) {
    const colors = ['#E5484D', '#F6C945', '#3F8EDB'];
    const beat = t / 700;
    pose.armL = Math.floor(beat) % 2 ? -2 : 0;
    pose.armR = Math.floor(beat) % 2 ? 0 : -2;
    pose.look = [0, -1];
    drawClawd(p, pose);
    const tp = top(pose);
    for (let i = 0; i < 3; i++) {
      const cycle = beat + (i * 2) / 3;
      const ph = cycle % 1;
      const leftToRight = Math.floor(cycle) % 2 === 0;
      const from = leftToRight ? pose.x + 1 : pose.x + 15;
      const to = leftToRight ? pose.x + 15 : pose.x + 1;
      const bx = from + (to - from) * ph;
      const by = tp + 3 - Math.sin(Math.PI * ph) * 10;
      p.rect(bx, by, 1, 1, colors[i]);
    }
  },

  flex(b, p, pose, t) {
    const pump = Math.floor(t / 400) % 2;
    pose.armL = pose.armR = -4;
    pose.squash = pump ? -1 : 0;
    pose.eyes = 'happy';
    pose.mouth = 'w';
    drawClawd(p, pose);
    const tp = top(pose);
    p.rect(pose.x, tp - 1 - pump, 2, 1, pose.color);
    p.rect(pose.x + 15, tp - 1 - pump, 2, 1, pose.color);
  },

  kiss(b, p, pose, t) {
    if (t < 850) {
      pose.armR = -1;
      pose.eyes = 'closed';
      pose.mouth = 'o';
    } else {
      pose.armR = -4;
      pose.eyes = 'happy';
    }
    drawClawd(p, pose);
  },

  // A desktop notification: hop up holding the letter.
  mail(b, p, pose, t) {
    if (t < 400) pose.y -= [0, 2, 3, 1][Math.floor(t / 100)];
    pose.armL = pose.armR = -4;
    pose.eyes = t < 600 ? 'wide' : 'happy';
    pose.look = [0, -1];
    drawClawd(p, pose);
    P.envelope(p, pose.x, top(pose));
  },

  wake(b, p, pose, t) {
    if (t < 600) {
      pose.legs = [0, 0, 0, 0];
      pose.y += 2;
      pose.eyes = Math.floor(t / 150) % 2 ? 'closed' : 'blink';
    } else {
      yawnPose(pose, t - 600);
    }
    drawClawd(p, pose);
  },

  yawn(b, p, pose, t) {
    yawnPose(pose, t);
    drawClawd(p, pose);
  },

  dizzy(b, p, pose, t) {
    pose.x += Math.floor(t / 200) % 2 ? 1 : 0;
    pose.eyes = Math.floor(t / 150) % 2 ? 'x' : 'plus';
    pose.look = [0, 0];
    drawClawd(p, pose);
    for (let i = 0; i < 3; i++) {
      const a = t / 180 + (i * Math.PI * 2) / 3;
      p.rect(pose.x + 8 + Math.round(Math.cos(a) * 6), pose.y - 2 + Math.round(Math.sin(a) * 1.5), 1, 1, '#F6C945');
    }
  },
};
