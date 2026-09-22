import fs from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {PNG} from 'pngjs';
const src='assets-src/LeePerrySmith-r186',out='assets';
await fs.mkdir(out,{recursive:true});
const input=await fs.readFile(`${src}/LeePerrySmith.glb`),jpg=await fs.readFile(`${src}/Map-COL.jpg`);
const jsonLength=input.readUInt32LE(12),gltf=JSON.parse(input.subarray(20,20+jsonLength));
const oldBinStart=20+jsonLength+8,oldBin=input.subarray(oldBinStart,oldBinStart+gltf.buffers[0].byteLength);
const pad=(b,fill=0)=>Buffer.concat([b,Buffer.alloc((4-b.length%4)%4,fill)]);
const binary=Buffer.concat([pad(oldBin),pad(jpg)]);
// webgl_decals assigns a TextureLoader map (flipY=true), while GLTFLoader maps use flipY=false.
// Convert the source UV convention exactly once when embedding that external JPEG.
const uvAccessor=gltf.accessors[gltf.meshes[0].primitives[0].attributes.TEXCOORD_0];
const uvView=gltf.bufferViews[uvAccessor.bufferView];
for(let i=0;i<uvAccessor.count;i++){const offset=(uvView.byteOffset||0)+(uvAccessor.byteOffset||0)+i*8+4;binary.writeFloatLE(1-binary.readFloatLE(offset),offset);}
const oldMin=uvAccessor.min[1];uvAccessor.min[1]=1-uvAccessor.max[1];uvAccessor.max[1]=1-oldMin;
gltf.bufferViews.push({buffer:0,byteOffset:pad(oldBin).length,byteLength:jpg.length});
gltf.images=[{bufferView:gltf.bufferViews.length-1,mimeType:'image/jpeg',name:'Original Map-COL'}];
gltf.samplers=[{magFilter:9729,minFilter:9729,wrapS:33071,wrapT:33071}];
gltf.textures=[{source:0,sampler:0}];
gltf.materials=[{name:'SELF baked appearance',pbrMetallicRoughness:{baseColorFactor:[1,1,1,1],baseColorTexture:{index:0},metallicFactor:0,roughnessFactor:1},extensions:{KHR_materials_unlit:{}}}];
gltf.extensionsUsed=['KHR_materials_unlit'];
gltf.nodes=[{name:'LeePerrySmith',mesh:0}];gltf.scenes=[{nodes:[0]}];gltf.scene=0;
gltf.asset.generator='SELF lossless GLB packaging (original geometry / original JPEG)';gltf.buffers[0].byteLength=binary.length;
const j=pad(Buffer.from(JSON.stringify(gltf)),32),header=Buffer.alloc(12),jh=Buffer.alloc(8),bh=Buffer.alloc(8);
header.writeUInt32LE(0x46546c67);header.writeUInt32LE(2,4);header.writeUInt32LE(12+8+j.length+8+binary.length,8);
jh.writeUInt32LE(j.length);jh.writeUInt32LE(0x4e4f534a,4);bh.writeUInt32LE(binary.length);bh.writeUInt32LE(0x004e4942,4);
const packed=Buffer.concat([header,jh,j,bh,binary]);await fs.writeFile(`${out}/sample-head.glb`,packed);
const regions=JSON.parse(await fs.readFile('assets-src/regions.json','utf8'));
function inside(x,y,poly){let hit=false;for(let i=0,j=poly.length-1;i<poly.length;j=i++){const a=poly[i],b=poly[j];if((a[1]>y)!==(b[1]>y)&&x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0])hit=!hit;}return hit;}
for(const name of ['lip','editable','protectionTest']) {
  const pixels=new Uint8Array(1024*1024),png=new PNG({width:1024,height:1024});
  for(let y=0;y<1024;y++)for(let x=0;x<1024;x++) {
    const v=inside(x+.5,y+.5,regions[name]) && !(name==='lip'&&inside(x+.5,y+.5,regions.lipExclusion))?255:0;
    const i=y*1024+x;pixels[i]=v;png.data.set([v,v,v,255],i*4);
  }
  await fs.writeFile(`${out}/${name}.mask`,pixels);await fs.writeFile(`${out}/${name}.png`,PNG.sync.write(png));
}
const manifest={schemaVersion:1,assetId:'sample-lee',version:'lee-r186-self2',sourceKind:'MESH',label:'示例面容 · Lee Perry-Smith',baselineKind:'bakedAppearance',attribution:'Infinite, 3D Head Scan by Lee Perry-Smith; based on www.triplegangers.com',license:'CC-BY-3.0',orientation:{front:'+Z',up:'+Y',scale:1,unit:'original scan units (not calibrated metres)'},mesh:0,primitive:0,uvSet:0,uvVersion:'r186-v-flipped-on-pack-v1',textureVersion:regions.textureVersion,regionRefs:['lip','editable','protectionTest'],supportedOperations:['localTint','lipTint'],renderPipelineVersion:'self-linear-tint-v1',maskWidth:1024,maskHeight:1024,sha256:createHash('sha256').update(packed).digest('hex'),limitations:['Closed-mouth sample only','Conservative manually authored regions','Not a personal reconstruction','UV overlap exists outside registered editable region; prohibit whole-surface editing']};
await fs.writeFile(`${out}/manifest.json`,JSON.stringify(manifest,null,2));
await fs.copyFile(`${src}/LeePerrySmith_License.txt`,`${out}/LICENSE-HEAD.txt`);
console.log(`Packaged ${packed.length} bytes with original JPEG and 17,684 triangles; generated actual masks.`);
