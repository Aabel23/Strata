// Size the canvas to the element x DPR, clear it, apply the camera, no clip. Returns ctx (chart units).
export function prepare(canvas, cam) {
  const dpr = window.devicePixelRatio || 1;
  const w = Math.round(cam.W * dpr), h = Math.round(cam.H * dpr);
  if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
  const ctx = canvas.getContext('2d');
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, w, h);
  const k = dpr * cam.s0 * cam.scale;
  ctx.setTransform(k, 0, 0, k, dpr * (cam.ox + cam.tx * cam.s0), dpr * (cam.oy + cam.ty * cam.s0));
  return ctx;
}

export function clear(canvas) {
  const ctx = canvas.getContext('2d');
  ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, canvas.width, canvas.height);
}
