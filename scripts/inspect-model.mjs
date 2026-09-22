import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';
import validator from 'gltf-validator';

/** Offline structural gate, NOT a proof of face accuracy, UV uniqueness or native rendering. */
export async function inspectModel(bytes){
 const errors=[],check=(ok,message)=>{if(!ok)errors.push(message);};
 const result={schemaVersion:1,profile:'SELF static textured mesh v1',bytes:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex'),structurallyCompatible:false,errors,
  unverified:['native rendering / material appearance','analytic editable UV overlap and seam audit','capture coverage / reconstruction fidelity','occlusion-correct lasso / protected pixel equality / PNG on native device']};
 try{
  check(bytes.length<=33554432,'Model exceeds current 32 MiB asset budget');
  if(bytes.length<28||bytes.readUInt32LE(0)!==0x46546c67||bytes.readUInt32LE(4)!==2||bytes.readUInt32LE(8)!==bytes.length)throw Error('Expected a complete GLB 2.0 container; renaming PLY/OBJ does not convert it');
  const report=await validator.validateBytes(new Uint8Array(bytes),{maxIssues:30});
  result.validator={errors:report.issues.numErrors,warnings:report.issues.numWarnings};
  check(report.issues.numErrors===0,'Khronos glTF validation failed');
  if(bytes.readUInt32LE(16)!==0x4e4f534a)throw Error('First GLB chunk must be JSON');
  const g=JSON.parse(bytes.subarray(20,20+bytes.readUInt32LE(12)).toString('utf8'));
  check(g.asset?.version==='2.0','Expected glTF 2.0 asset');
  const extensions=new Set([...(g.extensionsUsed||[]),...(g.extensionsRequired||[])]);
  check([...extensions].every(e=>e==='KHR_materials_unlit'),'Profile only accepts KHR_materials_unlit; compressed or Gaussian extensions need a separately verified decoder');
  check((g.meshes||[]).length===1&&(g.meshes[0].primitives||[]).length===1,'Expected one mesh with one primitive');
  check(!(g.skins||[]).length&&!(g.animations||[]).length,'Skinning and animation require a separate editing/selection contract');
  const meshNodes=(g.nodes||[]).filter(n=>n.mesh!==undefined);
  check(meshNodes.length===1&&meshNodes[0].mesh===0,'Expected a single mesh instance');
  const identity=(value,expected)=>!value||(value.length===expected.length&&value.every((v,i)=>v===expected[i]));
  check((g.nodes||[]).every(n=>identity(n.matrix,[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1])&&identity(n.translation,[0,0,0])&&identity(n.rotation,[0,0,0,1])&&identity(n.scale,[1,1,1])),'Bake node transforms before importing into the current editor');
  check(g.buffers?.length===1&&g.buffers.every(b=>!b.uri),'All model data must be embedded in the GLB');
  check(g.images?.length===1&&g.images.every(i=>Number.isInteger(i.bufferView)&&!i.uri&&['image/jpeg','image/png'].includes(i.mimeType)),'Expected one embedded JPEG/PNG texture');
  const p=g.meshes?.[0]?.primitives?.[0];
  if(!p)throw Error('No triangle mesh; point clouds and Gaussian models are not UV meshes');
  check((p.mode??4)===4,'Only TRIANGLES mode is accepted');
  check(!(p.targets||[]).length,'Morph targets are not yet accepted');
  const attributes=p.attributes||{};
  for(const [name,type]of [['POSITION','VEC3'],['NORMAL','VEC3'],['TEXCOORD_0','VEC2']]){
   const a=g.accessors?.[attributes[name]];
   check(a?.type===type&&a.componentType===5126&&!a.sparse,`Missing or unsupported ${name}: expected dense float ${type}`);
  }
  const positions=g.accessors?.[attributes.POSITION],uv=g.accessors?.[attributes.TEXCOORD_0],indices=g.accessors?.[p.indices];
  check(indices?.type==='SCALAR'&&[5121,5123,5125].includes(indices.componentType)&&indices.count%3===0,'Expected indexed triangles');
  check(positions?.count>0&&positions.count===uv?.count,'UV and position counts must match');
  result.vertices=positions?.count;result.triangles=indices?.count/3;
  const material=g.materials?.[p.material],color=material?.pbrMetallicRoughness;
  check(material?.extensions?.KHR_materials_unlit!==undefined,'Current SELF appearance contract requires unlit baked color');
  check(color?.baseColorTexture!==undefined&&(color.baseColorTexture.texCoord??0)===0,'Expected base color on TEXCOORD_0');
  check(identity(color?.baseColorFactor,[1,1,1,1]),'Non-neutral baseColorFactor requires explicit appearance normalization');
  check((material?.alphaMode||'OPAQUE')==='OPAQUE','Transparent face material is outside this profile');
 }catch(e){errors.push(String(e));}
 result.structurallyCompatible=errors.length===0;return result;
}
if(process.argv[1]&&import.meta.url===pathToFileURL(path.resolve(process.argv[1])).href){
 const input=process.argv[2];if(!input)throw Error('Usage: node scripts/inspect-model.mjs model.glb [report.json]');
 const report=await inspectModel(await fs.readFile(input));
 const output=JSON.stringify(report,null,2);if(process.argv[3])await fs.writeFile(process.argv[3],output);
 console.log(output);if(!report.structurallyCompatible)process.exitCode=1;
}
