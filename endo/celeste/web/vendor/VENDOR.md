# Vendored libraries

Self-contained ESM, no bare imports, no runtime CDN.

| File | Package | Version | Source | License |
|------|---------|---------|--------|---------|
| graphology.mjs | graphology | 0.26.0 | `dist/graphology.umd.min.js` from the npm package (https://www.npmjs.com/package/graphology), wrapped as ESM with a 2-line prefix and 1-line suffix | MIT |
| graphology-layout-forceatlas2.mjs | graphology-layout-forceatlas2 | 0.10.1 | https://esm.sh/graphology-layout-forceatlas2@0.10.1/es2022/graphology-layout-forceatlas2.bundle.mjs (bundles graphology-utils; sourcemap comment removed) | MIT |

## Checksums (sha256)

```
0eed476a6d8aabaa6c0fabb4364bd1aa07ab1c0194cc88ec4b5208c86ee9e4b7  graphology.mjs
bcbf87552188ee686b073c53df5f292b7bac8419aac7a591b465fb44a68e5d22  graphology-layout-forceatlas2.mjs
```

Bundled graphology-utils: 2.5.2 (inferred; the bundle does not stamp it). esm.sh resolved FA2 0.10.1's dependency range `^2.1.0`, and 2.5.2 is the latest 2.x on npm.
