// One camera for SVG + canvases. Chart space is 2400x1200 (the SVG viewBox); the view is
// translate(tx,ty) scale(scale) in chart units, fitted into the element with a "meet" scale s0.
export const BOUNDS = { left: 76, right: 2324, top: 78, bottom: 1122 }; // where nodes are laid out
const PAN = { left: 0, right: 2400, top: 0, bottom: 1200 }; // what the camera may show

export function createCamera(el, { onChange, onIdle, onTap, onHover }) {
  const cam = { scale: 1, tx: 0, ty: 0, W: 1, H: 1, s0: 1, ox: 0, oy: 0, left: 0, top: 0, vl: PAN.left, vr: PAN.right,
    vis: { x0: 0, y0: 0, x1: 0, y1: 0 }, busy: false, narrow: false };
  let idle = 0;
  let drag = null;

  function clamp() {
    const s = cam.scale;
    cam.tx = Math.max(cam.vr - PAN.right * s, Math.min(cam.vl - PAN.left * s, cam.tx));
    cam.ty = Math.max(PAN.bottom - PAN.bottom * s, Math.min(PAN.top - PAN.top * s, cam.ty));
  }
  // busy = camera moved in the last 140ms: renderers may draw reduced detail, then onIdle repaints in full
  const changed = () => {
    clamp();
    const v = cam.vis, k = cam.s0 * cam.scale;
    v.x0 = -(cam.ox + cam.tx * cam.s0) / k; v.x1 = (cam.W - cam.ox - cam.tx * cam.s0) / k;
    v.y0 = -(cam.oy + cam.ty * cam.s0) / k; v.y1 = (cam.H - cam.oy - cam.ty * cam.s0) / k;
    cam.busy = true; clearTimeout(idle); idle = setTimeout(() => { cam.busy = false; onIdle?.(); }, 140);
    onChange();
  };
  const toView = (cx, cy) => [(cx - cam.left - cam.ox) / cam.s0, (cy - cam.top - cam.oy) / cam.s0];
  cam.toChart = (cx, cy) => { const [vx, vy] = toView(cx, cy); return [(vx - cam.tx) / cam.scale, (vy - cam.ty) / cam.scale]; };

  cam.resize = () => {
    const r = el.getBoundingClientRect();
    cam.W = Math.max(1, r.width); cam.H = Math.max(1, r.height); cam.left = r.left; cam.top = r.top;
    // narrow screens: fill the height and let dragging reveal the rest (the study's approach)
    cam.narrow = window.innerWidth <= 700;
    cam.s0 = cam.narrow ? cam.H / 1200 : Math.min(cam.W / 2400, cam.H / 1200);
    cam.ox = (cam.W - 2400 * cam.s0) / 2; cam.oy = (cam.H - 1200 * cam.s0) / 2;
    const w = cam.W / cam.s0, h = cam.H / cam.s0, left = -cam.ox / cam.s0, top = -cam.oy / cam.s0;
    cam.vl = cam.narrow ? left : PAN.left; cam.vr = cam.narrow ? left + w : PAN.right;
    // viewBox == the whole element, so the SVG layers are never letterboxed
    for (const svg of document.querySelectorAll('svg.layer')) svg.setAttribute('viewBox', `${left} ${top} ${w} ${h}`);
    changed();
  };
  cam.zoomAt = (factor, cx, cy) => {
    const [vx, vy] = toView(cx, cy);
    const next = Math.max(1, Math.min(8, cam.scale * factor));
    const wx = (vx - cam.tx) / cam.scale, wy = (vy - cam.ty) / cam.scale;
    cam.scale = next; cam.tx = vx - wx * next; cam.ty = vy - wy * next;
    changed();
  };
  cam.zoomCenter = (factor) => cam.zoomAt(factor, cam.left + cam.W / 2, cam.top + cam.H / 2);
  cam.reset = () => { cam.scale = 1; cam.tx = 0; cam.ty = 0; changed(); };
  cam.focus = (x, y) => { // centre a chart point in the view, keeping the zoom
    // put the chart point at the screen centre
    cam.tx = (cam.W / 2 - cam.ox) / cam.s0 - x * cam.scale; cam.ty = (cam.H / 2 - cam.oy) / cam.s0 - y * cam.scale; changed();
  };

  el.addEventListener('wheel', (e) => { e.preventDefault(); cam.zoomAt(Math.exp(-e.deltaY * .0014), e.clientX, e.clientY); }, { passive: false });
  el.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    drag = { id: e.pointerId, x: e.clientX, y: e.clientY, tx: cam.tx, ty: cam.ty, moved: false };
    el.setPointerCapture(e.pointerId);
  });
  el.addEventListener('pointermove', (e) => {
    if (!drag || drag.id !== e.pointerId) { onHover?.(e); return; }
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
    if (drag.moved) { el.classList.add('dragging'); cam.tx = drag.tx + dx / cam.s0; cam.ty = drag.ty + dy / cam.s0; changed(); }
  });
  el.addEventListener('pointerup', (e) => {
    if (!drag || drag.id !== e.pointerId) return;
    if (!drag.moved) onTap?.(e);
    drag = null; el.classList.remove('dragging');
  });
  el.addEventListener('pointercancel', () => { drag = null; el.classList.remove('dragging'); });
  el.addEventListener('pointerleave', () => { if (!drag) onHover?.(null); });
  return cam;
}
