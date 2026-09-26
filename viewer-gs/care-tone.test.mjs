import test from 'node:test';
import assert from 'node:assert/strict';
import {applyCareScenario,selectVisibleSplats} from './gs-edit.js';
import {upperLeftLuma,createToneTracker} from './tone.js';

test('tone switches only after repeated readings outside hysteresis band',()=>{
  const tracker=createToneTracker();
  assert.equal(tracker(.81),null);
  assert.equal(tracker(.82),true);
  assert.equal(tracker(.59),null);
  assert.equal(tracker(.35),null);
  assert.equal(tracker(.34),false);
  assert.equal(tracker(.59),null);
});

test('tone samples background patch instead of the central portrait',()=>{
  const width=12,height=8,pixels=new Uint8ClampedArray(width*height*4);
  for(let y=0;y<height;y++)for(let x=0;x<width;x++){
    const i=(y*width+x)*4,shade=x<6&&y<4?242:15;
    pixels.set([shade,shade,shade,255],i);
  }
  assert.ok(upperLeftLuma(pixels,width,height)>.9);
});

test('care scenario only changes masked DC colour and is reversible',()=>{
  const props={f_dc_0:new Float32Array([.40,.10]),f_dc_1:new Float32Array([-.20,.10]),
    f_dc_2:new Float32Array([-.18,.10])};
  const data={numSplats:2,getProp:name=>props[name]};
  const resource={gsplatData:data,updateColorData:()=>{}};
  const original=['f_dc_0','f_dc_1','f_dc_2'].map(key=>Float32Array.from(props[key]));
  applyCareScenario(resource,original,[],[new Uint8Array([255,0])],1);
  assert.ok(props.f_dc_0[0]<original[0][0]);
  assert.equal(props.f_dc_0[1],original[0][1]);
  applyCareScenario(resource,original,[],[new Uint8Array([255,0])],0);
  for(let c=0;c<3;c++)assert.deepEqual([...props[`f_dc_${c}`]],[...original[c]]);
});

test('a small face-area lasso can select a useful 3D patch',()=>{
  const xs=[],ys=[],zs=[],opacity=[];
  for(let y=0;y<10;y++)for(let x=0;x<10;x++){
    xs.push((x-4.5)*.02);ys.push((y-4.5)*.02);zs.push(0);opacity.push(1);
  }
  const props={x:Float32Array.from(xs),y:Float32Array.from(ys),z:Float32Array.from(zs),
    opacity:Float32Array.from(opacity)};
  const data={numSplats:100,activated:true,getProp:name=>props[name]};
  const square=[{x:70,y:70},{x:130,y:70},{x:130,y:130},{x:70,y:130},{x:70,y:70}];
  const result=selectVisibleSplats({data,polygon:square,target:[0,0,0],cameraPosition:[0,0,1],
    project:(x,y)=>({x:100+x*500,y:100+y*500}),width:200,height:200});
  assert.ok(result.selected>=28&&result.selected<60);
});
