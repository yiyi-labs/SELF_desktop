import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

// Exercise the actual production handlers without loading WebGL or a personal asset.
const source=readFileSync(new URL('../main.js',import.meta.url),'utf8');
function section(start,end){
  const from=source.indexOf(start),to=source.indexOf(end,from);
  assert.ok(from>=0&&to>from,`Production handler boundaries changed: ${start}`);
  return source.slice(from,to);
}
function cameraHarness(){
  const state={preview:false,touching:false,yaw:0,pitch:0,zoom:1,
    targetYaw:.4,targetPitch:-.2,targetZoom:1.6,firstCamera:true,
    setMotionResolution:()=>{},original:[0,0,3],up:[0,1,0],target:[0,0,0],
    twoFinger:null,pivotGoal:null,portrait2:false,userTouched:false,aimPoint:null,
    canvas:{getBoundingClientRect:()=>({width:720,height:1280,left:0,top:0})},
    rotate:v=>v,normal:v=>{const n=Math.hypot(...v);return v.map(x=>x/n);},
    camera:{setPosition:()=>{},lookAt:()=>{}},radius:3,recordedFov:false,
    app:{renderNextFrame:false},cameraRevision:0,selections:[]};
  vm.createContext(state);
  vm.runInContext(section('const update=','      app.on(\'update\'')+'globalThis.tick=update;',state);
  return state;
}
function close(actual,expected,message){assert.ok(Math.abs(actual-expected)<1e-12,`${message}: ${actual} vs ${expected}`);}

test('production camera retains the original 60 Hz step on every orbit axis',()=>{
  const h=cameraHarness();h.tick(1/60);
  close(h.yaw,.08,'yaw');close(h.pitch,-.04,'pitch');close(h.zoom,1.12,'zoom');
});
test('equal elapsed time has equal response at 20, 30, 60, 120 and 240 Hz',()=>{
  const reference=cameraHarness();for(let i=0;i<18;i++)reference.tick(1/60);
  for(const fps of [20,30,60,120,240]){
    const h=cameraHarness();for(let i=0;i<fps*.3;i++)h.tick(1/fps);
    for(const key of ['yaw','pitch','zoom'])close(h[key],reference[key],`${fps} Hz ${key}`);
  }
});
test('initial call and invalid dt stay finite; resumed frames are bounded without overshoot',()=>{
  for(const dt of [undefined,NaN,Infinity]){
    const h=cameraHarness();h.tick(dt);close(h.yaw,.08,'fallback');
  }
  for(const dt of [0,-.1]){const h=cameraHarness();h.tick(dt);close(h.yaw,0,'nonpositive dt');}
  const bounded=cameraHarness();bounded.tick(.05);
  const resumed=cameraHarness();resumed.tick(10);
  close(resumed.yaw,bounded.yaw,'resume clamp');
  assert.ok(resumed.yaw>0&&resumed.yaw<resumed.targetYaw);
  assert.ok(resumed.zoom>1&&resumed.zoom<resumed.targetZoom);
});

function pointerHarness(){
  const events={};
  const state={mode:'move',touching:false,lastX:0,lastY:0,movePointers:new Map(),
    polygon:[],targetYaw:0,targetPitch:0,targetZoom:1,twoFinger:null,userTouched:false,
    yawBounds:[-Math.PI,Math.PI],pitchBounds:[-1,1],
    canvas:{addEventListener:(type,handler)=>{events[type]=handler;},setPointerCapture:()=>{}},
    interaction:()=>{},drawOutline:()=>{},clampZoom:v=>v};
  state.pointerGap=()=>{const p=[...state.movePointers.values()];return Math.hypot(p[0].x-p[1].x,p[0].y-p[1].y);};
  state.endTwoFinger=()=>{state.twoFinger=null;};
  state.freezeOnRelease=()=>{};
  vm.createContext(state);
  vm.runInContext(section("canvas.addEventListener('pointerdown'","      canvas.addEventListener('wheel'"),state);
  return {state,events};
}
for(const cancelledId of [1,2])test(`cancelling pointer ${cancelledId} rebases the remaining finger before rotation`,()=>{
  const {state:h,events}=pointerHarness();
  events.pointerdown({pointerId:1,clientX:10,clientY:20});
  events.pointerdown({pointerId:2,clientX:300,clientY:250});
  // Leave lastX/Y at the cancelled pointer, reproducing the previous jump.
  const initial=cancelledId===1?{x:10,y:20}:{x:300,y:250};
  events.pointermove({pointerId:cancelledId,clientX:initial.x,clientY:initial.y});
  events.pointercancel({pointerId:cancelledId});
  const remainingId=cancelledId===1?2:1,remaining=h.movePointers.get(remainingId);
  assert.equal(h.touching,true);assert.equal(h.twoFinger,null);
  assert.equal(h.lastX,remaining.x);assert.equal(h.lastY,remaining.y);
  events.pointermove({pointerId:remainingId,clientX:remaining.x+5,clientY:remaining.y+2});
  close(h.targetYaw,.04,'small remaining yaw delta');close(h.targetPitch,.016,'small remaining pitch delta');
});
test('last-pointer cancellation clears the gesture and ignores later moves',()=>{
  const {state:h,events}=pointerHarness();
  events.pointerdown({pointerId:1,clientX:50,clientY:60});h.polygon=[{x:1,y:1}];
  events.pointercancel({pointerId:1});events.pointermove({pointerId:1,clientX:900,clientY:900});
  assert.equal(h.touching,false);assert.equal(h.movePointers.size,0);
  assert.equal(h.polygon.length,0);assert.equal(h.targetYaw,0);
});
