import fs from 'node:fs/promises';
import validator from 'gltf-validator';
await fs.mkdir('docs/evidence',{recursive:true});
const b=await fs.readFile('assets/sample-head.glb');
const report=await validator.validateBytes(new Uint8Array(b),{uri:'sample-head.glb',maxIssues:100});
await fs.writeFile('docs/evidence/gltf-validator.json',JSON.stringify(report,null,2));
const gltf=JSON.parse(b.subarray(20,20+b.readUInt32LE(12))),bin=b.subarray(28+b.readUInt32LE(12));
function accessor(i){const a=gltf.accessors[i],v=gltf.bufferViews[a.bufferView],size={SCALAR:1,VEC2:2,VEC3:3}[a.type];const bytes=bin.subarray((v.byteOffset||0)+(a.byteOffset||0));return a.componentType===5126?new Float32Array(bytes.buffer,bytes.byteOffset,a.count*size):new Uint16Array(bytes.buffer,bytes.byteOffset,a.count*size);}
const p=gltf.meshes[0].primitives[0],uv=accessor(p.attributes.TEXCOORD_0),ind=accessor(p.indices);
const size=1024,owners=new Int32Array(size*size).fill(-1);let overlap=0,covered=0,degenerate=0,editableOverlap=0,lipOverlap=0;
const editable=await fs.readFile('assets/editable.mask'),lip=await fs.readFile('assets/lip.mask');
const cross=(a,b,c)=>(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]);
for(let t=0;t<ind.length;t+=3){
 const pts=[0,1,2].map(k=>[uv[ind[t+k]*2]*size,uv[ind[t+k]*2+1]*size]);
 const area=cross(...pts);if(Math.abs(area)<1e-8){degenerate++;continue;}
 for(let y=Math.max(0,Math.floor(Math.min(...pts.map(p=>p[1]))));y<Math.min(size,Math.ceil(Math.max(...pts.map(p=>p[1]))));y++)
 for(let x=Math.max(0,Math.floor(Math.min(...pts.map(p=>p[0]))));x<Math.min(size,Math.ceil(Math.max(...pts.map(p=>p[0]))));x++){
  const q=[x+.5,y+.5],a=cross(pts[1],pts[2],q)/area,b=cross(pts[2],pts[0],q)/area,c=1-a-b;
  if(Math.min(a,b,c)<=1e-5)continue;
  const i=y*size+x;if(owners[i]>=0){overlap++;if(editable[i])editableOverlap++;if(lip[i])lipOverlap++;}else covered++;owners[i]=t/3;
 }
}
const audit={triangles:ind.length/3,vertices:uv.length/2,uvRasterSize:size,coveredPixels:covered,overlappingInteriorSamples:overlap,editableOverlap,lipOverlap,degenerateUVTriangles:degenerate,scope:'1024 pixel-centre raster audit; not an analytic proof; editing restricted to audited masks, never entire UV map',embeddedImages:gltf.images.every(i=>Number.isInteger(i.bufferView)),externalResources:gltf.buffers.some(b=>b.uri)||gltf.images.some(i=>i.uri),validatorErrors:report.issues.numErrors};
await fs.writeFile('docs/evidence/asset-audit.json',JSON.stringify(audit,null,2));console.log(JSON.stringify(audit,null,2));
if(report.issues.numErrors||editableOverlap||lipOverlap||audit.externalResources)process.exitCode=1;
