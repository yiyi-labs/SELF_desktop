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
