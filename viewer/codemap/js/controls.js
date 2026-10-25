import { edgeColor } from './render/palette.js';
const $ = (id) => document.getElementById(id);

export function createControls({ cam, onGravity, onEdgeToggle, onEscape }) {
  const gravity = $('gravity'), out = $('gravity-value'), filters = $('filters'), menu = $('edges-menu'), summary = menu.querySelector('summary');
  let raf = 0;
  $('zoom-in').onclick = () => cam.zoomCenter(1.35);
  $('zoom-out').onclick = () => cam.zoomCenter(1 / 1.35);
  $('reset').onclick = () => cam.reset();
  gravity.addEventListener('input', () => {
    out.textContent = Number(gravity.value).toFixed(2);
    if (!raf) raf = requestAnimationFrame(() => { raf = 0; onGravity(Number(gravity.value)); });
  });
  document.addEventListener('keydown', (e) => {
    const t = e.target;
    if (t instanceof HTMLElement && (t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || (t.tagName === 'INPUT' && (t.type === 'text' || t.type === 'range')))) return;
    if (e.key === '+' || e.key === '=') { e.preventDefault(); cam.zoomCenter(1.35); }
    else if (e.key === '-' || e.key === '_') { e.preventDefault(); cam.zoomCenter(1 / 1.35); }
    else if (e.key === '0') { e.preventDefault(); cam.reset(); }
    else if (e.key === 'Escape') onEscape();
  });
  return {
    resetGravity() { gravity.value = '0'; out.textContent = '0.00'; },
    setEdgeTypes(types) {
      menu.hidden = types.length === 0; menu.open = false; summary.textContent = `Edges (${types.length})`;
      filters.replaceChildren(...types.map((t, i) => {
        const l = document.createElement('label'), c = document.createElement('input'), sw = document.createElement('i');
        c.type = 'checkbox'; c.checked = true; c.onchange = () => onEdgeToggle(i, c.checked);
        sw.style.background = edgeColor(t, i);
        l.append(c, sw, document.createTextNode(t)); return l;
      }));
    },
  };
}
