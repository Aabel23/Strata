import { loadRaw } from './source.js';
import { adapt } from './adapt.js';
import { layout } from './layout.js';
import { createCamera } from './camera.js';
import { createPanel } from './panel.js';
import { createControls } from './controls.js';
import { clear } from './render/canvas.js';
import { buildSky } from './render/sky.js';
import { createOverlay } from './render/overlay.js';
import { drawEdges } from './render/edges.js';
import { drawStars } from './render/stars.js';
import { buildScene, applyGravity, hit, neighbours, GRAVITY_MAX } from './render/scene.js';

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const edgesCanvas = $('edges'), starsCanvas = $('stars');

let scene = null, enabled = new Uint8Array(0), hover = -1, sel = -1, nbr = new Uint8Array(0), raf = 0, token = 0;
const perf = params.get('perf') === '1', frames = (window.__celesteFrames = []); // ?perf=1 records frame draw times (ms)

const sky = buildSky();
const overlay = createOverlay();
const panel = createPanel({ onPick: (i) => { select(i); cam.focus(scene.x[i], scene.y[i]); }, onClose: () => select(-1) });

function frame() {
  raf = 0;
  if (!scene) { clear(edgesCanvas); clear(starsCanvas); return; }
  const t = perf ? performance.now() : 0;
  drawEdges(edgesCanvas, cam, scene, enabled, sel);
  drawStars(starsCanvas, cam, scene, hover, sel, nbr);
  if (perf) frames.push(performance.now() - t);
}
const schedule = () => { if (!raf) raf = requestAnimationFrame(frame); };

function onCamera() {
  const t = `translate(${cam.tx} ${cam.ty}) scale(${cam.scale})`;
  sky.world.setAttribute('transform', t);
  overlay.setCamera(cam);
  if (sel >= 0) placePanel();
  schedule();
}
const cam = createCamera(overlay.svg, {
  onChange: onCamera,
  onIdle: () => schedule(),
  onTap: (e) => select(pick(e)), // empty space clears
  onHover: (e) => setHover(e ? pick(e) : -1),
});
const controls = createControls({
  cam,
  onGravity: (g) => { if (!scene) return; applyGravity(scene, g); sky.setGlow(Math.min(1, g / GRAVITY_MAX)); refreshMarks(); schedule(); },
  onEdgeToggle: (t, on) => { enabled[t] = on ? 1 : 0; schedule(); },
  onEscape: () => select(-1),
});

function pick(e) {
  if (!scene) return -1;
  const [cx, cy] = cam.toChart(e.clientX, e.clientY);
  return hit(scene, cx, cy, 9 / (cam.s0 * cam.scale));
}

function placePanel() { // card sits beside the selected node and follows pan/zoom
  panel.place((cam.ox + (cam.tx + scene.x[sel] * cam.scale) * cam.s0), cam.oy + (cam.ty + scene.y[sel] * cam.scale) * cam.s0, cam.W, cam.H);
}
function show() { // popup only while a node is selected; hover just shows the label
  const i = sel;
  if (i < 0) return panel.hide();
  const nb = neighbours(scene, i).map((j) => ({ index: j, name: scene.graph.nodes[j].name, degree: scene.graph.nodes[j].degree }));
  panel.showNode(scene.graph.nodes[i], nb); placePanel();
}
function refreshMarks() {
  const i = hover >= 0 ? hover : sel;
  overlay.mark(i >= 0 ? scene.x[i] : null, i >= 0 ? scene.y[i] : null);
  overlay.hover(hover >= 0 ? scene.x[hover] : 0, hover >= 0 ? scene.y[hover] : 0, hover >= 0 ? scene.graph.nodes[hover].name : null, cam);
}
function setHover(i) {
  if (i === hover) return;
  hover = i; overlay.svg.classList.toggle('hovering', i >= 0);
  refreshMarks(); schedule();
}
function select(i) {
  nbr.fill(0);
  sel = i;
  if (i >= 0) for (const j of neighbours(scene, i, Infinity)) nbr[j] = 1;
  show(); refreshMarks(); schedule();
}

async function load(name) {
  const my = ++token, t0 = performance.now();
  scene = null; hover = sel = -1; refreshOverlayOff(); // drops the previous graph from canvases + overlay
  panel.message('Loading', name, 'Reading code map…');
  controls.setEdgeTypes([]); controls.resetGravity(); sky.setGlow(0);
  try {
    const raw = await loadRaw(name); const t1 = performance.now();
    if (my !== token) return;
    const graph = adapt(raw); const t2 = performance.now();
    if (!graph.nodes.length) return panel.message('Empty', name, 'This graph has no nodes.');
    panel.message('Loading', name, `Laying out ${graph.nodes.length.toLocaleString('en-US')} nodes…`);
    const pos = await layout(graph); const t3 = performance.now();
    if (my !== token) return;
    scene = buildScene(graph, pos);
    enabled = new Uint8Array(graph.edgeTypes.length).fill(1);
    nbr = new Uint8Array(scene.n);
    controls.setEdgeTypes(graph.edgeTypes);
    cam.reset(); show();
    requestAnimationFrame(() => {
      frame();
      const t4 = performance.now(), f = (a, b) => (b - a).toFixed(0);
      console.log(`[celeste] ${name}: nodes=${scene.n} edges=${graph.edges.length} load=${f(t0, t1)}ms adapt=${f(t1, t2)}ms layout=${f(t2, t3)}ms scene+paint=${f(t3, t4)}ms total=${f(t0, t4)}ms`);
    });
  } catch (err) {
    if (my !== token) return;
    console.error('[celeste] load failed', err);
    panel.message('Error', 'Could not load', `${name}: ${err.message}`);
  }
}
function refreshOverlayOff() { overlay.mark(null); overlay.hover(0, 0, null, cam); schedule(); }

window.addEventListener('resize', () => cam.resize());
cam.resize();

load(params.get('project') || '');
