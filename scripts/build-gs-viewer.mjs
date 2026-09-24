import { build } from 'esbuild';
import { copyFileSync, mkdirSync, readFileSync } from 'node:fs';

const destination='entry/src/main/resources/rawfile';
const dependency=JSON.parse(readFileSync('node_modules/playcanvas/package.json','utf8'));
if(dependency.version!=='2.22.4'||dependency.license!=='MIT')throw new Error('PlayCanvas version or license changed. Review before packaging.');
await build({entryPoints:['viewer-gs/main.js'],bundle:true,platform:'browser',format:'iife',target:'es2020',minify:true,external:['node:worker_threads'],outfile:`${destination}/gs-viewer.js`});
copyFileSync('viewer-gs/index.html',`${destination}/gs-viewer.html`);
mkdirSync(`${destination}/licenses`,{recursive:true});
copyFileSync('node_modules/playcanvas/LICENSE',`${destination}/licenses/playcanvas-LICENSE.txt`);
console.log('Prepared offline 3DGS viewer from pinned PlayCanvas engine.');
