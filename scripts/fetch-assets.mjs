import { mkdir, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
const root = 'assets-src/LeePerrySmith-r186';
await mkdir(root, {recursive:true});
const base = 'https://raw.githubusercontent.com/mrdoob/three.js/r186/';
const files = [
  'examples/models/gltf/LeePerrySmith/LeePerrySmith.glb',
  'examples/models/gltf/LeePerrySmith/Map-COL.jpg',
  'examples/models/gltf/LeePerrySmith/LeePerrySmith_License.txt',
  'examples/webgl_decals.html', 'examples/webgl_multiple_scenes_comparison.html', 'LICENSE', 'package.json'
];
const records = [];
for (const path of files) {
  const response = await fetch(base+path);
  if (!response.ok) throw Error(`${response.status}: ${path}`);
  const bytes = Buffer.from(await response.arrayBuffer());
  const file = path.split('/').at(-1);
  await writeFile(`${root}/${file}`, bytes);
  records.push({path,file,source:base+path,bytes:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex')});
  console.log(file, bytes.length);
}
await writeFile(`${root}/sources.json`, JSON.stringify({tag:'r186',retrievedAt:new Date().toISOString(),files:records},null,2));
