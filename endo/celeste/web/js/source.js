// Fetches raw graph data. Knows URLs only; GitNexus JSON shape is adapt.js's business.
async function getJson(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url} -> HTTP ${res.status}`);
  return res.json();
}

export async function listRepos() {
  const data = await getJson('/api/repos');
  return data.map((r) => r.name); // backend returns a bare array of {name, ...}
}

export function loadRaw({ repo, snapshot = false }) {
  const r = encodeURIComponent(repo);
  return getJson(snapshot ? `data/${r}.json` : `/api/graph?repo=${r}`);
}
