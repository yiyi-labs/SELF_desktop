import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
import {inspectModel} from './inspect-model.mjs';
const source=await fs.readFile('assets/sample-head.glb');
function altered(edit){
 const oldLength=source.readUInt32LE(12),g=JSON.parse(source.subarray(20,20+oldLength));edit(g);
 const json=Buffer.from(JSON.stringify(g)),padded=Buffer.alloc(Math.ceil(json.length/4)*4,32);json.copy(padded);
 const tail=source.subarray(20+oldLength),b=Buffer.alloc(20+padded.length+tail.length);
 source.copy(b,0,0,20);b.writeUInt32LE(b.length,8);b.writeUInt32LE(padded.length,12);padded.copy(b,20);tail.copy(b,20+padded.length);return b;
}
const cases=[
 ['existing textured mesh',source,true],
 ['PLY renamed GLB',Buffer.from('ply\nformat ascii 1.0\n'),false],
 ['point primitive',altered(g=>g.meshes[0].primitives[0].mode=0),false],
 ['missing UV',altered(g=>delete g.meshes[0].primitives[0].attributes.TEXCOORD_0),false],
 ['external image',altered(g=>{g.images[0]={uri:'https://example.invalid/face.jpg'};}),false],
 ['unverified Gaussian extension',altered(g=>g.extensionsUsed.push('KHR_gaussian_splatting')),false],
 ['unbaked transform',altered(g=>g.nodes[0].scale=[2,2,2]),false]
];
const results=[];
for(const [name,bytes,accepted]of cases){const r=await inspectModel(bytes);assert.equal(r.structurallyCompatible,accepted,name);results.push({name,status:'passed',structurallyCompatible:r.structurallyCompatible,errors:r.errors});}
await fs.writeFile('docs/evidence/model-inspection-tests.json',JSON.stringify({environment:'Node file validation; NOT reconstruction or device rendering',date:new Date().toISOString(),results},null,2));
console.log(`${results.length}/${results.length} model contract checks passed`);
