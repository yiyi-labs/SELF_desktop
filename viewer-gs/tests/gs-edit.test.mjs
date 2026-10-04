import test from 'node:test';
import assert from 'node:assert/strict';
import {selectVisibleSplats, normalizeLasso, selectionSlot, shouldRecordLassoPoint, makeOriginalColors, applyDigitalTint, applyDigitalLayers, DIGITAL_PRESETS} from '../gs-edit.js';

function scene() {
  const points=[];
  for(let y=-8;y<=8;y++)for(let x=-8;x<=8;x++)points.push([x*.02,y*.02,0]);
  const faceCount=points.length;
  for(let y=-8;y<=8;y++)for(let x=-8;x<=8;x++)points.push([x*.02,y*.02,-.1]);
  const count=points.length;
  const props={x:Float32Array.from(points,p=>p[0]),y:Float32Array.from(points,p=>p[1]),
    z:Float32Array.from(points,p=>p[2]),opacity:new Float32Array(count).fill(4),
    f_dc_0:new Float32Array(count).fill(.1),f_dc_1:new Float32Array(count).fill(.1),f_dc_2:new Float32Array(count).fill(.1)};
  return {faceCount,data:{numSplats:count,activated:false,getProp:name=>props[name]},props};
}

test('lasso selects visible face splats, not occluded points at the same pixels',()=>{
  const {faceCount,data}=scene();
  const result=selectVisibleSplats({data,polygon:[{x:100,y:100},{x:300,y:100},{x:300,y:300},{x:100,y:300},{x:100,y:100}],
    target:[0,0,0],cameraPosition:[0,0,1],project:(x,y)=>({x:200+x*700,y:200-y*700}),width:400,height:400});
  assert.ok(result.selected>80);
  assert.ok(result.mask.slice(0,faceCount).some(v=>v>0));
  assert.ok(result.mask.slice(faceCount).every(v=>v===0));
  assert.ok(result.mask[Math.floor(faceCount/2)]>result.mask[0]);
});

test('a combined portrait and room PLY keeps every room splat outside the editable range',()=>{
  const {faceCount,data}=scene();
  const selection=selectVisibleSplats({data,editableCount:faceCount,
    polygon:[{x:140,y:140},{x:260,y:140},{x:260,y:260},{x:140,y:260},{x:140,y:140}],
    target:[0,0,0],cameraPosition:[0,0,1],project:(x,y)=>({x:200+x*700,y:200-y*700}),
    width:400,height:400});
  assert.ok(selection.selected>28);
  assert.equal(selection.mask.length,data.numSplats);
  assert.ok(selection.mask.slice(faceCount).every(value=>value===0));
});

test('digital edit changes only selected Gaussian DC; reset restores original, including unmodified SH',()=>{
  const {data,props}=scene();
  const original=makeOriginalColors(data),mask=new Uint8Array(data.numSplats);
  mask[10]=255;mask[11]=128;
  const sh=new Float32Array(data.numSplats).fill(.77);props.f_rest_0=sh;
  let uploads=0;
  const resource={gsplatData:data,updateColorData:()=>uploads++};
  assert.deepEqual(DIGITAL_PRESETS.rose,[.66,.12,.30]);
  assert.deepEqual(DIGITAL_PRESETS.terracotta,[.65,.25,.18]);
  applyDigitalTint(resource,original,mask,DIGITAL_PRESETS.rose,.32);
  assert.notEqual(props.f_dc_0[10],original[0][10]);
  const greenBefore=.5+original[1][10]*.28209479177387814;
  const greenAfter=.5+props.f_dc_1[10]*.28209479177387814;
  assert.ok(greenBefore-greenAfter>.07,'medium rose must be perceptible at a selected splat');
  assert.ok(Math.abs(props.f_dc_0[11]-original[0][11])<Math.abs(props.f_dc_0[10]-original[0][10]));
  assert.equal(props.f_dc_0[12],original[0][12]);
  assert.equal(props.f_rest_0,sh);
  applyDigitalTint(resource,original,new Uint8Array(data.numSplats),[.5,.5,.5],0);
  assert.deepEqual(props.f_dc_0,original[0]);
  assert.equal(uploads,2);
});

test('diagonal touch drag becomes an oval while a drawn contour stays intact',()=>{
  const drag=normalizeLasso([{x:20,y:20},{x:100,y:100}]);
  assert.equal(drag.length,48);
  assert.ok(drag.some(p=>p.x>90&&p.y>40&&p.y<80));
  const drawn=[{x:20,y:20},{x:100,y:20},{x:100,y:100},{x:20,y:100}];
  assert.equal(normalizeLasso(drawn),drawn);
});

test('a repeat stroke replaces the last unsent region; adding another is explicit',()=>{
  assert.equal(selectionSlot(0,false),0);
  assert.equal(selectionSlot(1,false),0);
  assert.equal(selectionSlot(2,false),1);
  assert.equal(selectionSlot(2,true),2);
  assert.equal(selectionSlot(4,false),3);
  assert.throws(()=>selectionSlot(4,true),/最多圈选四处/);
});

test('slow pen movement accumulates against the last recorded point',()=>{
  const recorded=[{x:0,y:0}];
  for(let x=1;x<=60;x++){
    const point={x,y:0};
    if(shouldRecordLassoPoint(recorded[recorded.length-1],point))recorded.push(point);
  }
  assert.ok(recorded.length>12);
  assert.ok(recorded.every((point,index)=>index===0||point.x-recorded[index-1].x>3));
});

test('a grouped edit can remove one layer or the whole group without residual tint',()=>{
  const {data,props}=scene(),original=makeOriginalColors(data);
  let uploads=0;
  const resource={gsplatData:data,updateColorData:()=>uploads++};
  const first=new Uint8Array(data.numSplats),second=new Uint8Array(data.numSplats);
  first[10]=255;second[11]=255;
  const layers=[{mask:first,preset:'rose',strength:.32},{mask:second,preset:'terracotta',strength:.18}];
  applyDigitalLayers(resource,original,layers);
  assert.notEqual(props.f_dc_1[10],original[1][10]);
  assert.notEqual(props.f_dc_0[11],original[0][11]);
  applyDigitalLayers(resource,original,[layers[1]]);
  assert.equal(props.f_dc_1[10],original[1][10]);
  assert.notEqual(props.f_dc_0[11],original[0][11]);
  applyDigitalLayers(resource,original,[]);
  assert.deepEqual(props.f_dc_0,original[0]);
  assert.deepEqual(props.f_dc_1,original[1]);
  assert.equal(uploads,3);
});

// ---- Morton identity mapping (loaded order vs file order) ----
import {mortonOrderOf, editableSetFromOrder} from '../gs-edit.js';

test('mortonOrderOf is a permutation sorted by code with stable bucket order',()=>{
  // Deterministic pseudo-scatter across a grid.
  const pts=[];for(let z=0;z<4;z++)for(let y=0;y<4;y++)for(let x=0;x<4;x++)pts.push([x*1.5-3,y*1.5-3,z*1.5-3]);
  // shuffle deterministically
  for(let i=pts.length-1;i>0;i--){const j=(i*17+5)%(i+1);[pts[i],pts[j]]=[pts[j],pts[i]];}
  const props={x:Float32Array.from(pts,p=>p[0]),y:Float32Array.from(pts,p=>p[1]),z:Float32Array.from(pts,p=>p[2])};
  const data={numSplats:pts.length,getProp:n=>props[n]};
  const order=mortonOrderOf(data);
  assert.equal(order.length,pts.length);
  assert.deepEqual([...order].sort((a,b)=>a-b),[...Array(pts.length).keys()]); // permutation
  // codes must be non-decreasing along the order
  const part=w=>{w&=1023;w=(w^w<<16)&4278190335;w=(w^w<<8)&50393103;w=(w^w<<4)&51130563;w=(w^w<<2)&153391689;return w;};
  const code=(x,y,z)=>(part(z)<<2)+(part(y)<<1)+part(x);
  const q=(a)=>{const lo=Math.min(...a),hi=Math.max(...a);const s=lo===hi?0:1024/(hi-lo);return i=>Math.min(1023,Math.floor((a[i]-lo)*s));};
  const qx=q(props.x),qy=q(props.y),qz=q(props.z);
  const codes=[...order].map(i=>code(qx(i),qy(i),qz(i)));
  for(let k=1;k<codes.length;k++)assert.ok(codes[k]>=codes[k-1]);
});

test('editableLoadedIndices recovers the editable set after a simulated engine reorder',()=>{
  const {faceCount,data}=scene(); // first faceCount rows = editable in FILE order
  const order=mortonOrderOf(data);
  const props={};for(const name of ['x','y','z','opacity','f_dc_0','f_dc_1','f_dc_2'])props[name]=data.getProp(name);
  // engine reorder semantics: storageLoaded[l] = storageFile[order[l]]
  const loaded={};for(const name in props){const src=props[name];const arr=new src.constructor(src.length);for(let l=0;l<order.length;l++)arr[l]=src[order[l]];loaded[name]=arr;}
  const loadedData={numSplats:data.numSplats,activated:false,getProp:n=>loaded[n]};
  const set=editableSetFromOrder(order,faceCount); // App 方案：文件序置换→身份集
  assert.equal(set.length,faceCount);
  // every recovered loaded index maps back to a file row inside the prefix
  const back=new Set([...set].map(l=>order[l]));
  for(let f=0;f<faceCount;f++)assert.ok(back.has(f),`file row ${f} missing`);
  // and a selection through the identity set now finds the face, while the
  // legacy prefix scan of the same loaded data must NOT be equivalent.
  const pick={polygon:[{x:150,y:150},{x:250,y:150},{x:250,y:250},{x:150,y:250},{x:150,y:150}],
    target:[0,0,0],cameraPosition:[0,0,1],project:(x,y)=>({x:200+x*700,y:200-y*700}),width:400,height:400};
  const good=selectVisibleSplats({data:loadedData,editableIndices:set,...pick});
  assert.ok(good.selected>=28&&good.selected<faceCount*.6);
  const goodIds=new Set();for(let i=0;i<good.mask.length;i++)if(good.mask[i]>0)goodIds.add(order[i]);
  assert.ok([...goodIds].every(f=>f<faceCount));
  // legacy prefix on reordered data touches wrong-domain rows
  let legacyWrong=false;
  try{
    const legacy=selectVisibleSplats({data:loadedData,editableCount:faceCount,...pick});
    for(let i=0;i<legacy.mask.length;i++)if(legacy.mask[i]>0&&order[i]>=faceCount)legacyWrong=true;
  }catch(e){legacyWrong=true;/*rejected or empty is also fine*/}
  assert.ok(legacyWrong,'legacy prefix must not silently select the correct domain');
});
