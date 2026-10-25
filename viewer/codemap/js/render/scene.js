// Typed-array scene built once per graph: positions, radii, colour classes, edges, adjacency, hit grid.
import { BOUNDS } from '../camera.js';

import { PALETTE, GOLD } from './palette.js';
const LEVELS = 4, CELL = 30, COLS = Math.ceil(2400 / CELL), ROWS = Math.ceil(1200 / CELL);
const M = 3, MIN_X = BOUNDS.left + M, MIN_Y = BOUNDS.top + M, SPAN_X = BOUNDS.right - BOUNDS.left - 2 * M, SPAN_Y = BOUNDS.bottom - BOUNDS.top - 2 * M;
export const GRAVITY_MAX = 0.8, MAX_WARP = 0.35;

// The study's bounded cubic warp: centre density rises, edge density falls.
function pull(v, start, span, k) {
  const u = (v - start) / span;
  if (u <= 0 || u >= 1) return v;
  const d = u - 0.5;
  return start + span * (u - k * d * (1 - 4 * d * d));
}

const hex = (c) => [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16));
// key = colourClass*LEVELS + densityLevel; fill/alpha precomputed so drawing is one fill per key
export function keyStyle(key) {
  const cls = Math.floor(key / LEVELS), lvl = key % LEVELS;
  const base = hex(cls < PALETTE.length ? PALETTE[cls] : GOLD), t = lvl / (LEVELS - 1) * 0.75, cream = [255, 237, 197];
  const c = base.map((v, i) => Math.round(v + (cream[i] - v) * t));
  return { fill: `rgb(${c[0]},${c[1]},${c[2]})`, alpha: 0.62 + 0.38 * lvl / (LEVELS - 1) };
}
export const KEYS = (PALETTE.length + 1) * LEVELS;

export function buildScene(graph, pos) {
  const n = graph.nodes.length, idx = new Map(graph.nodes.map((nd, i) => [nd.id, i]));
  const bx = new Float32Array(n), by = new Float32Array(n), r = new Float32Array(n), cls = new Uint8Array(n);
  const size = new Map();
  for (const nd of graph.nodes) if (nd.community != null) size.set(nd.community, (size.get(nd.community) ?? 0) + 1);
  const rank = new Map([...size].sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1)).map(([name], i) => [name, i]));
  graph.nodes.forEach((nd, i) => {
    const p = pos.get(nd.id) ?? { x: 1200, y: 600 };
    bx[i] = p.x; by[i] = p.y; r[i] = 0.85 + 1.5 * Math.log1p(nd.degree);
    cls[i] = nd.community == null ? PALETTE.length : rank.get(nd.community) % PALETTE.length;
  });

  const m = graph.edges.length, es = new Int32Array(m), et = new Int32Array(m), types = graph.edgeTypes;
  const tIdx = new Map(types.map((t, i) => [t, i])), counts = new Int32Array(types.length), off = new Int32Array(n + 1);
  graph.edges.forEach((e, i) => { es[i] = idx.get(e.source); et[i] = idx.get(e.target); counts[tIdx.get(e.type)]++; off[es[i] + 1]++; off[et[i] + 1]++; });
  const edgeType = Uint8Array.from(graph.edges, (e) => tIdx.get(e.type));
  const byType = types.map((_, t) => new Int32Array(counts[t]));
  const fill = new Int32Array(types.length);
  edgeType.forEach((t, i) => { byType[t][fill[t]++] = i; });
  for (let i = 0; i < n; i++) off[i + 1] += off[i];
  const adj = new Int32Array(2 * m), cur = off.slice(0, n);
  for (let i = 0; i < m; i++) { adj[cur[es[i]]++] = i; adj[cur[et[i]]++] = i; }

  const order = Array.from({ length: n }, (_, i) => i).sort((a, b) => graph.nodes[b].degree - graph.nodes[a].degree);
  const s = { n, graph, idx, bx, by, x: bx.slice(), y: by.slice(), r, cls, level: new Uint8Array(n), groups: [],
    es, et, edgeType, byType, off, adj, head: new Int32Array(COLS * ROWS), next: new Int32Array(n), luminous: order.slice(0, Math.min(60, n)) };
  refresh(s);
  return s;
}

export function applyGravity(s, strength) {
  const k = MAX_WARP * Math.min(1, Math.max(0, strength / GRAVITY_MAX));
  for (let i = 0; i < s.n; i++) {
    s.x[i] = k ? pull(s.bx[i], MIN_X, SPAN_X, k) : s.bx[i];
    s.y[i] = k ? pull(s.by[i], MIN_Y, SPAN_Y, k) : s.by[i];
  }
  refresh(s);
}

// hit grid + density brightness (the study's updateDensityBrightness) + per-key draw groups
function refresh(s) {
  const { n, x, y, head, next } = s;
  head.fill(-1);
  const occ = new Uint32Array(COLS * ROWS);
  const cell = (v, max) => Math.max(0, Math.min(max - 1, Math.floor(v / CELL)));
  for (let i = 0; i < n; i++) { const c = cell(y[i], ROWS) * COLS + cell(x[i], COLS); next[i] = head[c]; head[c] = i; occ[c]++; }
  const near = new Float32Array(COLS * ROWS);
  for (let cy = 0; cy < ROWS; cy++) for (let cx = 0; cx < COLS; cx++) {
    let c = 0;
    for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
      const nx = cx + dx, ny = cy + dy;
      if (nx >= 0 && nx < COLS && ny >= 0 && ny < ROWS) c += occ[ny * COLS + nx] * (dx === 0 && dy === 0 ? 1 : dx === 0 || dy === 0 ? .4 : .2);
    }
    near[cy * COLS + cx] = c;
  }
  // shortcut: nearest-cell density (no bilinear blend), fine at CELL=30; upgrade if banding shows
  const cnt = new Int32Array(KEYS);
  for (let i = 0; i < n; i++) {
    const d = near[cell(y[i], ROWS) * COLS + cell(x[i], COLS)], boost = 1 - Math.exp(-Math.max(0, d - 4) / 18);
    s.level[i] = Math.min(LEVELS - 1, Math.floor(boost * LEVELS));
    cnt[s.cls[i] * LEVELS + s.level[i]]++;
  }
  s.groups = Array.from(cnt, (c) => new Int32Array(c));
  cnt.fill(0);
  for (let i = 0; i < n; i++) { const k = s.cls[i] * LEVELS + s.level[i]; s.groups[k][cnt[k]++] = i; }
}

// nearest node within `rad` chart units of (px,py), or -1
export function hit(s, px, py, rad) {
  const c0 = Math.max(0, Math.floor((px - rad) / CELL)), c1 = Math.min(COLS - 1, Math.floor((px + rad) / CELL));
  const r0 = Math.max(0, Math.floor((py - rad) / CELL)), r1 = Math.min(ROWS - 1, Math.floor((py + rad) / CELL));
  let best = -1, bd = rad * rad;
  for (let cy = r0; cy <= r1; cy++) for (let cx = c0; cx <= c1; cx++)
    for (let i = s.head[cy * COLS + cx]; i >= 0; i = s.next[i]) {
      const d = (s.x[i] - px) ** 2 + (s.y[i] - py) ** 2;
      if (d < bd) { bd = d; best = i; }
    }
  return best;
}

// top-N neighbours by degree (unique), as node indices
export function neighbours(s, i, limit = 12) {
  const set = new Set();
  for (let k = s.off[i]; k < s.off[i + 1]; k++) { const e = s.adj[k]; set.add(s.es[e] === i ? s.et[e] : s.es[e]); }
  return [...set].sort((a, b) => s.graph.nodes[b].degree - s.graph.nodes[a].degree).slice(0, limit);
}
