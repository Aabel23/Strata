import { prepare } from './canvas.js';
import { KEYS, keyStyle } from './scene.js';

const STYLES = Array.from({ length: KEYS }, (_, k) => keyStyle(k));
const TAU = Math.PI * 2;

// One fill per (community, density level) key. hover/sel: node index or -1; nbr: Uint8Array mark of sel's neighbours.
export function drawStars(canvas, cam, s, hover, sel, nbr) {
  const ctx = prepare(canvas, cam), { x, y, r } = s, px = 1 / (cam.s0 * cam.scale);
  const { x0, x1, y0, y1 } = cam.vis; // star radii are small; a 12px margin in chart units is enough
  const m = 12 * px, ax0 = x0 - m, ax1 = x1 + m, ay0 = y0 - m, ay1 = y1 + m;
  const dim = sel >= 0 ? 0.55 : 1;
  for (let k = 0; k < KEYS; k++) {
    const g = s.groups[k];
    if (!g.length) continue;
    ctx.fillStyle = STYLES[k].fill; ctx.globalAlpha = STYLES[k].alpha * dim;
    ctx.beginPath();
    for (let j = 0; j < g.length; j++) {
      const i = g[j], xi = x[i], yi = y[i];
      if (xi < ax0 || xi > ax1 || yi < ay0 || yi > ay1) continue;
      ctx.moveTo(xi + r[i], yi); ctx.arc(xi, yi, r[i], 0, TAU);
    }
    ctx.fill();
  }
  ctx.globalAlpha = 1;
  // glow on the highest-degree stars (constant on-screen blur, so only ~60 shadowed fills)
  ctx.shadowColor = 'rgba(255,218,152,.8)'; ctx.shadowBlur = 6 * (window.devicePixelRatio || 1);
  ctx.fillStyle = '#ffe3ae'; ctx.beginPath();
  for (const i of s.luminous) { if (s.r[i] > 2.4) { ctx.moveTo(x[i] + r[i], y[i]); ctx.arc(x[i], y[i], r[i], 0, TAU); } }
  ctx.fill(); ctx.shadowBlur = 0;
  if (sel >= 0) {
    ctx.fillStyle = '#f4dcae'; ctx.beginPath();
    for (let i = 0; i < s.n; i++) if (nbr[i]) { ctx.moveTo(x[i] + r[i] + px, y[i]); ctx.arc(x[i], y[i], r[i] + px, 0, TAU); }
    ctx.fill();
  }
  ctx.fillStyle = '#fff1ca'; ctx.beginPath();
  for (const i of [sel, hover]) if (i >= 0) { ctx.moveTo(x[i] + r[i] + px, y[i]); ctx.arc(x[i], y[i], r[i] + px, 0, TAU); }
  ctx.fill();
}
