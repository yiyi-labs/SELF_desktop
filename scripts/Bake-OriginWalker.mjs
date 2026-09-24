/** Bake a CC0 skinned surface into compact, time-corresponding point frames.
 * Usage: node scripts/Bake-OriginWalker.mjs artifacts/sources/quaternius-human.glb
 * Runtime asset contains only surface positions: no portrait, bones or textures.
 */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

globalThis.self = globalThis;
globalThis.createImageBitmap = async () => ({ width: 1, height: 1, close() {} });

const source = process.argv[2];
if (!source) throw Error('Provide a local, license-checked human.glb source path');
const input = fs.readFileSync(source);
const digest = crypto.createHash('sha256').update(input).digest('hex');
const gltf = await new Promise((resolve, reject) => new GLTFLoader().parse(
  input.buffer.slice(input.byteOffset, input.byteOffset + input.byteLength), '', resolve, reject));
const mesh = gltf.scene.getObjectByName('Human_Mesh');
const walk = gltf.animations.find(clip => clip.name.endsWith('|Walk'));
if (!mesh?.isSkinnedMesh || !walk || Math.abs(walk.duration - 1) > .05) {
  throw Error('The pinned source mesh or walking clip changed');
}
const positions = mesh.geometry.attributes.position;
const index = mesh.geometry.index;
const triangles = [];
let areaSum = 0;
const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3();
for (let k = 0; k < (index?.count ?? positions.count); k += 3) {
  const ia = index ? index.getX(k) : k;
  const ib = index ? index.getX(k + 1) : k + 1;
  const ic = index ? index.getX(k + 2) : k + 2;
  a.fromBufferAttribute(positions, ia);
  b.fromBufferAttribute(positions, ib);
  c.fromBufferAttribute(positions, ic);
  const area = b.sub(a).cross(c.sub(a)).length() * .5;
  if (area > 1e-10) { areaSum += area; triangles.push({ ia, ib, ic, end: areaSum }); }
}
let random = 49721;
const unit = () => { random = (Math.imul(random, 1664525) + 1013904223) >>> 0; return random / 4294967296; };
const pointCount = 4200, frameCount = 20;
const samples = [];
for (let i = 0; i < pointCount; i++) {
  const target = unit() * areaSum;
  let low = 0, high = triangles.length - 1;
  while (low < high) {
    const mid = (low + high) >> 1;
    if (triangles[mid].end < target) low = mid + 1;
    else high = mid;
  }
  const tri = triangles[low], root = Math.sqrt(unit()), split = unit();
  samples.push({ ...tri, wa: 1 - root, wb: root * (1 - split), wc: root * split });
}

const working = gltf.animations.find(clip => clip.name.endsWith('|Working'));
if (!working) throw Error('The indoor gesture clip is missing');
const mixer = new THREE.AnimationMixer(gltf.scene);
const makeBuffer = () => {
  const buffer=Buffer.alloc(16 + pointCount * frameCount * 6);
  buffer.write('SHUM', 0, 'ascii');
  buffer.writeUInt16LE(1, 4);
  buffer.writeUInt16LE(frameCount, 6);
  buffer.writeUInt16LE(pointCount, 8);
  buffer.writeUInt16LE(6, 10);
  return buffer;
};
const vertices = new Float32Array(positions.count * 3);
const vertex = new THREE.Vector3();
const at = (id, axis) => vertices[id * 3 + axis];
const quantize = value => Math.max(-32767, Math.min(32767, Math.round(value * 32767)));
const writePoint = (buffer, frame, i, x, y, z) => {
  const offset=16+(frame*pointCount+i)*6;
  buffer.writeInt16LE(quantize(x),offset);
  buffer.writeInt16LE(quantize(y),offset+2);
  buffer.writeInt16LE(quantize(z),offset+4);
};
const sampleSurface = sample => {
  const worldX=at(sample.ia,0)*sample.wa+at(sample.ib,0)*sample.wb+at(sample.ic,0)*sample.wc;
  const worldY=at(sample.ia,1)*sample.wa+at(sample.ib,1)*sample.wb+at(sample.ic,1)*sample.wc;
  const worldZ=at(sample.ia,2)*sample.wa+at(sample.ib,2)*sample.wb+at(sample.ic,2)*sample.wc;
  return [(worldZ*.96+worldX*.28)/5.5,(2.72-worldY)/5.5,
    (worldX*.96-worldZ*.28)/5.5];
};
const room=[];
for(let j=0;j<pointCount-2300;j++){
  let x=0,y=0,z=0;
  if(j<700){
    const beam=Math.floor(j/100),u=unit(),thickness=(unit()-.5)*.018;
    z=-.18+(unit()-.5)*.026;
    if(beam===0||beam===1){x=(beam===0?-.05:.47)+thickness;y=-.20+u*.40;}
    else if(beam===2){x=.21+.26*Math.cos(u*Math.PI)+thickness;y=-.20-.23*Math.sin(u*Math.PI);}
    else if(beam===3){x=-.08+u*.58;y=.20+thickness;z=-.13;}
    else if(beam===4){x=.21+thickness;y=-.42+u*.62;}
    else if(beam===5){x=-.05+u*.52;y=-.055+thickness;}
    else {y=-.19+u*.43;x=(j%2===0?-.105:.525)+Math.sin(u*21)*.014+thickness;z=-.10;}
  } else if(j<1600){
    const n=j-700;
    if(n<320){
      const t=unit(),a=unit()*Math.PI*2,r=.047+t*.016;
      x=.29+Math.cos(a)*r;y=.39-t*.13;z=.13+Math.sin(a)*r;
    }else if(n<520){
      const branch=Math.floor(unit()*7),t=unit();
      const angle=branch*2.399;
      x=.29+Math.cos(angle)*.13*t*t;y=.26-.26*t;
      z=.13+Math.sin(angle)*.09*t*t;
    }else{
      const branch=Math.floor(unit()*9),angle=branch*2.399;
      const centerX=.29+Math.cos(angle)*(.08+branch%3*.025);
      const centerY=.07-(branch%4)*.038;
      const along=unit()*2-1,width=Math.sqrt(1-along*along)*(unit()*2-1)*.028;
      const leafAngle=angle+(branch%2===0?.35:-.35);
      x=centerX+along*.095*Math.cos(leafAngle)-width*Math.sin(leafAngle);
      y=centerY+along*.095*Math.sin(leafAngle)+width*Math.cos(leafAngle);
      z=.13+Math.sin(angle)*.08+(unit()-.5)*.028;
    }
  } else {
    const u=unit(),v=unit();
    x=-.58+u*1.2;y=.40+v*.13;z=-.20+v*.5;
  }
  room.push([x,y,z]);
}

const outputs=[];
for(const [scene,clip] of [['walker',walk],['window',working]]){
  mixer.stopAllAction();
  mixer.clipAction(clip).reset().play();
  const out=makeBuffer();
  for(let frame=0;frame<frameCount;frame++){
    mixer.setTime(frame*clip.duration/frameCount);
    gltf.scene.updateMatrixWorld(true);
    mesh.skeleton.update();
    for(let i=0;i<positions.count;i++){
      vertex.fromBufferAttribute(positions,i);
      mesh.applyBoneTransform(i,vertex);
      vertex.applyMatrix4(mesh.matrixWorld);
      vertices[i*3]=vertex.x;vertices[i*3+1]=vertex.y;vertices[i*3+2]=vertex.z;
    }
    const humanCount=scene==='walker'?pointCount:2300;
    for(let i=0;i<humanCount;i++){
      const [x,y,z]=sampleSurface(samples[i]);
      writePoint(out,frame,i,scene==='window'?x-.24:x,scene==='window'?y+.02:y,z);
    }
    if(scene==='window')for(let i=2300;i<pointCount;i++){
      const [x,y,z]=room[i-2300];writePoint(out,frame,i,x,y,z);
    }
  }
  const destination=path.join('entry','src','main','resources','rawfile',`origin-${scene}.bin`);
  fs.writeFileSync(destination,out);
  outputs.push({scene,clip:clip.name,path:destination,bytes:out.length,
    sha256:crypto.createHash('sha256').update(out).digest('hex')});
}
console.log(JSON.stringify({source,sourceSha256:digest,meshVertices:positions.count,
  triangles:triangles.length,pointCount,frameCount,outputs}));
