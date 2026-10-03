// Execute the actual ArkTS journey methods with a virtual clock and file store.
// This checks native state/timer races offline, not ArkUI rendering or device frame rate.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {transformSync} from 'esbuild';

const source=fs.readFileSync(new URL('../../entry/src/main/ets/pages/SelfMirrorPage.ets',import.meta.url),'utf8');
const section=(from,to)=>{
  const start=source.indexOf(from),end=source.indexOf(to,start+from.length);
  assert.ok(start>=0&&end>start,`Missing native method boundary: ${from}`);
  return source.slice(start,end);
};
const methods=section('  private activateGaussian(','  private async restoreGaussian(')+
  section('  private refreshStars(','  private requestGalaxyScene(')+
  section('  private selectStarPreview(','  private saveStarName(');
const compiled=transformSync(`class Journey {${methods}} globalThis.Journey=Journey;`,{loader:'ts',target:'es2020'}).code;
const generic='走过的光，还在这里等你。';
const id=index=>index.toString(16).padStart(32,'0');

function fixture({motion=true,names=['外婆','新的我','海边的夏天']}={}){
  let now=100000,serial=0;
  const timers=new Map(),animations=[],existing=new Set(),contents=new Map(),removed=[];
  const records=names.map((name,index)=>({jobId:id(index+1),name,scene3dPath:'cached'}));
  const paths=jobId=>({gaussian:`/virtual/models/${jobId}/portrait.gaussian.ply`,view:`/virtual/models/${jobId}/portrait.view.json`});
  for(const star of records)Object.values(paths(star.jobId)).forEach(file=>existing.add(file));
  const context=vm.createContext({
    Date:{now:()=>now},Curve:{EaseInOut:'ease-in-out',EaseOut:'ease-out'},
    fs:{accessSync:file=>existing.has(file),readTextSync:file=>contents.get(file),unlinkSync:file=>existing.delete(file)},console:{info:()=>{},warn:()=>{}},
    setTimeout:(fn,delay)=>{const key=++serial;timers.set(key,{fn,at:now+delay});return key;},
    clearTimeout:key=>timers.delete(key)
  });
  vm.runInContext(compiled,context);
  const page=new context.Journey();
  Object.assign(page,{
    motion,language:'zh',skyMounted:false,skyOpen:false,skyOpacity:0,skyVeil:0,skyTransition:'idle',
    galaxyTravelId:'',galaxyStatus:'',galaxyCaption:generic,galaxyCaptionOpacity:1,
    galaxyCaptionTimer:-1,galaxyCaptionGeneration:0,galaxyCaptionChangedAt:now,skyTimers:[],skyGeneration:0,
    originMode:true,journey:'idle',previewStarId:'',galaxyNavigationSerial:0,starItems:records.slice(),galaxyDeleteId:'',
    galaxyDissolvingId:'',galaxyRiseIds:[],galaxyRiseOffset:0,galaxyDeletedIndex:-1,galaxyRiseTimer:-1,
    context:{filesDir:'/virtual'},stars:{list:()=>records.slice(),modelPaths:paths,remove:jobId=>{
      removed.push(jobId);const index=records.findIndex(record=>record.jobId===jobId);if(index>=0)records.splice(index,1);
    }},
    markInteraction:()=>{},cueStory:()=>{},revealStory:()=>{},requestGalaxyScene:()=>{},
    audio:{setScene:()=>{}},
    getUIContext:()=>({animateTo:(options,action)=>{animations.push({at:now,...options});action();}})
  });
  const advance=duration=>{
    const end=now+duration;let iterations=0;
    while(true){
      const next=[...timers.entries()].filter(([,entry])=>entry.at<=end).sort((a,b)=>a[1].at-b[1].at||a[0]-b[0])[0];
      if(!next)break;
      assert.ok(++iterations<1000,'Runaway journey timer');
      now=next[1].at;timers.delete(next[0]);next[1].fn();
    }
    now=end;
  };
  return {page,advance,timers,animations,existing,contents,removed,paths,now:()=>now};
}
function enter(f){f.page.enterSky();f.advance(1810);assert.equal(f.page.skyTransition,'idle');assert.equal(f.page.skyOpen,true);}

test('enter/return and repeated visits leave no delayed screen changes',()=>{
  const f=fixture(),p=f.page;
  for(let cycle=0;cycle<20;cycle++){
    p.enterSky();p.enterSky();assert.equal(p.skyOpen,false);assert.equal(p.skyMounted,true);
    f.advance(579);assert.equal(p.skyOpen,false);
    f.advance(1231);assert.equal(p.skyOpen,true);assert.equal(p.skyTransition,'idle');
    p.returnOrigin();f.advance(1540);assert.equal(p.skyMounted,false);assert.equal(p.skyOpen,false);
    assert.equal(p.skyTransition,'idle');assert.equal(p.skyVeil,0);assert.equal(f.timers.size,0);
  }
  f.advance(60000);assert.equal(p.skyOpen,false);assert.equal(p.galaxyCaption,generic);
});

test('return before entry finishes cancels its stale callback',()=>{
  const f=fixture(),p=f.page;p.enterSky();f.advance(180);p.returnOrigin();
  f.advance(60000);assert.equal(p.skyOpen,false);assert.equal(p.skyMounted,false);
  assert.equal(p.skyTransition,'idle');assert.equal(f.timers.size,0);
});

test('rapid selection stays quiet and only publishes the final settled name',()=>{
  const f=fixture(),p=f.page;enter(f);
  for(let index=0;index<40;index++){p.selectStarPreview(id(index%3+1));f.advance(180);assert.equal(p.galaxyCaption,generic);}
  p.selectStarPreview(id(3));f.advance(2199);assert.equal(p.galaxyCaption,generic);
  f.advance(1);assert.equal(p.galaxyCaptionOpacity,0);assert.equal(p.galaxyCaption,generic);
  f.advance(480);assert.equal(p.galaxyCaption,'循着「海边的夏天」，回到那一刻。');assert.equal(p.galaxyCaptionOpacity,1);
  const changed=f.now();p.selectStarPreview(id(2));f.advance(5999);
  assert.equal(p.galaxyCaption,'循着「海边的夏天」，回到那一刻。');
  f.advance(481);assert.equal(p.galaxyCaption,'循着「新的我」，回到那一刻。');assert.ok(f.now()-changed>=6000);
});

test('a drag, new selection or departure cancels a pending caption fade',()=>{
  const f=fixture(),p=f.page;enter(f);f.advance(4190);assert.equal(p.galaxyCaptionOpacity,0);
  p.selectStarPreview(id(2));f.advance(500);assert.equal(p.galaxyCaption,generic);
  // Repeated interaction calls the same debouncer used by the native Web bridge.
  for(let n=0;n<6;n++){p.scheduleGalaxyCaption();f.advance(1600);assert.equal(p.galaxyCaption,generic);}
  f.advance(1080);assert.match(p.galaxyCaption,/新的我/);
  p.selectStarPreview(id(3));p.returnOrigin();f.advance(60000);
  assert.doesNotMatch(p.galaxyCaption,/海边/);assert.equal(f.timers.size,0);
});

test('unnamed memories stay generic; long names stay bounded; reduced motion has no animated durations',()=>{
  for(const name of ['未命名的星辰','我的星辰 12','123','']){
    const f=fixture({names:[name]});enter(f);f.advance(10000);assert.equal(f.page.galaxyCaption,generic);
  }
  const f=fixture({motion:false,names:['一个非常非常非常非常非常非常漫长的星辰名字']}),p=f.page;
  p.enterSky();f.advance(6000);assert.match(p.galaxyCaption,/…/);assert.ok(p.galaxyCaption.length<28);
  p.returnOrigin();f.advance(0);assert.equal(p.skyMounted,false);assert.ok(f.animations.every(a=>a.duration===0));
});

test('cancelled, duplicate and wrong-id flight messages cannot open another memory',()=>{
  const f=fixture(),p=f.page;enter(f);p.openStar(id(1));p.openStar(id(2));
  assert.equal(p.galaxyTravelId,id(1));p.arriveAtGalaxy(id(2));assert.equal(p.skyTransition,'approaching');
  p.recoverGalaxy();p.arriveAtGalaxy(id(1));f.advance(15000);
  assert.equal(p.skyOpen,true);assert.equal(p.skyTransition,'idle');assert.equal(p.galaxyStatus,'');
  p.openStar(id(2));p.arriveAtGalaxy(id(2));assert.equal(p.skyTransition,'loading');
  const pending=f.timers.size;p.arriveAtGalaxy(id(2));assert.equal(f.timers.size,pending);
  p.recoverGalaxy();p.finishGalaxyArrival();f.advance(35000);
  assert.equal(p.skyOpen,true);assert.equal(p.skyMounted,true);assert.equal(p.skyTransition,'idle');
});

test('flight and loading timeouts recover a usable stars screen',()=>{
  const f=fixture(),p=f.page;enter(f);p.openStar(id(1));f.advance(12000);
  assert.equal(p.skyTransition,'idle');assert.equal(p.skyOpen,true);assert.match(p.galaxyStatus,/再试/);
  p.openStar(id(1));p.arriveAtGalaxy(id(1));f.advance(29999);assert.equal(p.skyTransition,'loading');
  f.advance(1);assert.equal(p.skyTransition,'idle');assert.equal(p.skyMounted,true);assert.equal(p.skyOpen,true);
  assert.match(p.galaxyStatus,/稍后/);assert.equal(p.galaxyTravelId,'');
});

test('missing or removed full memory recovers without an empty editor',()=>{
  const f=fixture(),p=f.page;enter(f);const path=f.paths(id(1)).gaussian;
  f.existing.delete(path);p.openStar(id(1));assert.equal(p.skyTransition,'idle');assert.equal(p.galaxyTravelId,'');
  assert.match(p.galaxyStatus,/未能展开/);f.existing.add(path);p.openStar(id(1));f.existing.delete(path);p.arriveAtGalaxy(id(1));
  assert.equal(p.skyOpen,true);assert.equal(p.skyTransition,'idle');assert.match(p.galaxyStatus,/未能展开/);
});

test('successful arrival clears watchdogs and can return through stars to home',()=>{
  const f=fixture(),p=f.page;enter(f);p.openStar(id(1));f.advance(2350);p.arriveAtGalaxy(id(1));
  assert.equal(p.skyOpen,false);assert.equal(p.skyMounted,true);assert.equal(p.skyTransition,'loading');
  f.advance(1200);p.finishGalaxyArrival();assert.equal(p.skyTransition,'arriving');f.advance(1180);
  assert.equal(p.skyMounted,false);assert.equal(p.originMode,false);assert.equal(p.skyTransition,'idle');
  assert.equal(p.activeStarId,id(1));assert.equal(f.timers.size,0);
  enter(f);p.returnOrigin();f.advance(60000);assert.equal(p.originMode,true);assert.equal(p.skyOpen,false);
  assert.equal(p.skyTransition,'idle');assert.equal(p.galaxyStatus,'');assert.equal(f.timers.size,0);
});

test('delete requires an explicit matching confirmation; cancelling or closing preserves the star',()=>{
  const f=fixture(),p=f.page;enter(f);p.galaxyDialOpen=true;
  p.removeGalaxy(id(1));assert.equal(f.removed.length,0);
  p.setGalaxyDelete(id(1));p.removeGalaxy(id(2));assert.equal(f.removed.length,0);
  p.setGalaxyDelete('');p.removeGalaxy(id(1));assert.equal(f.removed.length,0);
  p.setGalaxyDelete(id(1));p.setGalaxyDial(false);assert.equal(p.galaxyDeleteId,'');
  p.removeGalaxy(id(1));assert.equal(f.removed.length,0);
  p.setGalaxyDelete(id(1));p.openStar(id(1));p.removeGalaxy(id(1));assert.equal(f.removed.length,0);
  assert.equal(p.galaxyDeleteId,'');assert.equal(p.skyTransition,'approaching');
});

test('deleting another star preserves camera selection and the currently restored memory',()=>{
  const f=fixture(),p=f.page;enter(f);p.galaxyDialOpen=true;p.activeStarId=id(1);
  const serial=p.galaxyNavigationSerial;
  const saved='/virtual/reconstruction-result.json';f.existing.add(saved);f.contents.set(saved,JSON.stringify({jobId:id(1)}));
  p.setGalaxyDelete(id(3));p.removeGalaxy(id(3));
  p.finishGalaxyDelete(id(3),188);f.advance(650);
  assert.equal(p.previewStarId,id(1));assert.equal(p.activeStarId,id(1));assert.equal(p.galaxyNavigationSerial,serial);
  assert.equal(p.galaxyDialOpen,true);assert.equal(p.starItems.length,2);assert.equal(p.galaxySceneItems.length,2);
  assert.equal(f.existing.has(saved),true);assert.deepEqual(f.removed,[id(3)]);
});

test('deleting the selected star chooses its neighbour and clears the deleted restoration reference',()=>{
  const f=fixture(),p=f.page;enter(f);p.selectStarPreview(id(2));p.activeStarId=id(2);
  p.personalGaussianPath=f.paths(id(2)).gaussian;p.personalViewPath=f.paths(id(2)).view;
  const saved='/virtual/reconstruction-result.json';f.existing.add(saved);f.contents.set(saved,JSON.stringify({jobId:id(2)}));
  p.setGalaxyDelete(id(2));p.removeGalaxy(id(2));
  p.finishGalaxyDelete(id(2),188);f.advance(650);
  assert.equal(p.previewStarId,id(3));assert.equal(p.activeStarId,'');assert.equal(p.personalGaussianPath,'');
  assert.equal(f.existing.has(saved),false);assert.equal(p.galaxyCaption,generic);
  f.advance(6500);assert.match(p.galaxyCaption,/海边/);assert.doesNotMatch(p.galaxyCaption,/新的我/);
});

test('deleting the final star leaves a quiet empty sky and no stale caption',()=>{
  const f=fixture({names:['外婆']}),p=f.page;enter(f);f.advance(6500);
  p.setGalaxyDelete(id(1));p.removeGalaxy(id(1));p.finishGalaxyDelete(id(1),188);f.advance(10000);
  assert.equal(p.starItems.length,0);assert.equal(p.galaxySceneItems.length,0);assert.equal(p.previewStarId,'');
  assert.equal(p.galaxyCaption,generic);assert.equal(p.galaxyCaptionOpacity,1);assert.equal(p.skyOpen,true);
  assert.equal(p.skyTransition,'idle');assert.equal(f.timers.size,0);
});

test('a persistence failure preserves selection, confirmation and all stars for retry',()=>{
  const f=fixture(),p=f.page;enter(f);p.setGalaxyDelete(id(1));
  p.stars.remove=()=>{throw new Error('storage unavailable');};p.removeGalaxy(id(1));
  assert.equal(p.starItems.length,3);assert.equal(p.previewStarId,id(1));assert.equal(p.galaxyDeleteId,id(1));
  assert.match(p.galaxyStatus,/暂未清理完成/);
});

test('the complete row keeps its gap until dissolution finishes, then only lower rows spring up',()=>{
  const f=fixture(),p=f.page;enter(f);p.galaxyDialOpen=true;
  p.setGalaxyDelete(id(2));p.removeGalaxy(id(2));
  assert.deepEqual(f.removed,[id(2)]);assert.equal(p.starItems.length,3);
  assert.equal(p.galaxyDeleteId,id(2));assert.equal(p.galaxyDissolvingId,id(2));
  assert.equal(p.galaxyRiseIds.length,0);f.advance(760);assert.equal(p.starItems.length,3);
  p.refreshStars();assert.equal(p.starItems.length,3,'a late model download cannot remove the gap');
  p.removeGalaxy(id(2));assert.equal(f.removed.length,1,'duplicate confirmation is ignored');
  p.finishGalaxyDelete(id(2),188);assert.equal(p.starItems.length,2);
  assert.deepEqual(Array.from(p.galaxyRiseIds),[id(3)]);assert.equal(p.galaxyRiseOffset,192);
  f.advance(31);assert.equal(p.galaxyRiseOffset,192);
  f.advance(1);assert.equal(p.galaxyRiseOffset,0);assert.match(f.animations.at(-1).curve,/spring/);
  f.advance(600);assert.equal(p.galaxyRiseIds.length,0);assert.equal(f.timers.size,1); // caption settling timer
});
test('closing during dissolution commits the deleted row once without a stale animation',()=>{
  const f=fixture(),p=f.page;enter(f);p.setGalaxyDelete(id(2));p.removeGalaxy(id(2));
  p.setGalaxyDial(false);assert.equal(p.starItems.length,2);assert.equal(p.galaxyDissolvingId,'');
  p.finishGalaxyDelete(id(2),188);f.advance(10000);assert.equal(p.galaxyRiseIds.length,0);
  assert.deepEqual(f.removed,[id(2)]);assert.equal(f.timers.size,0);
});
test('reduced motion deletes immediately without leaving a ghost row',()=>{
  const f=fixture({motion:false}),p=f.page;enter(f);p.setGalaxyDelete(id(1));p.removeGalaxy(id(1));
  assert.equal(p.starItems.length,2);assert.equal(p.galaxyDissolvingId,'');assert.equal(p.galaxyRiseIds.length,0);
});
