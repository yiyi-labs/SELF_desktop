import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {add,rotate,twoFingerPanDelta,composeOrbitCamera} from '../portrait-camera-math.js';

const source=fs.readFileSync(new URL('../main.js',import.meta.url),'utf8');
function section(start,end){
  const from=source.indexOf(start),to=source.indexOf(end,from);
  assert.ok(from>=0&&to>from,`Missing production section: ${start}`);
  return source.slice(from,to);
}
function harness({pitch=0,recordedFov=false}={}){
  const events={},positions=[];
  const rect={left:37,top:61,width:720,height:1280};
  const h={preview:false,touching:false,mode:'move',yaw:0,pitch,zoom:1,
    targetYaw:0,targetPitch:pitch,targetZoom:1,firstCamera:true,lastX:0,lastY:0,
    original:[0,0,3],up:[0,1,0],target:[0,0,0],pivotGoal:[0,0,0],radius:3,
    yawBounds:[-Math.PI,Math.PI],pitchBounds:[-85*Math.PI/180,85*Math.PI/180],
    movePointers:new Map(),twoFinger:null,polygon:[],userTouched:false,portrait2:false,
    setMotionResolution:()=>{},interaction:()=>{},drawOutline:()=>{},
    rotate,add,twoFingerPanDelta,composeOrbitCamera,
    normal:v=>{const n=Math.hypot(...v);return v.map(x=>x/n);},clampZoom:v=>Math.max(.04,Math.min(4,v)),
    performance:{now:()=>1000},recordedFov,aimPoint:null,cameraRevision:0,selections:[],
    app:{renderNextFrame:false},camera:{camera:{fov:60},setPosition:(...p)=>positions.push(p),lookAt:()=>{}},
    canvas:{getBoundingClientRect:()=>rect,setPointerCapture:()=>{},addEventListener:(name,fn)=>{events[name]=fn;}}};
  vm.createContext(h);
  vm.runInContext(section('      const update=','      app.on(\'update\'')+'globalThis.tick=update;',h);
  vm.runInContext(section('      const endTwoFinger=',"      canvas.addEventListener('wheel'"),h);
  const event=(type,id,x,y)=>events[type]({pointerId:id,clientX:x+rect.left,clientY:y+rect.top});
  h.tick(1/60);
  return {h,positions,event};
}
const near=(a,b)=>assert.ok(Math.abs(a-b)<1e-10,`${a} != ${b}`);
function pair(f){f.event('pointerdown',1,260,600);f.event('pointerdown',2,460,600);}

test('single-finger drag uses the source sensitivity and stops at the rendered pose on release',()=>{
  const f=harness();f.event('pointerdown',1,100,100);f.event('pointermove',1,120,110);
  near(f.h.targetYaw,.16);near(f.h.targetPitch,.08);f.h.tick(1/60);
  const pose=[f.h.yaw,f.h.pitch,f.h.zoom,...f.h.target];
  f.event('pointerup',1,120,110);for(let i=0;i<10;i++)f.h.tick(1/60);
  assert.deepEqual([f.h.yaw,f.h.pitch,f.h.zoom,...f.h.target],pose);
});
for(const pitch of [0,Math.PI/3,-Math.PI/3])test(`two-finger pan follows the fingers without changing zoom or orbit at pitch ${pitch}`,()=>{
  const f=harness({pitch});pair(f);
  const before=f.positions.at(-1);f.event('pointermove',1,300,630);f.event('pointermove',2,500,630);
  assert.deepEqual(f.h.pivotGoal,[0,0,0]);f.h.tick(1/60);
  near(f.h.targetZoom,1);near(f.h.targetYaw,0);near(f.h.targetPitch,pitch);
  const logical=composeOrbitCamera([0,0,0],[0,0,3],[0,1,0],0,pitch,3);
  assert.ok(f.h.pivotGoal.reduce((s,v,i)=>s+v*logical.basis.right[i],0)<0);
  const after=f.positions.at(-1);after.forEach((v,i)=>near(v-before[i],f.h.target[i]));
});
test('centred pinch changes distance and leaves the pivot fixed',()=>{
  const f=harness();pair(f);f.event('pointermove',1,160,600);f.event('pointermove',2,560,600);f.h.tick(1/60);
  near(f.h.targetZoom,.5);f.h.pivotGoal.forEach(v=>near(v,0));
});
test('combined pan and pinch produces the same result regardless of finger event order',()=>{
  const run=reverse=>{const f=harness();pair(f);const moves=[[1,190,650],[2,590,650]];
    for(const [id,x,y] of reverse?moves.reverse():moves)f.event('pointermove',id,x,y);
    f.h.tick(1/60);return [f.h.targetZoom,...f.h.pivotGoal,...f.h.target];};
  assert.deepEqual(run(false),run(true));near(run(false)[0],.5);assert.ok(Math.abs(run(false)[2])>0);
});
test('a third finger does not alter the tracked pair, zoom, or pan',()=>{
  const f=harness();pair(f);f.event('pointerdown',3,600,100);f.event('pointermove',3,700,200);f.h.tick(1/60);
  near(f.h.targetZoom,1);assert.deepEqual(f.h.pivotGoal,[0,0,0]);assert.deepEqual(Array.from(f.h.twoFinger.ids),[1,2]);
  f.event('pointercancel',3,700,200);assert.ok(f.h.twoFinger);
});
for(const end of ['pointerup','pointercancel'])test(`${end} rebases the surviving finger and freezes the final pan and zoom`,()=>{
  const f=harness();pair(f);f.event('pointermove',1,220,640);f.event('pointermove',2,620,640);f.h.tick(1/60);
  f.event(end,1,220,640);f.event('pointermove',2,625,642);
  near(f.h.targetYaw,.04);near(f.h.targetPitch,.016);f.h.tick(1/60);
  f.event(end,2,625,642);const pose=[f.h.yaw,f.h.pitch,f.h.zoom,...f.h.target];
  for(let i=0;i<30;i++)f.h.tick(1/60);
  assert.deepEqual([f.h.yaw,f.h.pitch,f.h.zoom,...f.h.target],pose);
  assert.equal(f.h.touching,false);assert.equal(f.h.twoFinger,null);
});
test('recorded-FOV framing stays offset by the same amount while the scene pans',()=>{
  const f=harness({recordedFov:true});pair(f);f.event('pointermove',1,300,620);f.event('pointermove',2,500,620);f.h.tick(1/60);
  near(f.h.aimPoint[0],f.h.target[0]);near(f.h.aimPoint[1],f.h.target[1]-3*f.h.zoom*.075);near(f.h.aimPoint[2],f.h.target[2]);
});
test('screen-space selection contours are reprojected after pan and zoom',()=>{
  let projected=0;
  const h={target:[0,0,0],zoom:1,yaw:0,pitch:0,radius:3,polygon:[],sparks:[],devicePixelRatio:1,
    performance:{now:()=>0},canvas:{getBoundingClientRect:()=>({width:720,height:1280})},
    outline:{width:720,height:1280,getContext:()=>({clearRect:()=>{},save:()=>{},scale:()=>{},restore:()=>{}})},
    trace:()=>{},projectedContour:()=>{projected++;return [];},
    selections:[{target:[0,0,0],zoom:1,yaw:0,pitch:0,width:720,height:1280,polygon:[],mask:new Uint8Array([1,0])}]};
  vm.createContext(h);vm.runInContext(section('      const drawOutline=','      const animateSparks=')+'globalThis.draw=drawOutline;',h);
  h.draw();assert.equal(projected,0);h.target=[-.1,0,0];h.draw();assert.equal(projected,1);
  h.target=[0,0,0];h.zoom=.5;h.draw();assert.equal(projected,2);
  assert.deepEqual(Array.from(h.selections[0].mask),[1,0]);
});
