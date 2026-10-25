import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { adapt } from '../web/js/adapt.js';
import { layoutSync } from '../web/js/layout.js';

const rd = (p) => JSON.parse(readFileSync(new URL(p, import.meta.url), 'utf8'));
const raw = rd('./fixtures/endo-graph.json');
const schema = rd('../contract/graph.schema.json');

// tiny checker for the subset of JSON Schema the contract uses
function check(s, v, root = schema, path = '$') {
  if (s.$ref) return check(s.$ref.split('/').slice(1).reduce((o, k) => o[k], root), v, root, path);
  const types = [].concat(s.type ?? []);
  const t = v === null ? 'null' : Array.isArray(v) ? 'array' : Number.isInteger(v) ? 'integer' : typeof v;
  if (types.length && !types.includes(t)) throw new Error(`${path}: ${t} not in ${types}`);
  if (s.minimum !== undefined && v < s.minimum) throw new Error(`${path}: below minimum`);
  if (t === 'array' && s.items) v.forEach((x, i) => check(s.items, x, root, `${path}[${i}]`));
  if (t === 'object') {
    for (const k of s.required ?? []) if (!(k in v)) throw new Error(`${path}: missing ${k}`);
    for (const k of Object.keys(v)) {
      if (s.properties?.[k]) check(s.properties[k], v[k], root, `${path}.${k}`);
      else if (s.additionalProperties === false) throw new Error(`${path}: extra ${k}`);
    }
  }
}

test('adapt fixture: counts, communities, hidden kinds, no dangling edges, schema', () => {
  const g = adapt(raw);
  check(schema, g);
  assert.equal(g.nodes.length, 527 - 1); // the one Community node is hidden
  assert.ok(!g.kinds.includes('Community') && !g.kinds.includes('Process'));
  const ids = new Set(g.nodes.map((n) => n.id));
  for (const e of g.edges) assert.ok(ids.has(e.source) && ids.has(e.target) && e.source !== e.target);
  assert.equal(new Set(g.edges.map((e) => `${e.source}|${e.target}|${e.type}`)).size, g.edges.length);
  assert.ok(!g.edgeTypes.includes('MEMBER_OF')); // its target was hidden
  assert.equal(g.communities.length, 1);
  assert.equal(g.communities[0].size, 2);
  assert.equal(g.nodes.filter((n) => n.community === g.communities[0].name).length, 2);
  assert.equal(g.nodes.reduce((s, n) => s + n.degree, 0), g.edges.length * 2);
});

test('adapt is deterministic and order-independent', () => {
  const rev = { nodes: [...raw.nodes].reverse(), relationships: [...raw.relationships].reverse() };
  assert.deepEqual(adapt(rev), adapt(raw));
});

test('adapt tolerates unknown labels and properties', () => {
  const g = adapt({
    nodes: [{ id: 'x', label: 'Weird' }, { id: 'y', label: 'Other', properties: { foo: 1 } }],
    relationships: [
      { id: 'r', type: 'ZAP', sourceId: 'x', targetId: 'y' },
      { id: 's', type: 'ZAP', sourceId: 'x', targetId: 'gone' },
    ],
  });
  check(schema, g);
  assert.equal(g.nodes.length, 2);
  assert.equal(g.edges.length, 1);
});

test('adapt skips malformed entries and coerces fields', () => {
  const g = adapt({
    nodes: [null, { label: 'File' }, { id: 5 }, { id: 'a', label: 7, properties: { name: 3, filePath: 9 } }],
    relationships: [null, { type: 'X', sourceId: 'a' }, { type: 'X', sourceId: 'a', targetId: 'a' }],
  });
  check(schema, g);
  assert.deepEqual(g.nodes, [{ id: 'a', kind: '7', name: '3', file: '9', community: null, degree: 0 }]);
  assert.equal(g.edges.length, 0);
});

test('adapt picks smallest community id regardless of relationship order', () => {
  const nodes = [
    { id: 's', label: 'Function', properties: { name: 's' } },
    { id: 'c2', label: 'Community', properties: { name: 'two' } },
    { id: 'c1', label: 'Community', properties: { name: 'one' } },
  ];
  const rels = [
    { type: 'MEMBER_OF', sourceId: 's', targetId: 'c2' },
    { type: 'MEMBER_OF', sourceId: 's', targetId: 'c1' },
  ];
  const a = adapt({ nodes, relationships: rels });
  const b = adapt({ nodes, relationships: [...rels].reverse() });
  assert.deepEqual(a, b);
  assert.equal(a.nodes[0].community, 'one');
  assert.deepEqual(a.communities.map((c) => [c.id, c.size]), [['c1', 1]]);
});

test('layoutSync: bounds and determinism', () => {
  const g = adapt(raw);
  const a = layoutSync(g, { seed: 7 });
  assert.equal(a.size, g.nodes.length);
  for (const { x, y } of a.values()) assert.ok(x >= 80 && x <= 2320 && y >= 80 && y <= 1120);
  assert.deepEqual([...layoutSync(g, { seed: 7 })], [...a]);
  assert.notDeepEqual([...layoutSync(g, { seed: 8 })], [...a]);
});
