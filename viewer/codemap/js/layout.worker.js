import { layoutSync } from './layout.js';

self.onmessage = (e) => self.postMessage([...layoutSync(e.data.graph, e.data.opts)]);
