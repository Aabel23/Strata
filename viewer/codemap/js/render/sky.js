import { BOUNDS as b } from '../camera.js';
const NS = 'http://www.w3.org/2000/svg';
const el = (tag, a = {}) => { const n = document.createElementNS(NS, tag); for (const k in a) n.setAttribute(k, a[k]); return n; };

// Faint background grid (no frame, rulers or labels) and the core glow.
export function buildSky() {
  const grid = document.getElementById('grid'), glow = document.getElementById('core-glow');
  for (let h = -24; h <= 48; h++) {
    const x = b.left + (b.right - b.left) * h / 24;
    grid.append(el('line', { x1: x, y1: -1200, x2: x, y2: 2400, class: h % 3 === 0 ? 'major-grid' : 'minor-grid' }));
  }
  for (let i = -180; i <= 360; i += 10) {
    const y = b.top + (b.bottom - b.top) * i / 180;
    grid.append(el('line', { x1: -2400, y1: y, x2: 4800, y2: y, class: i === 90 ? 'equator' : i % 30 === 0 ? 'major-grid' : 'minor-grid' }));
  }
  return {
    world: document.getElementById('sky-world'),
    setGlow(t) { glow.setAttribute('rx', 8 + 220 * t); glow.setAttribute('ry', 5 + 125 * t); glow.setAttribute('opacity', t === 0 ? 0 : .36 * Math.sqrt(t)); },
  };
}
