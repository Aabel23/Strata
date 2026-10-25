import Graph from '../vendor/graphology.mjs';
import forceAtlas2 from '../vendor/graphology-layout-forceatlas2.mjs';

// seeded PRNG (mulberry32): same seed, same initial positions
function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// ~constant budget: cost per iteration grows with n (Barnes-Hut), so fewer iterations for big graphs
const defaultIterations = (n) => Math.max(40, Math.min(300, Math.round(300000 / n)));

export function layoutSync(graph, { iterations, width = 2400, height = 1200, margin = 80, seed = 1 } = {}) {
  const nodes = graph.nodes.map((n) => n.id).sort();
  const out = new Map();
  if (!nodes.length) return out;
  const rand = rng(seed);
  const g = new Graph({ type: 'undirected', multi: false });
  for (const id of nodes) g.addNode(id, { x: rand() * 1000, y: rand() * 1000 });
  for (const e of graph.edges) if (!g.hasEdge(e.source, e.target)) g.addEdge(e.source, e.target);

  const n = nodes.length;
  if (n > 1) {
    forceAtlas2.assign(g, {
      iterations: iterations ?? defaultIterations(n),
      settings: { ...forceAtlas2.inferSettings(g), barnesHutOptimize: n > 500, slowDown: 5 },
    });
  }

  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  for (const id of nodes) {
    const { x, y } = g.getNodeAttributes(id);
    x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y);
  }
  const fit = (v, lo, hi, size) => (hi > lo ? margin + ((v - lo) / (hi - lo)) * (size - 2 * margin) : size / 2);
  for (const id of nodes) {
    const { x, y } = g.getNodeAttributes(id);
    out.set(id, { x: fit(x, x0, x1, width), y: fit(y, y0, y1, height) });
  }
  return out;
}

export function layout(graph, opts = {}) {
  return new Promise((resolve, reject) => {
    const w = new Worker(new URL('./layout.worker.js', import.meta.url), { type: 'module' });
    w.onmessage = (e) => { w.terminate(); resolve(new Map(e.data)); };
    w.onerror = (e) => { w.terminate(); reject(new Error(e.message || 'layout worker failed')); };
    w.postMessage({ graph: { nodes: graph.nodes.map((n) => ({ id: n.id })), edges: graph.edges }, opts });
  });
}
