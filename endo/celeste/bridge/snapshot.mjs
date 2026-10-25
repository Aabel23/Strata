// node snapshot.mjs <repo> [--backend URL] -> celeste/data/<repo>.json
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repo = process.argv[2];
const bi = process.argv.indexOf('--backend');
const backend = bi > 0 ? process.argv[bi + 1] : 'http://127.0.0.1:4747';
if (!repo || !/^[A-Za-z0-9._-]+$/.test(repo) || repo === '.' || repo === '..') {
  console.error('usage: snapshot.mjs <repo> [--backend URL]  (repo matches ^[A-Za-z0-9._-]+$)'); process.exit(2);
}
const fail = m => { console.error('snapshot failed: ' + m); process.exit(1); };
let body, g;
try {
  const res = await fetch(`${backend}/api/graph?repo=${encodeURIComponent(repo)}`);
  if (!res.ok) fail(`backend ${res.status}: ${await res.text()}`);
  body = await res.text();
  g = JSON.parse(body);
} catch (e) { fail(e.message); }
const out = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'data', `${repo}.json`);
fs.writeFileSync(out + '.tmp', body);
fs.renameSync(out + '.tmp', out);
console.log(`${out}: ${g.nodes?.length} nodes, ${g.relationships?.length} relationships`);
