// Serves celeste/web at /, celeste/data at /data/, proxies /api/* to the GitNexus backend. Node stdlib only.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const arg = (n, d) => { const i = process.argv.indexOf('--' + n); return i > 0 ? process.argv[i + 1] : d; };
const port = Number(arg('port', 4780));
const bport = Number(arg('backend-port', 4747));
const HOST = '127.0.0.1';
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css',
  '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.woff2': 'font/woff2' };

const healthy = () => fetch(`http://${HOST}:${bport}/api/health`, { signal: AbortSignal.timeout(1500) }).then(r => r.ok, () => false);

let child = null;
async function ensureBackend() {
  if (await healthy()) { console.log(`backend already healthy on :${bport} (not started by bridge)`); return; }
  const vendored = path.join(root, 'backend/gitnexus/dist/cli/index.js');
  let cmd, args;
  if (process.env.GITNEXUS_BIN) [cmd, args] = ['node', [process.env.GITNEXUS_BIN]];
  else if (fs.existsSync(path.join(root, 'backend/gitnexus/node_modules'))) [cmd, args] = ['node', [vendored]];
  else [cmd, args] = ['gitnexus', []];
  console.log(`starting backend: ${cmd} ${[...args, 'serve'].join(' ')}`);
  child = spawn(cmd, [...args, 'serve', '--port', String(bport), '--host', HOST], { stdio: 'inherit' });
  child.on('error', e => { console.error(`cannot start backend (${cmd}): ${e.message}`); process.exit(1); });
  child.on('exit', c => { console.log(`backend exited (${c})`); child = null; });
  for (let i = 0; i < 60; i++) {
    if (await healthy()) return;
    if (!child) throw new Error('backend exited during startup');
    await new Promise(r => setTimeout(r, 500));
  }
  throw new Error('backend did not become healthy in 30s');
}

function serveFile(res, base, rel) {
  let p;
  if (rel.includes('\0')) { res.writeHead(400).end('bad request'); return; }
  try { p = path.resolve(base, '.' + path.sep + decodeURIComponent(rel)); } catch { res.writeHead(400).end('bad request'); return; }
  if (p !== base && !p.startsWith(base + path.sep)) { res.writeHead(403).end('forbidden'); return; }
  if (p.includes('\0')) { res.writeHead(400).end('bad request'); return; }
  if (fs.existsSync(p) && fs.statSync(p).isDirectory()) p = path.join(p, 'index.html');
  fs.readFile(p, (err, buf) => {
    if (err) { res.writeHead(404, { 'content-type': 'text/plain' }).end('not found'); return; }
    res.writeHead(200, { 'content-type': TYPES[path.extname(p)] || 'application/octet-stream' }).end(buf);
  });
}

const hostOk = new Set([`${HOST}:${port}`, `localhost:${port}`]);

const handle = (req, res) => {
  if (!hostOk.has(req.headers.host)) { res.writeHead(421).end('misdirected request'); return; }
  const u = new URL(req.url, 'http://x');
  const raw = req.url.split('?')[0];
  if (raw.startsWith('/api/') || raw === '/api') {
    const up = http.request({ host: HOST, port: bport, path: req.url, method: req.method, headers: { ...req.headers, host: `${HOST}:${bport}` } },
      r => { r.on('error', () => res.destroy()); res.writeHead(r.statusCode, r.headers); r.pipe(res); });
    up.on('error', e => { if (res.headersSent) res.destroy(); else res.writeHead(502).end('backend unavailable: ' + e.message); });
    req.on('error', () => up.destroy());
    res.on('close', () => up.destroy());
    req.pipe(up);
  } else if (u.pathname.startsWith('/data/')) serveFile(res, path.join(root, 'data'), u.pathname.slice(6));
  else serveFile(res, path.join(root, 'web'), u.pathname);
};

const server = http.createServer((req, res) => {
  try { handle(req, res); } catch (e) {
    if (res.headersSent) res.destroy(); else res.writeHead(500).end('internal error');
  }
});

const stop = () => { child?.kill(); };
process.on('exit', stop);
for (const s of ['SIGINT', 'SIGTERM', 'SIGHUP']) process.on(s, () => { stop(); process.exit(0); });

await ensureBackend().catch(e => { console.error(e.message); stop(); process.exit(1); });
server.listen(port, HOST, () => console.log(`celeste bridge: http://${HOST}:${port}`));
