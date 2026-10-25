import { BOUNDS as b } from '../camera.js';
const NS = 'http://www.w3.org/2000/svg';
const el = (tag, a = {}) => { const n = document.createElementNS(NS, tag); for (const k in a) n.setAttribute(k, a[k]); return n; };
function text(parent, x, y, s, cls, anchor = 'middle') { const n = el('text', { x, y, class: cls, 'text-anchor': anchor }); n.textContent = s; parent.append(n); return n; }

// Ported from the study's buildChart: grid, rulers, frame, RA/Dec labels. No figures, no synthetic stars.
export function buildSky() {
  const grid = document.getElementById('grid'), rulers = document.getElementById('rulers'), glow = document.getElementById('core-glow');
  rulers.append(el('rect', { x: b.left, y: b.top, width: b.right - b.left, height: b.bottom - b.top, class: 'plot-frame' }));
  for (let h = 0; h <= 24; h++) {
    const x = b.left + (b.right - b.left) * h / 24;
    grid.append(el('line', { x1: x, y1: b.top, x2: x, y2: b.bottom, class: h % 3 === 0 ? 'major-grid' : 'minor-grid' }));
    if (h < 24) { text(rulers, x, 62, String(h).padStart(2, '0'), 'axis-text'); text(rulers, x, 1148, String(h).padStart(2, '0'), 'axis-text'); }
  }
  for (let i = 0; i <= 180; i += 10) {
    const y = b.top + (b.bottom - b.top) * i / 180;
    grid.append(el('line', { x1: b.left, y1: y, x2: b.right, y2: y, class: i === 90 ? 'equator' : i % 30 === 0 ? 'major-grid' : 'minor-grid' }));
    const label = `${i <= 90 ? '+' : '−'}${String(Math.abs(90 - i)).padStart(2, '0')}°`;
    text(rulers, 60, y + 4, label, 'axis-text', 'end'); text(rulers, 2340, y + 4, label, 'axis-text', 'start');
  }
  const tick = (i, major) => (major ? 12 : i % 5 === 0 ? 8 : 4);
  for (let i = 0; i <= 240; i++) {
    const x = b.left + (b.right - b.left) * i / 240, hgt = tick(i, i % 10 === 0), cls = i % 10 === 0 ? 'axis-mark' : 'axis-minor';
    rulers.append(el('line', { x1: x, y1: b.top, x2: x, y2: b.top + hgt, class: cls }), el('line', { x1: x, y1: b.bottom, x2: x, y2: b.bottom - hgt, class: cls }));
  }
  for (let i = 0; i <= 180; i++) {
    const y = b.top + (b.bottom - b.top) * i / 180, w = tick(i, i % 10 === 0), cls = i % 10 === 0 ? 'axis-mark' : 'axis-minor';
    rulers.append(el('line', { x1: b.left, y1: y, x2: b.left + w, y2: y, class: cls }), el('line', { x1: b.right, y1: y, x2: b.right - w, y2: y, class: cls }));
  }
  text(rulers, 1200, 1180, 'RIGHT ASCENSION  ·  HOURS', 'axis-caption');
  text(rulers, 23, 600, 'DECLINATION', 'axis-caption').setAttribute('transform', 'rotate(-90 23 600)');
  return {
    world: document.getElementById('sky-world'),
    setGlow(t) { glow.setAttribute('rx', 8 + 220 * t); glow.setAttribute('ry', 5 + 125 * t); glow.setAttribute('opacity', t === 0 ? 0 : .36 * Math.sqrt(t)); },
  };
}
