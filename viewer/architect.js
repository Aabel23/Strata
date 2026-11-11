/* Architecture designer: a direct-manipulation editor for the project's C4 map and its flows.
   Reads GET /api/c4, writes only through POST /api/c4/edit (one op or a batch per user action).
   All model text reaches the page through textContent / attributes, never innerHTML. */
"use strict";
const Q = new URLSearchParams(location.search), PROJECT = Q.get("project") || "";
const PQ = PROJECT ? "?project=" + encodeURIComponent(PROJECT) : "";
const $ = s => document.querySelector(s);
const NS = "http://www.w3.org/2000/svg";

function build(el, attrs, kids) {
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "text") el.textContent = v;
    else if (k in el && !(el instanceof SVGElement)) el[k] = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat(Infinity)) if (c != null && c !== false) el.append(c);
  return el;
}
const h = (tag, attrs, ...kids) => build(document.createElement(tag), attrs, kids);
const s = (tag, attrs, ...kids) => build(document.createElementNS(NS, tag), attrs, kids);

/* ---------- model ---------- */
const KIND = {
  actor: { label: "Actor", icon: '<circle cx="10" cy="6" r="3.5"/><path d="M3 18c1-4 4-6 7-6s6 2 7 6"/>' },
  system: { label: "System", icon: '<rect x="2" y="3" width="16" height="14" rx="2"/><path d="M2 7h16"/>' },
  app: { label: "App", icon: '<rect x="2" y="2" width="7" height="7" rx="1"/><rect x="11" y="2" width="7" height="7" rx="1"/><rect x="2" y="11" width="7" height="7" rx="1"/><rect x="11" y="11" width="7" height="7" rx="1"/>' },
  store: { label: "Data store", icon: '<ellipse cx="10" cy="4.5" rx="7" ry="2.5"/><path d="M3 4.5v11c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5v-11M3 10c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5"/>' },
  component: { label: "Component", icon: '<path d="M10 2l7 4v8l-7 4-7-4V6z"/><path d="M3 6l7 4 7-4M10 10v8"/>' },
  group: { label: "Group", icon: '<rect x="2" y="2" width="16" height="16" rx="2" stroke-dasharray="3 2"/>' },
};
// What may be placed inside what ("" = the top level). The server only warns about level order; the palette guides.
const CHILD = { "": ["actor", "system", "group"], system: ["app", "store", "group"], app: ["component", "group"], group: ["actor", "system", "app", "store", "component", "group"], actor: [], store: [], component: [] };
const LEVEL = { "": "System context", system: "Containers", app: "Components", group: "Group" };
const STATUS = { live: "Live", future: "Planned", doing: "In progress", maintenance: "Maintenance", deprecated: "Deprecated", removed: "Removed" };

let M = null, by = {}, focus = null, V = null;            // model, objects by id, object whose inside is shown, current view
let sel = new Set(), selEdge = null, selConn = null;      // selected cards; selected arrow (a→b) and the single link picked on it
let cam = { x: 0, y: 0, k: 1 };
let tab = "props", flowId = null, stepIx = -1, adding = false;
let undo = [], redo = [], findings = null, TOKEN = null;

const kids = id => M.objects.filter(o => (o.parent || null) === id);
const chain = id => { const r = []; for (let o = by[id]; o; o = by[o.parent]) r.unshift(o.id); return r; };
const nm = id => by[id]?.name || id;
const path = id => chain(id).map(nm).join(" › ");
const conn = id => M.connections.find(c => c.id === id);
const viewKey = () => focus || "_root";
const stepLink = st => st.link || st.connection;
const cleanStep = st => Object.fromEntries(Object.entries({ link: stepLink(st), at: st.at, text: st.text, reverse: st.reverse, values: st.values, transition: st.transition }).filter(([, v]) => v != null && v !== false && v !== ""));
const curFlow = () => M && (M.flows || []).find(f => f.id === flowId);

function slug(text, taken) {
  const base = text.normalize("NFKD").replace(/[^\x00-\x7f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "") || "object";
  let out = base, n = 2; while (taken.has(out)) out = `${base}_${n++}`;
  return out;
}
// The op-shaped copy of an object / link (the read model says type/description, edits say kind/summary).
const objOp = o => Object.fromEntries(Object.entries({ id: o.id, name: o.name, kind: o.type, parent: o.parent, summary: o.description, tech: o.tech, status: o.status, tags: o.tags, owns: o.owns }).filter(([, v]) => v != null));
const linkOp = c => Object.fromEntries(Object.entries({ id: c.id, from: c.from, to: c.to, name: c.name, summary: c.description, detail: c.detail, status: c.status }).filter(([, v]) => v != null));
const OBJ_FIELD = { name: "name", kind: "type", summary: "description", tech: "tech", status: "status", tags: "tags", owns: "owns", parent: "parent" };
const LINK_FIELD = { name: "name", summary: "description", status: "status", from: "from", to: "to" };

function adopt(model) {
  M = { ...(M || {}), ...model, positions: model.positions || {}, flows: model.flows || [], objects: model.objects || [], connections: model.connections || [] };
  M.links = M.links || {}; M.open_issues = M.open_issues || []; M.contracts = M.contracts || {};
  by = {}; M.objects.forEach(o => by[o.id] = o);
  if (focus && !by[focus]) focus = null;
  sel = new Set([...sel].filter(id => by[id]));
  if (selConn && !conn(selConn)) selConn = selEdge = null;
  if (flowId && !curFlow()) { flowId = null; adding = false; }
  $("#findlist").replaceChildren(...M.objects.map(o => h("option", { value: o.name || o.id })));
}

/* ---------- server ---------- */
async function post(op) {
  try {
    if (!TOKEN) TOKEN = (await (await fetch("/api/session")).json()).token;
    const r = await fetch("/api/c4/edit" + PQ, { method: "POST", headers: { "Content-Type": "application/json", "X-Strata-Edit": "1", "X-Strata-Token": TOKEN }, body: JSON.stringify(op) });
    const d = await r.json().catch(() => ({}));
    return r.ok ? { ok: true, d } : { error: d.error || `Server answered ${r.status}` };
  } catch { return { error: "Could not reach the server." }; }
}
async function reload() {
  const r = await fetch("/api/c4" + PQ);
  if (r.status === 404) { M = null; return false; }
  if (!r.ok) throw new Error(`Could not load the map (${r.status}).`);
  const d = await r.json();
  adopt({ ...d, name: d.meta?.name });
  return true;
}
async function check() {
  try { const r = await fetch("/api/c4/check" + PQ); findings = r.ok ? await r.json() : null; } catch { findings = null; }
  const n = findings ? findings.errors.length + findings.warnings.length : 0;
  $("#nissues").textContent = n || "";
  if (tab === "issues") renderPanel();
}
// One user action = one op (often a batch) plus the op that undoes it.
async function commit(op, inv) {
  let r = await post(op);
  if (r.error && /pass yes to accept/.test(r.error) && await ask("This also removes task links to the deleted blocks.", "Delete anyway")) r = await post({ ...op, yes: true });
  if (r.error) { toast(r.error); await reload().catch(() => {}); refresh(); return false; }
  adopt(r.d.model); undo.push({ op, inv }); redo = [];
  refresh(); check();
  return true;
}
async function travel(from, to, key) {
  const u = from.pop(); if (!u) return;
  const r = await post(u[key]);
  if (r.error) { toast(r.error); from.push(u); return; }
  adopt(r.d.model); to.push(u); refresh(); check();
}

/* ---------- view: which cards and arrows the current level shows, and where ---------- */
const W = 232, H = 104, GRID = 10, FAR = .5;   // below FAR zoom, cards switch to name-only
// The card that stands for object `id` on level F: itself or an ancestor inside F, else (ext) the nearest relative outside F.
function lift(id, F) {
  const anc = new Set(F ? chain(F) : []);
  for (let o = by[id]; o; o = by[o.parent]) {
    const p = o.parent || null;
    if (p === F) return { id: o.id, ext: false };
    if (p === null || anc.has(p)) return anc.has(o.id) ? null : { id: o.id, ext: true };
  }
  return null;
}
function buildView(F) {
  const nodes = new Map(), edges = new Map();
  kids(F).forEach(o => nodes.set(o.id, { o, ext: false }));
  for (const c of M.connections) {
    const a = lift(c.from, F), b = lift(c.to, F);
    if (!a || !b || a.id === b.id || (a.ext && b.ext)) continue;
    for (const x of [a, b]) if (!nodes.has(x.id)) nodes.set(x.id, { o: by[x.id], ext: x.ext });
    const key = a.id + "→" + b.id, e = edges.get(key) || { key, from: a.id, to: b.id, list: [] };
    e.list.push(c); edges.set(key, e);
  }
  const saved = M.positions[F || "_root"] || {}, pos = {}, todo = [];
  nodes.forEach((n, id) => saved[id] ? pos[id] = { x: saved[id][0], y: saved[id][1] } : todo.push(id));
  if (todo.length) {
    const g = new dagre.graphlib.Graph(); g.setGraph({ rankdir: "LR", nodesep: 46, ranksep: 100, marginx: 0, marginy: 0 }); g.setDefaultEdgeLabel(() => ({}));
    nodes.forEach((n, id) => g.setNode(id, { width: W, height: H }));
    edges.forEach(e => g.setEdge(e.from, e.to, { width: Math.min(130, measure(e.list[0].name || "", "11px")) + 24, height: 20, labelpos: "c" }));
    dagre.layout(g);
    const hit = (p, q) => Math.abs(p.x - q.x) < W + 20 && Math.abs(p.y - q.y) < H + 20;
    for (const id of todo) {
      const p = { x: snap(g.node(id).x), y: snap(g.node(id).y) };
      while (Object.values(pos).some(q => hit(p, q))) p.y += H + 40;   // never land on a card the user placed
      pos[id] = p;
    }
  }
  return { nodes, edges, pos };
}
const snap = v => Math.round(v / GRID) * GRID;
function bounds(pad = 0) {
  const ps = [...V.nodes.keys()].map(id => V.pos[id]);
  if (!ps.length) return { x: -260, y: -150, w: 520, h: 300 };
  const x0 = Math.min(...ps.map(p => p.x)) - W / 2 - pad, y0 = Math.min(...ps.map(p => p.y)) - H / 2 - pad;
  return { x: x0, y: y0, w: Math.max(...ps.map(p => p.x)) + W / 2 + pad - x0, h: Math.max(...ps.map(p => p.y)) + H / 2 + pad - y0 };
}
function scopeBox() {
  const ps = [...V.nodes].filter(([, n]) => !n.ext).map(([id]) => V.pos[id]);
  if (!ps.length) { const b = bounds(); return { x: b.x + b.w / 2 - 230, y: b.y + b.h / 2 - 130, w: 460, h: 260 }; }
  const x0 = Math.min(...ps.map(p => p.x)) - W / 2 - 34, y0 = Math.min(...ps.map(p => p.y)) - H / 2 - 52;
  return { x: x0, y: y0, w: Math.max(...ps.map(p => p.x)) + W / 2 + 34 - x0, h: Math.max(...ps.map(p => p.y)) + H / 2 + 34 - y0 };
}

/* ---------- canvas ---------- */
const SVG_CSS = `
text{font-family:var(--body);fill:var(--fg)}
.node .card{fill:var(--card);stroke:var(--line);stroke-width:1.5}
.node .stack{fill:var(--card);stroke:var(--line);stroke-width:1}
.node .name{font-size:14px;font-weight:600}
.node .sub{font-size:11px;fill:var(--muted)}
.node .desc{font-size:11.5px;fill:var(--muted)}
.node .foot{font-size:10.5px;fill:var(--faint)}
.node .ico{fill:none;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}
.node .stripe{stroke-width:3;stroke-linecap:round;fill:none}
.node.ext .card{stroke-dasharray:6 4;fill:var(--bg)}
.node.ext .stripe{opacity:.45}
.node.sel .card{stroke:var(--accent);stroke-width:2.2}
.node.hot .card{stroke:var(--hot);stroke-width:2.2}
.node.issue .card{stroke:var(--err)}
.node{cursor:grab}
.port{fill:var(--card);stroke:var(--accent);stroke-width:1.5;opacity:0;cursor:crosshair}
.node:hover .port,.node.sel .port{opacity:1}
.port:hover{fill:var(--accent)}
.badge circle{fill:var(--hot)}.badge text{font-size:10.5px;font-weight:700;fill:var(--bg)}
.edge path.line{fill:none;stroke:var(--faint);stroke-width:1.5}
.edge path.hit{fill:none;stroke:transparent;stroke-width:16;cursor:pointer}
.edge text{font-size:11px;fill:var(--muted);cursor:pointer}
.edge rect{fill:var(--canvas);fill-opacity:.92}
.edge.future path.line{stroke-dasharray:5 4}
.edge.sel path.line{stroke:var(--accent);stroke-width:2.2}.edge.sel text{fill:var(--accent);font-weight:600}
.edge.hot path.line{stroke:var(--hot);stroke-width:2.2}.edge.hot text{fill:var(--fg)}
.edge.dim,.node.dim{opacity:.3}
.scope rect{fill:none;stroke:var(--faint);stroke-width:1.2;stroke-dasharray:8 5}
.scope text{font-size:12px;fill:var(--muted);font-weight:600}
.scope .empty{font-weight:400;fill:var(--faint)}
.overlay .lasso{fill:var(--accent-soft);stroke:var(--accent);stroke-dasharray:4 3}
.overlay .wire{stroke:var(--accent);stroke-width:2;stroke-dasharray:6 4;fill:none}
#arrow path{fill:context-stroke}
`;
const ruler = document.createElement("canvas").getContext("2d");
function measure(text, font) { ruler.font = font + " " + getComputedStyle(document.body).fontFamily; return ruler.measureText(text).width; }
function fitText(text, font, max) {
  text = String(text || ""); if (measure(text, font) <= max) return text;
  while (text.length > 1 && measure(text + "…", font) > max) text = text.slice(0, -1);
  return text.trimEnd() + "…";
}
function wrapText(text, font, max, lines) {
  const out = []; let cur = "";
  for (const w of String(text || "").split(/\s+/).filter(Boolean)) {
    if (cur && measure(cur + " " + w, font) > max) { out.push(cur); cur = w; } else cur = cur ? cur + " " + w : w;
  }
  if (cur) out.push(cur);
  if (out.length > lines) { out.length = lines; out[lines - 1] = fitText(out[lines - 1] + " …", font, max); }
  return out.map(l => fitText(l, font, max));
}
const icon = (kind, attrs) => { const g = s("g", { class: "ico", stroke: `var(--k-${kind})`, ...attrs }); g.innerHTML = (KIND[kind] || KIND.component).icon; return g; };  // static markup from KIND, no model text

function rim(c, toward) {
  const dx = toward.x - c.x, dy = toward.y - c.y;
  const k = Math.min((W / 2 + 3) / Math.max(Math.abs(dx), 1e-6), (H / 2 + 3) / Math.max(Math.abs(dy), 1e-6), 1);
  return { x: c.x + dx * k, y: c.y + dy * k };
}
// Flow marks: link id -> step numbers, card id -> step numbers ("at" steps), for the opened flow.
function flowMarks() {
  const f = curFlow(), links = new Map(), cards = new Map();
  (f?.steps || []).forEach((st, i) => {
    const add = (m, k) => m.set(k, [...(m.get(k) || []), i]);
    if (st.at) { const a = lift(st.at, focus); if (a) add(cards, a.id); } else if (stepLink(st)) add(links, stepLink(st));
  });
  return { f, links, cards };
}

function draw(extra) {
  const svg = $("#svg"), marks = flowMarks(), camG = s("g", { id: "cam", transform: `translate(${cam.x},${cam.y}) scale(${cam.k})` });
  if (focus) {
    const b = scopeBox(), o = by[focus], empty = !kids(focus).length;
    camG.append(s("g", { class: "scope" }, s("rect", { x: b.x, y: b.y, width: b.w, height: b.h, rx: 12 }),
      s("text", { x: b.x + 14, y: b.y + 22, text: `${o.name || o.id}  [${KIND[o.type]?.label || o.type}]` }),
      empty && s("text", { class: "empty", x: b.x + b.w / 2, y: b.y + b.h / 2, "text-anchor": "middle", text: "Empty. Drag a block from the left to start." })));
  }
  const labels = [];
  V.edges.forEach(e => { const [line, label] = drawEdge(e, marks); camG.append(line); labels.push(label); });
  V.nodes.forEach((n, id) => camG.append(drawNode(n, id, marks)));
  camG.append(...labels);
  if (extra) camG.append(s("g", { class: "overlay" }, extra));
  svg.replaceChildren(s("defs", null, s("style", { text: SVG_CSS }),
    s("marker", { id: "arrow", viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" }, s("path", { d: "M0 1L9 5L0 9z" }))), camG);
  $("#zoom").textContent = Math.round(cam.k * 100) + "%";
}
function drawEdge(e, marks) {
  const a = V.pos[e.from], b = V.pos[e.to], back = V.edges.has(e.to + "→" + e.from);
  const dx = b.x - a.x, dy = b.y - a.y, L = Math.hypot(dx, dy) || 1, base = back ? 26 : 0;
  // Straight when nothing is in the way; otherwise the smallest bow, to either side, that passes clear of every other card.
  let ctrl, p0, p1, bend;
  for (bend of [base, base + 60, base - 60, base + 120, base - 120, base + 190, base - 190, base]) {
    ctrl = { x: (a.x + b.x) / 2 - dy / L * bend * 2, y: (a.y + b.y) / 2 + dx / L * bend * 2 };
    p0 = rim(a, bend ? ctrl : b); p1 = rim(b, bend ? ctrl : a);
    if (passesClear(p0, ctrl, p1, e)) break;
  }
  const d = bend ? `M${p0.x},${p0.y}Q${ctrl.x},${ctrl.y} ${p1.x},${p1.y}` : `M${p0.x},${p0.y}L${p1.x},${p1.y}`;
  const mid = bend ? { x: .25 * p0.x + .5 * ctrl.x + .25 * p1.x, y: .25 * p0.y + .5 * ctrl.y + .25 * p1.y } : { x: (p0.x + p1.x) / 2, y: (p0.y + p1.y) / 2 };
  const steps = e.list.flatMap(c => marks.links.get(c.id) || []).sort((x, y) => x - y);
  const cur = stepIx >= 0 && steps.includes(stepIx), first = e.list[0];
  const label = fitText((first.name || "") + (e.list.length > 1 ? `  +${e.list.length - 1}` : ""), "11px", 190);
  const lw = measure(label, "11px"), isSel = selEdge === e.key;
  const cls = ["edge", isSel && "sel", (cur || (stepIx < 0 && steps.length)) && "hot", marks.f && !steps.length && "dim", e.list.every(c => c.status === "future") && "future"].filter(Boolean).join(" ");
  const g = s("g", { class: cls, "data-e": e.key }, s("path", { class: "hit", d }), s("path", { class: "line", d, "marker-end": "url(#arrow)" }));
  const tag = s("g", { class: cls + " tag", "data-e": e.key });
  if (label && (cam.k >= FAR || isSel || cur)) tag.append(s("rect", { x: mid.x - lw / 2 - 5, y: mid.y - 9, width: lw + 10, height: 18, rx: 4 }), s("text", { x: mid.x, y: mid.y + 4, "text-anchor": "middle", text: label }));
  if (steps.length) tag.append(badge(mid.x + (label ? lw / 2 + 16 : 0), mid.y, steps));
  return [g, tag];
}
function passesClear(p0, c, p1, e) {
  for (let i = 1; i < 14; i++) {
    const t = i / 14, u = 1 - t, x = u * u * p0.x + 2 * u * t * c.x + t * t * p1.x, y = u * u * p0.y + 2 * u * t * c.y + t * t * p1.y;
    for (const id in V.pos) if (id !== e.from && id !== e.to && V.nodes.has(id) && Math.abs(x - V.pos[id].x) < W / 2 + 10 && Math.abs(y - V.pos[id].y) < H / 2 + 10) return false;
  }
  return true;
}
function badge(x, y, steps) {
  const t = steps.slice(0, 3).map(i => i + 1).join(",") + (steps.length > 3 ? "…" : ""), w = Math.max(18, measure(t, "700 10.5px") + 10);
  const k = Math.max(1, .75 / cam.k);  // stay readable when zoomed out
  return s("g", { class: "badge", transform: `translate(${x},${y}) scale(${k})` }, s("rect", { x: -w / 2, y: -9, width: w, height: 18, rx: 9, style: "fill:var(--hot)" }), s("text", { x: 0, y: 4, "text-anchor": "middle", text: t }));
}
function drawNode(n, id, marks) {
  const o = n.o, p = V.pos[id], kind = KIND[o.type] ? o.type : "component", nk = kids(id).length, steps = marks.cards.get(id) || [];
  const atCur = stepIx >= 0 && (steps.includes(stepIx) || stepTouches(marks.f?.steps[stepIx], id));
  const inFlow = marks.f && (steps.length || [...V.edges.values()].some(e => (e.from === id || e.to === id) && e.list.some(c => marks.links.has(c.id))));
  const cls = ["node", n.ext && "ext", sel.has(id) && "sel", atCur && "hot", marks.f && !inFlow && "dim", M.open_issues.includes(id) && "issue"].filter(Boolean).join(" ");
  const g = s("g", { class: cls, "data-id": id, transform: `translate(${p.x - W / 2},${p.y - H / 2})` });
  if (nk && !n.ext) g.append(s("rect", { class: "stack", x: 6, y: 6, width: W, height: H, rx: 10 }));
  g.append(s("rect", { class: "card", width: W, height: H, rx: 10 }), s("path", { class: "stripe", d: `M12 1.5H${W - 12}`, stroke: `var(--k-${kind})` }));
  if (cam.k < FAR) {
    const big = wrapText(o.name || o.id, "600 30px", W - 24, 2);
    big.forEach((l, i) => g.append(s("text", { class: "name", style: "font-size:30px", x: 12, y: (big.length > 1 ? 46 : 52) + i * 34, text: l })));
    if (big.length === 1) g.append(s("text", { class: "sub", style: "font-size:17px", x: 12, y: H - 14, text: KIND[kind].label + (nk && !n.ext ? ` · ${nk} inside` : n.ext ? " · outside" : "") }));
    if (steps.length) g.append(badge(W - 18, 0, steps));
    return g;
  }
  g.append(icon(kind, { transform: "translate(13,13)" }),
    s("text", { class: "name", x: 42, y: 27, text: fitText(o.name || o.id, "600 14px", W - 56) }),
    s("text", { class: "sub", x: 42, y: 43, text: fitText(`[${KIND[kind].label}${o.tech ? ": " + o.tech : ""}]`, "11px", W - 56) }));
  wrapText(o.description, "11.5px", W - 28, 2).forEach((l, i) => g.append(s("text", { class: "desc", x: 14, y: 64 + i * 15, text: l })));
  const foot = n.ext ? "Outside · " + (path(o.parent) || "top level") : nk ? `${nk} inside ›` : "";
  if (foot) g.append(s("text", { class: "foot", x: 14, y: H - 9, text: fitText(foot, "10.5px", W - 90) }));
  if (o.status && o.status !== "live") g.append(s("text", { class: "foot", x: W - 12, y: H - 9, "text-anchor": "end", text: STATUS[o.status] || o.status }));
  if (steps.length) g.append(badge(W - 18, 0, steps));
  for (const [x, y] of [[W / 2, 0], [W, H / 2], [W / 2, H], [0, H / 2]]) g.append(s("circle", { class: "port", cx: x, cy: y, r: 5.5 }, s("title", { text: "Drag to another block to connect" })));
  return g;
}
function stepTouches(st, id) {
  const c = st && !st.at && conn(stepLink(st)); if (!c) return false;
  return lift(c.from, focus)?.id === id || lift(c.to, focus)?.id === id;
}

/* ---------- camera ---------- */
const world = e => { const r = $("#svg").getBoundingClientRect(); return { x: (e.clientX - r.left - cam.x) / cam.k, y: (e.clientY - r.top - cam.y) / cam.k }; };
function fit() {
  const r = $("#stage").getBoundingClientRect(), b = focus ? scopeBox() : bounds(), all = bounds(40);
  const x0 = Math.min(b.x - 40, all.x), y0 = Math.min(b.y - 40, all.y), x1 = Math.max(b.x + b.w + 40, all.x + all.w), y1 = Math.max(b.y + b.h + 40, all.y + all.h);
  const k = Math.min(1.25, Math.max(.15, Math.min(r.width / (x1 - x0), r.height / (y1 - y0))));
  cam = { k, x: r.width / 2 - (x0 + x1) / 2 * k, y: r.height / 2 - (y0 + y1) / 2 * k };
  draw();
}
function zoomAt(f, cx, cy) {
  const r = $("#stage").getBoundingClientRect(); cx ??= r.width / 2; cy ??= r.height / 2;
  const k = Math.min(3, Math.max(.15, cam.k * f));
  cam = { k, x: cx - (cx - cam.x) * k / cam.k, y: cy - (cy - cam.y) * k / cam.k };
  draw();
}
function centerOn(id) {
  const r = $("#stage").getBoundingClientRect(), p = V.pos[id]; if (!p) return;
  cam.x = r.width / 2 - p.x * cam.k; cam.y = r.height / 2 - p.y * cam.k; draw();
}

/* ---------- navigation and refresh ---------- */
function refresh() {
  document.body.classList.toggle("nomap", !M);
  if (!M) { $("#svg").replaceChildren(); renderStart(); renderBar(); renderPalette(); renderPanel(); return; }
  V = buildView(focus); draw(); renderStart(); renderBar(); renderPalette(); renderPanel();
}
function go(F) {
  focus = F && by[F] ? F : null; sel.clear(); selEdge = selConn = null;
  history.replaceState(null, "", location.search + "#" + encodeURIComponent(focus || ""));
  V = buildView(focus); fit(); refresh();
}
function jumpTo(id) {
  if (!by[id]) return;
  go(by[id].parent || null); sel = new Set([id]); tab = "props"; centerOn(id); refresh();
}
function renderBar() {
  const items = [h("a", { text: M?.name || "Architecture", onclick: () => M && go(null) })];
  for (const id of focus ? chain(focus) : []) items.push(h("i", { text: "›" }), h("a", { text: nm(id), onclick: () => go(id) }));
  if (M) items.push(h("small", { text: LEVEL[focus ? by[focus].type : ""] || "Inside" }));
  $("#crumbs").replaceChildren(...items);
  $("#undo").disabled = !undo.length; $("#redo").disabled = !redo.length;
  for (const id of ["tidy", "fit", "zin", "zout", "export", "find"]) $("#" + id).disabled = !M;
  $("#classic").href = "/c4-classic" + location.search + location.hash;
  const hint = adding ? "Click links or blocks on the map to add steps to this flow. Esc to stop." : "";
  if (!$("#hint").dataset.ask) { $("#hint").textContent = hint; $("#hint").hidden = !hint; }
}
function renderPalette() {
  const allowed = M ? CHILD[focus ? by[focus].type : ""] || [] : [];
  $("#palette").replaceChildren(h("h6", { text: "Blocks" }), ...Object.keys(KIND).map(k => {
    const b = h("button", { disabled: !allowed.includes(k), title: allowed.includes(k) ? `Drag onto the map, or click, to add a ${KIND[k].label.toLowerCase()}` : `A ${KIND[k].label.toLowerCase()} does not belong on this level`, "data-kind": k });
    const sv = s("svg", { viewBox: "0 0 20 20", stroke: `var(--k-${k})` }); sv.innerHTML = KIND[k].icon;  // static markup
    b.append(sv, KIND[k].label);
    b.addEventListener("pointerdown", e => paletteDown(e, k));
    return b;
  }));
}
const TEMPLATES = [
  { title: "Web application", sub: "User, web app, API, database", make: n => [
    { op: "add_object", id: "user", kind: "actor", name: "User", summary: "Uses the product in a browser" },
    { op: "add_object", id: "system", kind: "system", name: n, summary: "Describe what this system does in one sentence" },
    { op: "add_object", id: "web", parent: "system", kind: "app", name: "Web app", tech: "Browser", summary: "Screens the user works with" },
    { op: "add_object", id: "api", parent: "system", kind: "app", name: "API", tech: "HTTP + JSON", summary: "Business rules and access control" },
    { op: "add_object", id: "db", parent: "system", kind: "store", name: "Database", tech: "SQL", summary: "Durable data" },
    { op: "add_link", id: "user_web", from: "user", to: "web", name: "Uses" },
    { op: "add_link", id: "web_api", from: "web", to: "api", name: "Calls" },
    { op: "add_link", id: "api_db", from: "api", to: "db", name: "Reads and writes" },
    { op: "set_positions", view: "_root", positions: { user: [0, 0], system: [340, 0] } },
    { op: "set_positions", view: "system", positions: { user: [-340, 0], web: [0, 0], api: [340, 0], db: [680, 0] } }] },
  { title: "Service with a queue", sub: "Producer, queue, worker, store", make: n => [
    { op: "add_object", id: "client", kind: "actor", name: "Client", summary: "Sends requests" },
    { op: "add_object", id: "system", kind: "system", name: n, summary: "Describe what this system does in one sentence" },
    { op: "add_object", id: "api", parent: "system", kind: "app", name: "API", summary: "Accepts requests and queues work" },
    { op: "add_object", id: "queue", parent: "system", kind: "store", name: "Queue", summary: "Work waiting to be done" },
    { op: "add_object", id: "worker", parent: "system", kind: "app", name: "Worker", summary: "Does the work in the background" },
    { op: "add_object", id: "db", parent: "system", kind: "store", name: "Database", summary: "Results and state" },
    { op: "add_link", id: "client_api", from: "client", to: "api", name: "Requests" },
    { op: "add_link", id: "api_queue", from: "api", to: "queue", name: "Enqueues" },
    { op: "add_link", id: "worker_queue", from: "worker", to: "queue", name: "Takes work" },
    { op: "add_link", id: "worker_db", from: "worker", to: "db", name: "Writes results" },
    { op: "set_positions", view: "_root", positions: { client: [0, 0], system: [340, 0] } },
    { op: "set_positions", view: "system", positions: { client: [-340, 0], api: [0, 0], queue: [340, -90], worker: [340, 90], db: [680, 90] } }] },
];
function renderStart() {
  const box = $("#start"), blank = M && !M.objects.length;
  if (M && !blank) { box.hidden = true; return; }
  box.hidden = false;
  const begin = async t => {
    if (!M) { const r = await post({ op: "create_map" }); if (r.error) return toast(r.error); adopt(r.d.model); }
    if (t) await commit({ op: "batch", ops: t.make(M.name || "System") }, { op: "batch", ops: [{ op: "delete_object", id: "system", cascade: true }, { op: "delete_object", id: t.make("")[0].id, cascade: true }] });
    go(null);
  };
  box.replaceChildren(h("div", { class: "welcome" }, h("h2", { text: M ? "An empty map" : "Start your design" }),
    h("p", { text: M ? "Drag a block from the left onto the canvas, or begin from a template." : "This project has no architecture map yet. Begin from a template or a blank canvas." }),
    h("div", { class: "tpl" }, ...TEMPLATES.map(t => h("button", { onclick: () => begin(t) }, h("b", { text: t.title }), h("small", { text: t.sub }))),
      !M && h("button", { onclick: () => begin(null) }, h("b", { text: "Blank canvas" }), h("small", { text: "Place every block yourself" })))));
}

/* ---------- small UI helpers ---------- */
let toastTimer = 0;
function toast(msg, ok) { const t = $("#toast"); t.textContent = msg; t.className = ok ? "ok" : ""; t.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => t.hidden = true, ok ? 2500 : 7000); }
function ask(msg, yes) {
  return new Promise(res => {
    const bar = $("#hint"), done = v => { delete bar.dataset.ask; bar.hidden = true; renderBar(); res(v); };
    bar.dataset.ask = "1"; bar.hidden = false;
    bar.replaceChildren(msg + "  ", h("button", { class: "danger", text: yes, onclick: () => done(true) }), " ", h("button", { text: "Cancel", onclick: () => done(false) }));
  });
}
// A text box on the canvas at a screen point. Enter or leaving the box saves, Esc cancels.
function inlineEdit(cx, cy, value, placeholder, save) {
  document.querySelector(".inline")?.remove();
  const r = $("#stage").getBoundingClientRect();
  const inp = h("input", { class: "inline", value, placeholder, style: `left:${Math.max(4, Math.min(r.width - 224, cx - r.left - 110))}px;top:${Math.max(4, cy - r.top - 15)}px;width:220px` });
  let over = false; const end = ok => { if (over) return; over = true; const v = inp.value.trim(); inp.remove(); if (ok && v) save(v); $("#stage").focus(); };
  inp.onkeydown = e => { e.stopPropagation(); if (e.key === "Enter") end(true); else if (e.key === "Escape") end(false); };
  inp.onblur = () => end(true);
  $("#stage").append(inp); inp.focus(); inp.select();
}
const screenOf = id => { const r = $("#svg").getBoundingClientRect(), p = V.pos[id]; return { x: r.left + cam.x + p.x * cam.k, y: r.top + cam.y + p.y * cam.k }; };
function download(name, blob) { const a = h("a", { href: URL.createObjectURL(blob), download: name }); document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 5000); }

/* ---------- edits ---------- */
function addObject(kind, pt) {
  const r = $("#svg").getBoundingClientRect();
  inlineEdit(r.left + cam.x + pt.x * cam.k, r.top + cam.y + pt.y * cam.k, "", `Name the ${KIND[kind].label.toLowerCase()}…`, async name => {
    const id = slug(name, new Set(M.objects.map(o => o.id)));
    const ops = [{ op: "add_object", id, name, kind, ...(focus ? { parent: focus } : {}) }, { op: "set_positions", view: viewKey(), positions: { [id]: [snap(pt.x), snap(pt.y)] } }];
    if (await commit({ op: "batch", ops }, { op: "delete_object", id, cascade: true })) { sel = new Set([id]); selEdge = selConn = null; tab = "props"; refresh(); }
  });
}
function freeSpot() {
  const r = $("#stage").getBoundingClientRect(), p = { x: snap((r.width / 2 - cam.x) / cam.k), y: snap((r.height / 2 - cam.y) / cam.k) };
  while (Object.values(V.pos).some(q => Math.abs(p.x - q.x) < W + 20 && Math.abs(p.y - q.y) < H + 20)) p.y += H + 40;
  return p;
}
function updateObject(id, set) {
  const o = by[id], inv = {};
  for (const k of Object.keys(set)) { inv[k] = o[OBJ_FIELD[k]] ?? null; if (set[k] === "" || (Array.isArray(set[k]) && !set[k].length)) set[k] = null; }
  if (Object.keys(set).every(k => JSON.stringify(set[k]) === JSON.stringify(inv[k]))) return;
  return commit({ op: "update_object", id, set }, { op: "update_object", id, set: inv });
}
function addLink(from, to, at) {
  inlineEdit(at.x, at.y, "Uses", "What does it do?", async name => {
    const id = slug(`${from}_${to}`, new Set(M.connections.map(c => c.id)));
    if (await commit({ op: "add_link", id, from, to, name }, { op: "delete_link", id })) { selEdge = lift(from, focus)?.id + "→" + lift(to, focus)?.id; selConn = id; sel.clear(); tab = "props"; refresh(); }
  });
}
function updateLink(id, set) {
  const c = conn(id), inv = {};
  for (const k of Object.keys(set)) { inv[k] = c[LINK_FIELD[k]] ?? null; if (set[k] === "") set[k] = null; }
  if (Object.keys(set).every(k => set[k] === inv[k])) return;
  return commit({ op: "update_link", id, set }, { op: "update_link", id, set: inv });
}
async function removeSelection() {
  if (selConn && !sel.size) { const c = conn(selConn); selEdge = selConn = null; return commit({ op: "delete_link", id: c.id }, { op: "add_link", ...linkOp(c) }); }
  const picked = [...sel].filter(id => !V.nodes.get(id)?.ext);
  if (!picked.length) return sel.size && toast("That block lives outside this level. Open its own level to delete it.");
  const tops = picked.filter(id => !chain(id).slice(0, -1).some(a => sel.has(a)));
  const gone = M.objects.filter(o => chain(o.id).some(a => tops.includes(a))), ids = new Set(gone.map(o => o.id));
  const links = M.connections.filter(c => ids.has(c.from) || ids.has(c.to));
  if ((gone.length > tops.length || links.length) && !await ask(`Delete ${gone.length} block${gone.length > 1 ? "s" : ""} and ${links.length} link${links.length === 1 ? "" : "s"}?`, "Delete")) return;
  const places = Object.entries(M.positions).map(([view, ps]) => ({ op: "set_positions", view, positions: Object.fromEntries(Object.entries(ps).filter(([id]) => ids.has(id) || ids.has(view))) })).filter(x => Object.keys(x.positions).length);
  const inv = { op: "batch", ops: [...gone.sort((a, b) => chain(a.id).length - chain(b.id).length).map(o => ({ op: "add_object", ...objOp(o) })), ...links.map(c => ({ op: "add_link", ...linkOp(c) })), ...places] };
  sel.clear();
  return commit({ op: "batch", ops: tops.map(id => ({ op: "delete_object", id, cascade: true })) }, inv);
}
// Positions are drawing data: show them at once, save in the background.
function commitPositions(positions) {
  const view = viewKey(), old = M.positions[view] || {}, inv = Object.fromEntries(Object.keys(positions).map(id => [id, old[id] || null]));
  M.positions[view] = { ...old }; for (const [id, p] of Object.entries(positions)) p ? M.positions[view][id] = p : delete M.positions[view][id];
  const op = { op: "set_positions", view, positions }, u = { op, inv: { op: "set_positions", view, positions: inv } };
  undo.push(u); redo = []; refresh();
  post(op).then(r => { if (r.error) { toast(r.error); undo = undo.filter(x => x !== u); reload().then(refresh); } });
}
function align(mode) {
  const ids = [...sel], ps = ids.map(id => V.pos[id]), out = {};
  if (mode === "left" || mode === "top") { const k = mode === "left" ? "x" : "y", v = Math.min(...ps.map(p => p[k])); ids.forEach(id => out[id] = k === "x" ? [v, V.pos[id].y] : [V.pos[id].x, v]); }
  else { const k = mode === "h" ? "x" : "y", sorted = [...ids].sort((a, b) => V.pos[a][k] - V.pos[b][k]), a = V.pos[sorted[0]][k], step = (V.pos[sorted.at(-1)][k] - a) / (sorted.length - 1);
    sorted.forEach((id, i) => out[id] = k === "x" ? [snap(a + i * step), V.pos[id].y] : [V.pos[id].x, snap(a + i * step)]); }
  commitPositions(out);
}
function flowSet(set) {
  const f = curFlow(); if (!f) return;
  return commit({ op: "update_flow", id: f.id, set }, { op: "update_flow", id: f.id, set: { ...(set.name ? { name: f.name } : {}), ...(set.steps ? { steps: f.steps.map(cleanStep) } : {}) } });
}
function addStep(st) { const f = curFlow(); stepIx = f.steps.length; return flowSet({ steps: [...f.steps.map(cleanStep), st] }); }

/* ---------- pointer: select, drag, connect, pan ---------- */
let drag = null, raf = 0;
const later = fn => { cancelAnimationFrame(raf); raf = requestAnimationFrame(fn); };
$("#svg").addEventListener("pointerdown", e => {
  if (!M || e.button > 1) return;
  document.querySelector(".inline")?.blur();
  const svg = $("#svg"), nodeEl = e.target.closest(".node"), edgeEl = e.target.closest(".edge"), p = world(e);
  svg.setPointerCapture(e.pointerId); $("#stage").focus();
  if (e.button === 1 || (!nodeEl && !edgeEl && !e.shiftKey)) drag = { type: "pan", sx: e.clientX, sy: e.clientY, cx: cam.x, cy: cam.y };
  else if (e.target.closest(".port")) drag = { type: "connect", from: nodeEl.dataset.id, p };
  else if (nodeEl) drag = { type: "node", id: nodeEl.dataset.id, p, shift: e.shiftKey, orig: null };
  else if (edgeEl) drag = { type: "edge", key: edgeEl.dataset.e };
  else drag = { type: "marquee", p };
  drag.x0 = e.clientX; drag.y0 = e.clientY;
});
$("#svg").addEventListener("pointermove", e => {
  if (!drag) return;
  const p = world(e), far = Math.hypot(e.clientX - drag.x0, e.clientY - drag.y0) > 4;
  if (drag.type === "pan") { if (far) { drag.moved = true; $("#stage").classList.add("pan"); } cam.x = drag.cx + e.clientX - drag.sx; cam.y = drag.cy + e.clientY - drag.sy; later(() => draw()); }
  else if (drag.type === "node" && (far || drag.moved)) {
    if (!drag.moved) { drag.moved = true; if (!sel.has(drag.id)) { sel = new Set([drag.id]); selEdge = selConn = null; } drag.orig = Object.fromEntries([...sel].map(id => [id, { ...V.pos[id] }])); }
    for (const [id, o] of Object.entries(drag.orig)) V.pos[id] = { x: snap(o.x + p.x - drag.p.x), y: snap(o.y + p.y - drag.p.y) };
    later(() => draw());
  }
  else if (drag.type === "connect") { $("#stage").classList.add("connect"); const a = V.pos[drag.from]; later(() => draw(s("path", { class: "wire", d: `M${a.x},${a.y}L${p.x},${p.y}`, "marker-end": "url(#arrow)" }))); }
  else if (drag.type === "marquee") { drag.moved = true; const b = drag.p; later(() => draw(s("rect", { class: "lasso", x: Math.min(b.x, p.x), y: Math.min(b.y, p.y), width: Math.abs(p.x - b.x), height: Math.abs(p.y - b.y) }))); }
});
$("#svg").addEventListener("pointerup", e => {
  const d = drag; drag = null; if (!d) return;
  cancelAnimationFrame(raf); $("#stage").classList.remove("pan", "connect");
  const p = world(e);
  if (d.type === "pan") { if (!d.moved && (sel.size || selEdge)) { sel.clear(); selEdge = selConn = null; refresh(); } return; }
  if (d.type === "node") {
    if (d.moved) {  // the first hand-placed card freezes the whole level, so the rest does not reshuffle around it
      const saved = M.positions[viewKey()] || {}, ids = [...V.nodes.keys()].filter(id => d.orig[id] || !saved[id]);
      return commitPositions(Object.fromEntries(ids.map(id => [id, [V.pos[id].x, V.pos[id].y]])));
    }
    if (adding) return addStep({ at: d.id });
    if (!d.shift && isDouble("n:" + d.id)) return openNode(d.id);
    if (d.shift) sel.has(d.id) ? sel.delete(d.id) : sel.add(d.id); else sel = new Set([d.id]);
    selEdge = selConn = null; if (tab === "issues") tab = "props"; return refresh();
  }
  if (d.type === "edge") {
    const ed = V.edges.get(d.key); if (!ed) return;
    if (adding && ed.list.length === 1) return addStep({ link: ed.list[0].id });
    if (ed.list.length === 1 && isDouble("e:" + d.key)) return inlineEdit(e.clientX, e.clientY, ed.list[0].name || "", "Link name", name => updateLink(ed.list[0].id, { name }));
    sel.clear(); selEdge = d.key; selConn = ed.list.length === 1 ? ed.list[0].id : null; if (!adding) tab = "props"; return refresh();
  }
  if (d.type === "connect") {
    const to = document.elementFromPoint(e.clientX, e.clientY)?.closest?.(".node")?.dataset.id;
    draw(); if (to && to !== d.from) addLink(d.from, to, { x: e.clientX, y: e.clientY });
    return;
  }
  if (d.type === "marquee") {
    const x0 = Math.min(d.p.x, p.x), x1 = Math.max(d.p.x, p.x), y0 = Math.min(d.p.y, p.y), y1 = Math.max(d.p.y, p.y);
    sel = new Set([...V.nodes.keys()].filter(id => { const q = V.pos[id]; return q.x > x0 && q.x < x1 && q.y > y0 && q.y < y1; })); selEdge = selConn = null; refresh();
  }
});
// Double click is detected here, not with the dblclick event: the svg captures the pointer and the first click redraws the card.
let lastClick = { key: "", t: 0 };
function isDouble(key) { const now = performance.now(), dbl = lastClick.key === key && now - lastClick.t < 400; lastClick = { key: dbl ? "" : key, t: now }; return dbl; }
function openNode(id) {
  const n = V.nodes.get(id), at = screenOf(id);
  if (n.ext) return jumpTo(id);
  if (CHILD[n.o.type]?.length) return go(id);
  inlineEdit(at.x, at.y - 30 * cam.k, n.o.name || "", "Name", name => updateObject(id, { name }));
}
$("#stage").addEventListener("wheel", e => { if (!M) return; e.preventDefault(); const r = $("#stage").getBoundingClientRect(); zoomAt(Math.exp(-e.deltaY * .0015), e.clientX - r.left, e.clientY - r.top); }, { passive: false });

function paletteDown(e, kind) {
  if (e.button || e.currentTarget.disabled) return;
  const x0 = e.clientX, y0 = e.clientY; let ghost = null;
  const move = ev => {
    if (!ghost && Math.hypot(ev.clientX - x0, ev.clientY - y0) > 5) { ghost = h("div", { id: "ghost", text: KIND[kind].label }); document.body.append(ghost); }
    if (ghost) ghost.style.cssText = `left:${ev.clientX - 60}px;top:${ev.clientY - 18}px`;
  };
  const up = ev => {
    removeEventListener("pointermove", move); removeEventListener("pointerup", up);
    if (!ghost) return addObject(kind, freeSpot());
    ghost.remove();
    const r = $("#stage").getBoundingClientRect();
    if (ev.clientX > r.left && ev.clientX < r.right && ev.clientY > r.top && ev.clientY < r.bottom) addObject(kind, world(ev));
  };
  addEventListener("pointermove", move); addEventListener("pointerup", up);
}

/* ---------- side panel ---------- */
const field = (label, control) => [h("label", { text: label }), control];
const text = (value, save, attrs) => h("input", { value: value || "", ...attrs, onchange: e => save(e.target.value.trim()) });
const area = (value, save, attrs) => h("textarea", { value: value || "", rows: 3, ...attrs, onchange: e => save(e.target.value.trim()) });
const pick = (value, options, save) => h("select", { onchange: e => save(e.target.value) }, options.map(([v, t]) => h("option", { value: v, text: t, selected: v === (value ?? "") })));
const lines = v => v.split(/[\n,]/).map(x => x.trim()).filter(Boolean);

function renderPanel() {
  document.querySelectorAll("#tabs [data-t]").forEach(b => b.setAttribute("aria-selected", b.dataset.t === tab));
  const box = $("#panel");
  if (!M) return box.replaceChildren(h("p", { text: "No map yet." }));
  box.replaceChildren(...(tab === "flows" ? flowsPanel() : tab === "issues" ? issuesPanel() : propsPanel()).flat(Infinity).filter(Boolean));
}
function propsPanel() {
  if (sel.size > 1) return [h("h3", { text: `${sel.size} blocks selected` }), h("h4", { text: "Arrange" }),
    h("div", { class: "row" }, h("button", { text: "Align left", onclick: () => align("left") }), h("button", { text: "Align top", onclick: () => align("top") }),
      sel.size > 2 && h("button", { text: "Space out →", onclick: () => align("h") }), sel.size > 2 && h("button", { text: "Space out ↓", onclick: () => align("v") })),
    h("div", { class: "row" }, h("button", { class: "danger", text: "Delete", onclick: removeSelection }))];
  if (sel.size === 1) return objectPanel(by[[...sel][0]]);
  if (selEdge) return linkPanel();
  return overviewPanel();
}
function overviewPanel() {
  const o = focus && by[focus];
  return [h("h3", { text: o ? o.name : M.name || "Architecture" }), h("p", { text: o ? `Inside this ${KIND[o.type]?.label.toLowerCase()}: ${kids(focus).length} blocks.` : `${M.objects.length} blocks, ${M.connections.length} links, ${M.flows.length} flows.` }),
    o && h("div", { class: "row" }, h("button", { text: "Edit this block", onclick: () => jumpTo(focus) }), h("button", { text: "Up one level", onclick: () => go(o.parent || null) })),
    h("h4", { text: "How to design" }),
    h("div", { class: "keys" },
      h("span", { text: "Add" }), h("span", { text: "Drag a block from the left onto the map" }),
      h("span", { text: "Connect" }), h("span", { text: "Drag from a dot on a block's edge to another block" }),
      h("span", { text: "Open" }), h("span", { text: "Double-click a system or app to design its inside" }),
      h("span", { text: "Rename" }), h("span", {}, "Select, then press ", h("kbd", { text: "F2" })),
      h("span", { text: "Select many" }), h("span", {}, h("kbd", { text: "Shift" }), " + click, or ", h("kbd", { text: "Shift" }), " + drag a box"),
      h("span", { text: "Delete" }), h("span", {}, h("kbd", { text: "Del" })),
      h("span", { text: "Undo" }), h("span", {}, h("kbd", { text: "Ctrl" }), " + ", h("kbd", { text: "Z" })),
      h("span", { text: "Move map" }), h("span", { text: "Drag the background; scroll to zoom" }))];
}
function objectPanel(o) {
  const ext = V.nodes.get(o.id)?.ext, set = k => v => updateObject(o.id, { [k]: v });
  const below = new Set(M.objects.filter(x => chain(x.id).includes(o.id)).map(x => x.id));
  const parents = [["", "(top level)"], ...M.objects.filter(x => !below.has(x.id) && CHILD[x.type]?.length).map(x => [x.id, path(x.id)])];
  const links = M.connections.filter(c => c.from === o.id || c.to === o.id), tasks = M.links[o.id]?.items || [];
  return [h("h3", { text: o.name || o.id }), h("p", {}, h("span", { class: "kind", text: KIND[o.type]?.label || o.type }), "  ", h("small", { text: o.id })),
    ext && h("p", { text: "This block lives outside the level you are looking at." }),
    field("Name", text(o.name, set("name"))),
    field("Description", area(o.description, set("summary"), { placeholder: "What it is responsible for, in one sentence" })),
    field("Technology", text(o.tech, set("tech"), { placeholder: "e.g. Python + SQLite" })),
    field("Kind", pick(o.type, Object.entries(KIND).map(([k, v]) => [k, v.label]), set("kind"))),
    field("Status", pick(o.status || "live", Object.entries(STATUS), v => updateObject(o.id, { status: v === "live" ? "" : v }))),
    field("Inside", pick(o.parent || "", parents, set("parent"))),
    field("Tags", text((o.tags || []).join(", "), v => updateObject(o.id, { tags: lines(v) }), { placeholder: "comma separated" })),
    field("Code it owns", area((o.owns || []).join("\n"), v => updateObject(o.id, { owns: lines(v) }), { placeholder: "one path or glob per line", rows: 2 })),
    h("div", { class: "row" }, CHILD[o.type]?.length && h("button", { text: kids(o.id).length ? "Open inside" : "Design inside", onclick: () => go(o.id) }),
      ext && h("button", { text: "Go to its level", onclick: () => jumpTo(o.id) }), !ext && h("button", { class: "danger", text: "Delete", onclick: removeSelection })),
    links.length && [h("h4", { text: `Links (${links.length})` }), h("div", { class: "list" }, links.map(c => h("div", { class: "item", onclick: () => showLink(c.id) },
      h("span", { class: "t", text: `${c.from === o.id ? "→ " + nm(c.to) : "← " + nm(c.from)} · ${c.name || ""}` }))))],
    tasks.length && [h("h4", { text: `Tasks (${tasks.length})` }), h("div", { class: "list" }, tasks.map(t => h("a", { class: "item", href: `/#/p/${encodeURIComponent(PROJECT)}/task/${t.id}`, target: "_top", style: "text-decoration:none;color:inherit" },
      h("span", { class: "t", text: `#${t.id} ${t.title}` }), h("small", { text: t.status }))))]];
}
function showLink(id) {
  const c = conn(id), a = lift(c.from, focus), b = lift(c.to, focus);
  if (!a || !b || a.id === b.id) { const up = chain(c.from).filter(x => chain(c.to).includes(x)).pop() || null; go(up); }
  sel.clear(); selEdge = lift(c.from, focus)?.id + "→" + lift(c.to, focus)?.id; selConn = id; tab = "props"; refresh();
}
function linkPanel() {
  const ed = V.edges.get(selEdge); if (!ed) return overviewPanel();
  const c = selConn && conn(selConn);
  if (!c) return [h("h3", { text: `${nm(ed.from)} → ${nm(ed.to)}` }), h("p", { text: `${ed.list.length} links run along this arrow. Pick one${adding ? " to add it as a flow step" : " to edit it"}.` }),
    h("div", { class: "list" }, ed.list.map(x => h("div", { class: "item", onclick: () => adding ? addStep({ link: x.id }) : (selConn = x.id, refresh()) },
      h("span", { class: "t", text: `${x.name || x.id}` }), h("small", { text: `${nm(x.from)} → ${nm(x.to)}` }))))];
  const set = k => v => updateLink(c.id, { [k]: v }), all = M.objects.map(o => [o.id, path(o.id)]), k = c.detail && M.contracts[c.detail];
  return [h("h3", { text: c.name || c.id }), h("p", {}, h("span", { class: "kind", text: "Link" }), "  ", h("small", { text: c.id })),
    ed.list.length > 1 && h("div", { class: "row" }, h("button", { text: `‹ All ${ed.list.length} links on this arrow`, onclick: () => { selConn = null; refresh(); } })),
    field("Name", text(c.name, set("name"), { placeholder: "What the caller does, e.g. Reads orders" })),
    field("Description", area(c.description, set("summary"))),
    field("From", pick(c.from, all, set("from"))), field("To", pick(c.to, all, set("to"))),
    field("Status", pick(c.status || "live", Object.entries(STATUS), v => updateLink(c.id, { status: v === "live" ? "" : v }))),
    h("div", { class: "row" }, h("button", { text: "Flip direction", onclick: () => commit({ op: "update_link", id: c.id, set: { from: c.to, to: c.from } }, { op: "update_link", id: c.id, set: { from: c.from, to: c.to } }) }),
      h("button", { class: "danger", text: "Delete", onclick: removeSelection })),
    k && [h("h4", { text: "Call detail" }), k.transport && h("p", { text: "Transport: " + k.transport }), k.start && h("p", { text: "Starts in: " + [].concat(k.start).join(", ") }), k.end && h("p", { text: "Ends in: " + k.end })]];
}
function stepTitle(st) {
  if (st.at) return "At " + nm(st.at);
  const c = conn(stepLink(st)); if (!c) return "Missing link " + stepLink(st);
  return st.reverse ? `${nm(c.to)} ↩ ${nm(c.from)} · ${c.name || ""}` : `${nm(c.from)} → ${nm(c.to)} · ${c.name || ""}`;
}
function showStep(i) {
  const f = curFlow(), st = f?.steps[i]; stepIx = st ? i : -1;
  if (st) {
    const c = !st.at && conn(stepLink(st)), level = st.at ? by[st.at]?.parent || null : c ? chain(c.from).filter(x => chain(c.to).includes(x)).pop() || null : focus;
    if (level !== focus && (st.at ? !V.nodes.has(st.at) : !(c && lift(c.from, focus) && lift(c.to, focus) && lift(c.from, focus).id !== lift(c.to, focus).id))) { const keep = [flowId, stepIx]; go(level); [flowId, stepIx] = keep; }
  }
  refresh();
}
function flowsPanel() {
  const f = curFlow();
  if (!f) return [h("h3", { text: "Flows" }), h("p", { text: "A flow is one user-visible action traced step by step across the map." }),
    h("div", { class: "row" }, h("button", { class: "pri", text: "New flow", onclick: e => { const r = e.target.getBoundingClientRect(); inlineEdit(r.left, r.bottom + 24, "", "Name the flow, e.g. Place an order", async name => {
      const id = slug(name, new Set(M.flows.map(x => x.id)));
      if (await commit({ op: "add_flow", id, name }, { op: "delete_flow", id })) { flowId = id; stepIx = -1; adding = true; refresh(); } }); } })),
    h("h4", { text: `${M.flows.length} flows` }),
    h("div", { class: "list" }, M.flows.map(x => h("div", { class: "item", onclick: () => { flowId = x.id; stepIx = -1; refresh(); } }, h("span", { class: "t", text: x.name || x.id }), h("small", { text: `${x.steps.length} steps` }))))];
  const move = (i, d) => { const st = f.steps.map(cleanStep); [st[i], st[i + d]] = [st[i + d], st[i]]; stepIx = i + d; flowSet({ steps: st }); };
  const patch = (i, fn) => { const st = f.steps.map(cleanStep); fn(st, i); flowSet({ steps: st.map(cleanStep) }); };
  return [h("div", { class: "row", style: "margin:0 0 8px" }, h("button", { text: "‹ All flows", onclick: () => { flowId = null; adding = false; stepIx = -1; refresh(); } })),
    field("Flow name", text(f.name, v => v && flowSet({ name: v }))),
    h("div", { class: "row" }, h("button", { text: "◀", title: "Previous step", disabled: stepIx < 0, onclick: () => showStep(stepIx - 1) }),
      h("button", { text: stepIx < 0 ? "▶ Play" : "▶", title: "Next step", disabled: stepIx >= f.steps.length - 1, onclick: () => showStep(stepIx + 1) }),
      h("button", { class: adding ? "on" : "", text: adding ? "Adding steps…" : "+ Add steps", title: "Then click links or blocks on the map", onclick: () => { adding = !adding; refresh(); } }),
      h("button", { class: "danger", text: "Delete flow", onclick: async () => { if (await ask(`Delete the flow "${f.name || f.id}"?`, "Delete")) { adding = false; commit({ op: "delete_flow", id: f.id }, { op: "add_flow", id: f.id, name: f.name || f.id, steps: f.steps.map(cleanStep) }); } } })),
    h("h4", { text: `${f.steps.length} steps` }),
    !f.steps.length && h("p", { text: "No steps yet. Press “Add steps”, then click the links on the map in the order things happen." }),
    h("div", { class: "list" }, f.steps.map((st, i) => h("div", { class: "step" + (i === stepIx ? " on" : "") },
      h("span", { class: "n", text: i + 1 }),
      h("div", { class: "w", onclick: e => { if (e.target.tagName !== "INPUT") showStep(i); } }, h("b", { text: stepTitle(st), title: stepTitle(st) }),
        h("input", { value: st.text || "", placeholder: "What happens in this step", onchange: e => patch(i, s2 => s2[i].text = e.target.value.trim()) })),
      h("div", { class: "ops" }, !st.at && h("button", { class: "mini", text: "⇄", title: "Reply: travel the link backwards", onclick: () => patch(i, s2 => s2[i].reverse = !s2[i].reverse) }),
        h("button", { class: "mini", text: "↑", title: "Move up", disabled: !i, onclick: () => move(i, -1) }), h("button", { class: "mini", text: "↓", title: "Move down", disabled: i === f.steps.length - 1, onclick: () => move(i, 1) }),
        h("button", { class: "mini", text: "✕", title: "Remove step", onclick: () => { stepIx = -1; patch(i, s2 => s2.splice(i, 1)); } })))))];
}
function issuesPanel() {
  if (!findings) return [h("h3", { text: "Issues" }), h("p", { text: "Checking the map…" })];
  const all = [...findings.errors.map(f => ({ ...f, severity: "error" })), ...findings.warnings];
  const open = f => { if (by[f.subject]) jumpTo(f.subject); else if (conn(f.subject)) showLink(f.subject); else if (M.flows.some(x => x.id === f.subject)) { flowId = f.subject; tab = "flows"; refresh(); } };
  return [h("h3", { text: "Issues" }), all.length ? h("p", { text: `${findings.errors.length} errors, ${findings.warnings.length} warnings. Click one to go to it.` }) : h("p", { class: "ok", text: "No issues. The map is consistent." }),
    h("div", { class: "list" }, all.map(f => h("div", { class: "find " + (f.severity === "error" ? "error" : ""), onclick: () => open(f) }, h("b", { text: `${by[f.subject]?.name || f.subject}` }), h("span", { text: f.message }), f.fix && h("small", { text: " Fix: " + f.fix }))))];
}

/* ---------- export ---------- */
function exportSvg() {
  const b = bounds(focus ? 70 : 30), svg = $("#svg").cloneNode(true), css = getComputedStyle(document.documentElement);
  svg.querySelectorAll(".port,.overlay,.hit").forEach(x => x.remove());
  svg.querySelectorAll(".sel").forEach(x => x.classList.remove("sel"));
  svg.querySelector("#cam").removeAttribute("transform");
  const resolve = t => { for (let i = 0; i < 4 && t.includes("var("); i++) t = t.replace(/var\((--[\w-]+)\)/g, (m, v) => css.getPropertyValue(v).trim() || "currentColor"); return t; };
  svg.querySelector("style").textContent = resolve(SVG_CSS);
  svg.querySelectorAll("[stroke^='var('],[style*='var(']").forEach(x => { if (x.getAttribute("stroke")) x.setAttribute("stroke", resolve(x.getAttribute("stroke"))); if (x.getAttribute("style")) x.setAttribute("style", resolve(x.getAttribute("style"))); });
  svg.setAttribute("viewBox", `${b.x} ${b.y} ${b.w} ${b.h}`); svg.setAttribute("width", b.w); svg.setAttribute("height", b.h); svg.removeAttribute("id");
  svg.insertBefore(s("rect", { x: b.x, y: b.y, width: b.w, height: b.h, fill: css.getPropertyValue("--canvas").trim() }), svg.querySelector("#cam"));
  return { text: '<?xml version="1.0" encoding="UTF-8"?>\n' + new XMLSerializer().serializeToString(svg), w: b.w, h: b.h };
}
function exportAs(kind) {
  const name = `${PROJECT || "map"}-${focus || "context"}`, out = exportSvg(), blob = new Blob([out.text], { type: "image/svg+xml" });
  if (kind === "svg") return download(name + ".svg", blob);
  const img = new Image(), url = URL.createObjectURL(blob);
  img.onload = () => { const c = h("canvas", { width: out.w * 2, height: out.h * 2 }); c.getContext("2d").drawImage(img, 0, 0, c.width, c.height); URL.revokeObjectURL(url); c.toBlob(b => download(name + ".png", b), "image/png"); };
  img.onerror = () => { URL.revokeObjectURL(url); toast("Could not render the PNG. Export SVG instead."); };
  img.src = url;
}

/* ---------- wiring ---------- */
$("#undo").onclick = () => travel(undo, redo, "inv"); $("#redo").onclick = () => travel(redo, undo, "op");
$("#fit").onclick = fit; $("#zin").onclick = () => zoomAt(1.25); $("#zout").onclick = () => zoomAt(.8);
$("#tidy").onclick = () => { const ps = M.positions[viewKey()] || {}; if (!Object.keys(ps).length) return fit(); commitPositions(Object.fromEntries(Object.keys(ps).map(id => [id, null]))); fit(); };
$("#export").onclick = e => { e.stopPropagation(); $("#exportpop").hidden = !$("#exportpop").hidden; };
$("#exportpop").onclick = e => { const k = e.target.dataset?.x; if (k) exportAs(k); };
addEventListener("click", () => $("#exportpop").hidden = true);
$("#find").onchange = e => { const v = e.target.value.trim().toLowerCase(), o = M?.objects.find(x => (x.name || "").toLowerCase() === v || x.id === v) || M?.objects.find(x => (x.name || "").toLowerCase().includes(v)); if (o) { jumpTo(o.id); e.target.value = ""; } };
document.querySelectorAll("#tabs [data-t]").forEach(b => b.onclick = () => { tab = b.dataset.t; renderPanel(); });
function setSide(hidden) { $("main").classList.toggle("noside", hidden); $("#expand").hidden = !hidden; try { localStorage.setItem("strata-arch-side", hidden ? "0" : "1"); } catch { } if (V) draw(); }
$("#collapse").onclick = () => setSide(true); $("#expand").onclick = () => setSide(false);
addEventListener("keydown", e => {
  if (!M || /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
  const mod = e.ctrlKey || e.metaKey, k = e.key.toLowerCase();
  if (mod && k === "z") { e.preventDefault(); return e.shiftKey ? travel(redo, undo, "op") : travel(undo, redo, "inv"); }
  if (mod && k === "y") { e.preventDefault(); return travel(redo, undo, "op"); }
  if (mod && k === "a") { e.preventDefault(); sel = new Set([...V.nodes].filter(([, n]) => !n.ext).map(([id]) => id)); selEdge = selConn = null; return refresh(); }
  if (mod || e.altKey) return;
  if (k === "delete" || k === "backspace") { e.preventDefault(); return removeSelection(); }
  if (k === "escape") { if (adding) { adding = false; return refresh(); } if (sel.size || selEdge) { sel.clear(); selEdge = selConn = null; return refresh(); } if (focus) return go(by[focus].parent || null); }
  if (k === "f") return fit();
  if (k === "+" || k === "=") return zoomAt(1.25);
  if (k === "-") return zoomAt(.8);
  if ((k === "f2" || k === "enter") && sel.size === 1) { const id = [...sel][0], at = screenOf(id); e.preventDefault();
    if (k === "enter" && CHILD[by[id].type]?.length && !V.nodes.get(id).ext) return go(id);
    return inlineEdit(at.x, at.y - 30 * cam.k, by[id].name || "", "Name", name => updateObject(id, { name })); }
});
addEventListener("resize", () => V && draw());
function theme() { try { const t = localStorage.getItem("strata-theme"); if (t) document.documentElement.dataset.theme = t; } catch { } }
addEventListener("storage", e => { if (e.key === "strata-theme") { theme(); if (V) draw(); } });

(async function boot() {
  theme();
  try { setSide(localStorage.getItem("strata-arch-side") === "0"); } catch { }
  try { await reload(); } catch (e) { toast(e.message); }
  if (!M) return refresh();
  fromHash(); check();
})();
// #<object id>: open that object's level (a container opens its inside). The shell deep-links tasks to map objects this way.
function fromHash() {
  let id = ""; try { id = decodeURIComponent(location.hash.slice(1)).split("/")[0]; } catch { }
  if (by[id] && kids(id).length) go(id); else if (by[id]) jumpTo(id); else go(null);
}
addEventListener("hashchange", () => M && fromHash());
