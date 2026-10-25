import { prepare } from './canvas.js';
import { edgeColor } from './palette.js';

// One path per edge type. enabled: Uint8Array per type. sel: selected node index or -1.
// While the camera moves (cam.busy) every 3rd edge is drawn, a bit brighter; full detail on idle.
export function drawEdges(canvas, cam, s, enabled, sel) {
  const ctx = prepare(canvas, cam), px = 1 / (cam.s0 * cam.scale), { x, y, es, et } = s;
  const { x0, x1, y0, y1 } = cam.vis, stride = cam.busy ? 3 : 1;
  ctx.lineWidth = 0.9 * px;
  for (let t = 0; t < s.byType.length; t++) {
    if (!enabled[t]) continue;
    ctx.strokeStyle = edgeColor(s.graph.edgeTypes[t], t);
    ctx.globalAlpha = (sel >= 0 ? 0.04 : 0.13) * (stride > 1 ? 1.6 : 1);
    ctx.beginPath();
    const list = s.byType[t];
    for (let j = 0; j < list.length; j += stride) {
      const a = es[list[j]], b = et[list[j]], ax = x[a], bx = x[b], ay = y[a], by = y[b];
      // skip an edge only when both ends are off the same side of the view
      if ((ax < x0 && bx < x0) || (ax > x1 && bx > x1) || (ay < y0 && by < y0) || (ay > y1 && by > y1)) continue;
      ctx.moveTo(ax, ay); ctx.lineTo(bx, by);
    }
    ctx.stroke();
  }
  if (sel < 0) return;
  ctx.lineWidth = 1.4 * px; ctx.globalAlpha = 0.9;
  for (let t = 0; t < s.byType.length; t++) {
    if (!enabled[t]) continue;
    ctx.strokeStyle = edgeColor(s.graph.edgeTypes[t], t); ctx.beginPath();
    for (let k = s.off[sel]; k < s.off[sel + 1]; k++) {
      const e = s.adj[k];
      if (s.edgeType[e] === t) { ctx.moveTo(x[es[e]], y[es[e]]); ctx.lineTo(x[et[e]], y[et[e]]); }
    }
    ctx.stroke();
  }
}
