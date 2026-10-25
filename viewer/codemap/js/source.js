// Fetches the raw graph from Strata. Knows URLs only; GitNexus JSON shape is adapt.js's business.
export async function loadRaw(project) {
  const res = await fetch(`/api/codemap?project=${encodeURIComponent(project)}`);
  if (res.ok) return res.json();
  const body = await res.json().catch(() => ({}));
  throw Object.assign(new Error(body.error || `HTTP ${res.status}`), { building: !!body.building, buildState: res.status === 404 && 'building' in body });
}
