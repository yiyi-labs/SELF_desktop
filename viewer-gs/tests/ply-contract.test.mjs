// Parse the synthetic gsplat export through the locked PlayCanvas 2.22.4
// PLY loader.  This is a data/field probe, not a GPU/browser visual test.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import { PlyParser } from '../../backend/.sources/playcanvas/node_modules/playcanvas/build/playcanvas/src/framework/parsers/ply.js';

const path = resolve(fileURLToPath(new URL('.', import.meta.url)),
  '../../backend/.sources/gs-contract-probe/anisotropic-occlusion.ply');
const bytes = await readFile(path);
let parsed;
const app = { scene: { gsplatCentersEnabled: false }, graphicsDevice: null };
const asset = {
  file: { contents: Promise.resolve(new Response(bytes)) },
  data: { reorder: false },
  fire(event, value) { if (event === 'load:data') parsed = value; }
};
await new PlyParser(app).load({ load: 'synthetic.ply' }, () => {}, asset);
assert.ok(parsed, 'PlayCanvas did not parse the PLY');
assert.equal(parsed.numSplats, 4);
assert.equal(parsed.shBands, 3);
const { Vec3 } = await import('../../backend/.sources/playcanvas/node_modules/playcanvas/build/playcanvas/src/core/math/vec3.js');
const { Quat } = await import('../../backend/.sources/playcanvas/node_modules/playcanvas/build/playcanvas/src/core/math/quat.js');
const { Color } = await import('../../backend/.sources/playcanvas/node_modules/playcanvas/build/playcanvas/src/core/math/color.js');
const p = new Vec3(), q = new Quat(), s = new Vec3(), c = new Color();
parsed.createIter(p, q, s, c).read(0);
assert.ok(Math.abs(p.z - 1.7) < 1e-5);
assert.ok(Math.abs(s.x - .26) < 1e-5);
assert.ok(Math.abs(s.y - .07) < 1e-5);
assert.ok(Math.abs(q.w - .8660254) < 1e-5);
assert.ok(Math.abs(c.r - .9) < 1e-5);
assert.ok(Math.abs(c.a - .82) < 1e-5);
assert.ok(Math.abs(parsed.getProp('f_rest_0')[0] - .08) < 1e-6);
assert.ok(Math.abs(parsed.getProp('f_rest_15')[0] + .05) < 1e-6);
assert.ok(Math.abs(parsed.getProp('f_rest_30')[0] - .11) < 1e-6);
console.log(JSON.stringify({ playcanvasVersion: '2.22.4', parsedSplats: parsed.numSplats,
  firstCenterZ: p.z, firstScaleX: s.x, firstOpacity: c.a }));
