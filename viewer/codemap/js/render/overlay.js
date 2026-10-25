// Selection ring/cross and hover label, drawn in the same world transform as the sky.
export function createOverlay() {
  const world = document.getElementById('overlay-world'), ring = document.getElementById('selection-ring'),
    cross = document.getElementById('selection-cross'), label = document.getElementById('hover-label');
  let k = 1, at = null; // k: chart units per screen px (keeps ring/label a constant on-screen size); at: marked point
  function mark(x, y) { // x == null hides
    ring.classList.toggle('visible', x != null); cross.classList.toggle('visible', x != null);
    at = x == null ? null : [x, y];
    if (!at) return;
    ring.setAttribute('cx', x); ring.setAttribute('cy', y);
    cross.setAttribute('transform', `translate(${x} ${y}) scale(${k})`);
  }
  return {
    svg: document.getElementById('overlay'),
    mark,
    setCamera(cam) {
      world.setAttribute('transform', `translate(${cam.tx} ${cam.ty}) scale(${cam.scale})`);
      k = 1 / (cam.s0 * cam.scale);
      label.setAttribute('font-size', 12 * k); label.setAttribute('stroke-width', 3 * k);
      ring.setAttribute('r', 11 * k); ring.setAttribute('stroke-width', 1.15 * k); cross.setAttribute('stroke-width', .8 * k);
      if (at) mark(...at);
    },
    hover(x, y, s) { // s == null hides
      if (s == null) { label.setAttribute('visibility', 'hidden'); return; }
      label.textContent = s; label.setAttribute('x', x + 10 * k); label.setAttribute('y', y - 9 * k);
      label.setAttribute('visibility', 'visible');
    },
  };
}
