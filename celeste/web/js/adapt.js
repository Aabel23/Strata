// The ONLY module that knows the GitNexus JSON shape.
const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

export function adapt(raw, { hideKinds = ['Community', 'Process'] } = {}) {
  const hide = new Set(hideKinds);
  const isStr = (v) => typeof v === 'string';
  const all = new Map((raw?.nodes ?? []).filter((n) => n && isStr(n.id)).map((n) => [n.id, n]));
  const rels = (raw?.relationships ?? []).filter((r) => r && isStr(r.sourceId) && isStr(r.targetId));

  // symbol -> community via MEMBER_OF (symbol -> community)
  const commOf = new Map();
  const commSize = new Map();
  const commName = (c) => c.properties?.heuristicLabel || c.properties?.name || c.id;
  for (const r of rels) {
    const c = all.get(r.targetId);
    // several MEMBER_OF: smallest community id wins, independent of relationship order
    if (r.type === 'MEMBER_OF' && c?.label === 'Community' && all.has(r.sourceId) && !(commOf.get(r.sourceId) <= c.id)) {
      commOf.set(r.sourceId, c.id);
    }
  }
  for (const c of commOf.values()) commSize.set(c, (commSize.get(c) ?? 0) + 1);

  const kept = new Map();
  for (const n of all.values()) {
    if (hide.has(n.label)) continue;
    const p = n.properties ?? {};
    kept.set(n.id, {
      id: n.id,
      kind: n.label == null ? 'Unknown' : String(n.label),
      name: p.name == null ? n.id : String(p.name),
      file: p.filePath == null ? null : String(p.filePath),
      community: commOf.has(n.id) ? commName(all.get(commOf.get(n.id))) : null,
      degree: 0,
    });
  }

  const seen = new Set();
  const edges = [];
  for (const r of rels) {
    const { sourceId: source, targetId: target, type } = r;
    if (source === target || !kept.has(source) || !kept.has(target)) continue;
    const key = `${source}\0${target}\0${type}`;
    if (seen.has(key)) continue;
    seen.add(key);
    edges.push({ source, target, type });
    kept.get(source).degree++;
    kept.get(target).degree++;
  }
  edges.sort((a, b) => cmp(a.source, b.source) || cmp(a.target, b.target) || cmp(a.type, b.type));

  const nodes = [...kept.values()].sort((a, b) => cmp(a.id, b.id));
  const communities = [...commSize]
    .map(([id, size]) => ({ id, name: commName(all.get(id)), size }))
    .sort((a, b) => cmp(a.id, b.id));
  return {
    nodes,
    edges,
    communities,
    kinds: [...new Set(nodes.map((n) => n.kind))].sort(),
    edgeTypes: [...new Set(edges.map((e) => e.type))].sort(),
  };
}
