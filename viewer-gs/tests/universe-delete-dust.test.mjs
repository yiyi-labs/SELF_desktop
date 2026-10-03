import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {performance} from 'node:perf_hooks';
import {transformSync} from 'esbuild';
const folder=new URL('../../entry/src/main/ets/pages/',import.meta.url);
const dustSource=fs.readFileSync(new URL('GalaxyDeleteDust.ets',folder),'utf8').replace(/^export /gm,'');
const rowSource=fs.readFileSync(new URL('GalaxyDeleteRow.ets',folder),'utf8');
const methods=rowSource.slice(rowSource.indexOf('  private clear('),rowSource.indexOf('  build(){'));
const flightSource=fs.readFileSync(new URL('GalaxyDeleteFlight.ets',folder),'utf8');
const flightMethods=flightSource.slice(flightSource.indexOf('  private clear('),flightSource.indexOf('  build(){'));
const payloadSource=flightSource.slice(flightSource.indexOf('export interface GalaxyDeleteFlightRequest'),flightSource.indexOf('/** A window-level')).replace(/^export /gm,'');
const code=transformSync(dustSource+'\n'+payloadSource+'\nclass Row{'+methods+'}\nclass Flight{'+flightMethods+'}\nglobalThis.Dust=GalaxyDeleteDust;globalThis.Row=Row;globalThis.Flight=Flight;',
  {loader:'ts',target:'es2020'}).code;
function fixture(){
  let now=1000,key=0,released=0;const timers=new Map(),finished=[],uploads=[],logs=[];
  const snapshot={release:async()=>{released++;},getImageInfoSync:()=>({size:{width:528,height:376},pixelFormat:3,alphaType:3}),
    getPixelBytesNumber:()=>528*376*4,readPixelsToBufferSync:buffer=>{
      const data=new Uint8Array(buffer);for(let at=0;at<data.length;at+=4){data[at]=48;data[at+1]=55;data[at+2]=74;data[at+3]=255;}
    }};
  let resolve;const result=new Promise(done=>resolve=done);
  const schedule=(fn,delay,repeat)=>{const id=++key;timers.set(id,{fn,delay,at:now+delay,repeat});return id;};
  const context=vm.createContext({console:{info:msg=>logs.push(msg),warn:msg=>logs.push(msg)},
    image:{PixelMapFormat:{BGRA_8888:4},AlphaType:{PREMUL:2}},LengthMetricsUnit:{PX:1},
    ImageData:class{constructor(w,h,data,unit){this.width=unit===1?w:w*2;this.height=unit===1?h:h*2;this.data=data||new Uint8ClampedArray(this.width*this.height*4);}},
    Date:{now:()=>now},setInterval:(fn,delay)=>schedule(fn,delay,true),setTimeout:(fn,delay)=>schedule(fn,delay,false),
    clearInterval:id=>timers.delete(id),clearTimeout:id=>timers.delete(id)});
  vm.runInContext(code,context);const row=new context.Row(),flight=new context.Flight();
  Object.assign(flight,{request:undefined,active:true,motion:true,prepared:true,timer:-1,paintedRequest:undefined,
    frame:undefined,lastFrame:-1,frameCount:0,paintTime:0,maxPaint:0,onDiagnostics:msg=>logs.push(msg),
    onEnded:()=>{flight.request=undefined;flight.requestChanged();row.finish();},
    getUIContext:()=>({vp2px:value=>value*3}),
    drawing:{clearRect:()=>{},putImageData:(frame,x,y)=>uploads.push({time:now,x,y,width:frame.width,height:frame.height})}});
  Object.assign(row,{rowId:'fixture',deleting:false,motion:true,active:true,snapshotVisible:false,rowWidth:264,rowHeight:188,
    rowX:20,rowY:210,timer:-1,payloadToken:-1,generation:0,finished:false,onDiagnostics:msg=>logs.push(msg),
    onFlight:request=>{flight.request=request;flight.requestChanged();},
    getUIContext:()=>({getComponentSnapshot:()=>({get:()=>result})}),onDissolved:(...args)=>finished.push(args)});
  const advance=ms=>{
    const end=now+ms;
    while(true){const next=[...timers].filter(([,t])=>t.at<=end).sort((a,b)=>a[1].at-b[1].at)[0];
      if(!next)break;now=next[1].at;if(next[1].repeat)next[1].at+=next[1].delay;else timers.delete(next[0]);next[1].fn();}now=end;
  };
  return {row,flight,context,snapshot,resolve,advance,timers,finished,uploads,logs,released:()=>released};
}
function prepareDust(f){const dust=new f.context.Dust(264,188);dust.prepare(dust.bufferWidth*2,dust.bufferHeight*2);return dust;}

test('dense grains retain curved up-right paths and stagger lower-left before upper-right',()=>{
  const f=fixture(),dust=prepareDust(f);
  assert.ok(dust.tiles.length>1800&&dust.tiles.length<2300,'over three times the former density');
  assert.ok(dust.tiles.some(tile=>tile.y>60),'confirmation participates');
  for(const tile of dust.tiles){
    const first=dust.frame(tile,0),last=dust.frame(tile,f.context.Dust.duration);
    assert.equal(first.opacity,0);assert.equal(last.opacity,0);assert.ok(last.x>first.x&&last.y<first.y);
    assert.equal(last.scale,1);
    const mid=dust.frame(tile,tile.delay+tile.life*.5);assert.ok(mid.opacity>0);
    assert.ok(Math.hypot(mid.x-tile.x-tile.distance*.42,mid.y-tile.y+tile.drift*.42)>1,'curved breeze');
  }
  const lower=dust.tiles.filter(p=>p.x<20&&p.y>168),upper=dust.tiles.filter(p=>p.x>244&&p.y<20);
  assert.ok(Math.max(...lower.map(p=>p.delay))<Math.min(...upper.map(p=>p.delay)));
});

test('source pixels permanently leave their own irregular fragment exactly when its grains are released',()=>{
  const f=fixture(),dust=prepareDust(f),data=new Uint8ClampedArray(dust.base.length);
  dust.render(data,0);const initial=new Uint8ClampedArray(dust.base);
  assert.equal(initial.reduce((sum,value,i)=>sum+(i%4===3&&value>0?1:0),0),528*376);
  dust.render(data,320);
  let erased=0,retained=0;
  for(let i=0;i<dust.tiles.length;i++)for(let p=dust.heads[i];p>=0;p=dust.next[p]){
    const at=dust.destinations[p];
    if(dust.tiles[i].delay<=320){assert.ok(dust.base.slice(at,at+4).every(v=>v===0));erased++;}
    else{assert.equal(dust.base[at+3],initial[at+3]);retained++;}
  }
  assert.ok(erased>30000&&retained>30000,'a real partial dissolution, not an overlay over the intact source');
  const middle=new Uint8ClampedArray(dust.base);dust.render(data,704);
  for(let i=3;i<middle.length;i+=4)if(middle[i]===0)assert.equal(dust.base[i],0,'erased pixels cannot reappear');
  assert.equal(dust.base.reduce((sum,value,i)=>sum+(i%4===3&&value>0?1:0),0),0);
  let above=0;const rowTop=Math.round(dust.top*2),stride=dust.bufferWidth*2;
  for(let y=0;y<rowTop;y++)for(let x=0;x<stride;x++)if(data[(y*stride+x)*4+3]>0)above++;
  assert.ok(above>1000,'dense grains float above the former row');
  dust.render(data,f.context.Dust.duration);assert.ok(data.every((v,i)=>i%4!==3||v===0),'all grains finish before the rise');
});

test('snapshot color channels, premultiplied edges and transparent holes survive the transfer',()=>{
  const f=fixture(),pixels=new Uint8Array([25,50,100,128,0,0,0,0]),dust=new f.context.Dust(10,5,pixels,2,1,true,true);
  dust.prepare(dust.bufferWidth,dust.bufferHeight);const data=new Uint8ClampedArray(dust.base.length);dust.render(data,0);
  const at=((dust.top+2)*dust.bufferWidth+dust.left+2)*4;
  assert.equal(data[at+3],128);assert.equal(data[at],100);assert.equal(data[at+2],25);
  assert.equal(data[((dust.top+2)*dust.bufferWidth+dust.left+7)*4+3],0);
  for(const tile of dust.tiles.filter(tile=>tile.alpha>0)){
    assert.ok(Math.abs(tile.r-100*255/128)<.01);
    assert.ok(Math.abs(tile.g-50*255/128)<.01);
    assert.ok(Math.abs(tile.b-25*255/128)<.01,'particles inherit source color without a blue tint or brightening');
  }
});

test('one raster upload per frame replaces thousands of Canvas calls, while height waits for the final grain',async()=>{
  const f=fixture(),r=f.row;r.deleting=true;r.deletionChanged();
  assert.equal(r.snapshotVisible,false);f.resolve(f.snapshot);await new Promise(resolve=>setImmediate(resolve));
  assert.equal(r.snapshotVisible,true);assert.equal(f.released(),1);
  f.advance(1664);assert.equal(f.finished.length,0);assert.equal(r.rowHeight,188);
  assert.equal(f.uploads.length,53);assert.equal(new Set(f.uploads.map(p=>p.time)).size,53);
  assert.equal(f.uploads[0].x,0);assert.equal(f.uploads[0].y,0);
  assert.equal(f.flight.canvasX,-4);assert.equal(f.flight.canvasY,-38);
  assert.equal(f.uploads[0].width,418);assert.equal(f.flight.canvasWidth*3,418);
  f.advance(32);assert.deepEqual(f.finished,[['fixture',188]]);assert.equal(f.timers.size,0);
  assert.equal(f.released(),1);assert.ok(f.logs.some(x=>x.includes('SELF_STAR_DISSOLVE_RASTER')));
});

test('a late snapshot cannot restart dissolution after the row leaves the screen',async()=>{
  const f=fixture(),r=f.row;r.deleting=true;r.deletionChanged();r.aboutToDisappear();
  f.resolve(f.snapshot);await new Promise(resolve=>setImmediate(resolve));assert.equal(f.timers.size,0);assert.equal(f.finished.length,0);assert.equal(f.released(),1);
});

test('reduced motion or background settles once and clears rendering resources',async()=>{
  const f=fixture(),r=f.row;r.deleting=true;r.deletionChanged();f.resolve(f.snapshot);await new Promise(resolve=>setImmediate(resolve));
  f.flight.active=false;f.flight.activityChanged();r.active=false;r.activityChanged();r.activityChanged();
  assert.equal(f.finished.length,1);assert.equal(f.timers.size,0);assert.equal(f.released(),1);assert.equal(f.flight.frame,undefined);
});

test('clearing the flight request removes its old window drawing and frees cached source pixels',async()=>{
  const f=fixture(),r=f.row;r.deleting=true;r.deletionChanged();f.resolve(f.snapshot);await new Promise(resolve=>setImmediate(resolve));
  const dust=f.flight.dust;f.advance(200);f.flight.request=undefined;f.flight.requestChanged();
  assert.equal(f.flight.paintedRequest,undefined);assert.equal(f.flight.timer,-1);assert.equal(dust.base.length,0);
  r.aboutToDisappear();assert.equal(f.timers.size,0);
});

test('an unavailable flight canvas still releases the row after the bounded recovery timeout',async()=>{
  const f=fixture(),r=f.row;f.flight.prepared=false;r.deleting=true;r.deletionChanged();
  f.resolve(f.snapshot);await new Promise(resolve=>setImmediate(resolve));f.advance(2296);
  assert.deepEqual(f.finished,[['fixture',188]]);assert.equal(f.timers.size,0);
  assert.equal(vm.runInContext('pendingDust.size',f.context),0);
});

test('UI state carries only primitive metadata; typed pixel buffers retain their native internal slots',async()=>{
  const f=fixture(),r=f.row;r.onFlight=request=>{
    assert.ok(Object.values(request).every(value=>typeof value==='string'||typeof value==='number'));
    // A state wrapper can proxy metadata freely, but it never receives a typed array or its owner.
    f.flight.request=new Proxy(request,{get:(target,key)=>Reflect.get(target,key)});f.flight.requestChanged();
  };
  r.deleting=true;r.deletionChanged();f.resolve(f.snapshot);await new Promise(resolve=>setImmediate(resolve));
  assert.equal(f.flight.dust.base.byteLength>0,true);f.advance(1696);
  assert.deepEqual(f.finished,[['fixture',188]]);assert.equal(vm.runInContext('pendingDust.size',f.context),0);
});

test('cached raster renders need no per-frame trajectory calculation',()=>{
  const f=fixture(),dust=prepareDust(f),data=new Uint8ClampedArray(dust.base.length);
  dust.frame=()=>{throw new Error('trajectory recomputed during animation');};
  dust.makeKernel=()=>{throw new Error('sphere shading recomputed during animation');};
  const start=performance.now();for(let t=0;t<=f.context.Dust.duration;t+=32)dust.render(data,t);
  console.log('54 dense raster frames: '+Math.round(performance.now()-start)+' ms on the offline runtime');
});

test('cached sphere sprites are round, softly shaded and use a sparse halo in the source color',()=>{
  const f=fixture(),dust=prepareDust(f);assert.equal(dust.kernels.length,48);
  const kernel=dust.kernels[0],weight=(x,y)=>{
    for(let at=0;at<kernel.length;at+=3)if(kernel[at]===x&&kernel[at+1]===y)return kernel[at+2];return 0;
  };
  assert.ok(weight(0,0)>weight(1,1));assert.ok(weight(-1,-1)>weight(1,1),'upper-left light and lower-right shade');
  assert.ok(weight(1,1)>0,'soft round edges avoid a cross-shaped five-pixel grain');
  assert.equal(weight(4,4),0);assert.ok(dust.kernels[32].length>kernel.length,'glow is reserved for sparse bright grains');
  assert.ok(dust.tiles.filter(tile=>tile.light).length/dust.tiles.length<.13);
});

test('only the deletion pauses the galaxy renderer, and it resumes without advancing the camera',()=>{
  const source=fs.readFileSync(new URL('../universe.js',import.meta.url),'utf8');
  const configure=source.slice(source.indexOf('function configure('),source.indexOf('function sync('));
  const update=source.slice(source.indexOf('function update('),source.indexOf('async function start('));
  const document={body:{classList:{toggle(){}}},documentElement:{},getElementById:()=>({})};
  const context=vm.createContext({document,hint:{},app:{autoRender:true},paused:false,language:'zh',motion:true,
    t:()=>'',LANG_TAG:{zh:'zh-CN',en:'en',ja:'ja',ko:'ko'},canvas:{setAttribute(){}},names:{setAttribute(){}}});
  vm.runInContext(configure+update,context);context.configure({paused:true});assert.equal(context.app.autoRender,false);
  assert.doesNotThrow(()=>context.update(.016),'paused update must not move or redraw the scene');
  context.configure({paused:false});assert.equal(context.app.autoRender,true);
});
