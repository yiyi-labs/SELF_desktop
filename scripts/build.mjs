import {build} from 'esbuild';
import fs from 'node:fs/promises';
const out='entry/src/main/resources/rawfile/renderer';
await fs.mkdir(out,{recursive:true});await fs.mkdir('dist',{recursive:true});
for(const [dir,test]of [[out,false],['dist',true]]){
 await build({entryPoints:['renderer-web/src/main.ts'],outfile:`${dir}/renderer.js`,bundle:true,format:'iife',target:'es2020',minify:!test,sourcemap:test,define:{__SELF_TEST__:String(test)}});
 for(const name of ['index.html','renderer.css'])await fs.copyFile(`renderer-web/${name}`,`${dir}/${name}`);
}
await fs.cp('assets', 'entry/src/main/resources/rawfile/assets',{recursive:true});
await fs.cp('assets','dist/assets',{recursive:true});
await fs.copyFile('node_modules/three/LICENSE',`${out}/LICENSE-THREE.txt`);
console.log('Built one local IIFE; native rawfile excludes desktop testing entry points.');
