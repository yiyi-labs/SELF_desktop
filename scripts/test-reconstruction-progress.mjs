import fs from 'node:fs';
import assert from 'node:assert/strict';
import {transform} from 'esbuild';

const source=fs.readFileSync('entry/src/main/ets/pages/SelfMirrorPage.ets','utf8');
function method(name){
  const match=new RegExp('(?:private (?:async )?)?'+name+'\\([^\\n]*?\\)[:][^{]+\\{').exec(source);
  assert.ok(match,'missing production method '+name);
  let depth=0,quote='';const start=match.index,body=source.indexOf('{',start);
  for(let i=body;i<source.length;i++){
    const c=source[i];
    if(quote){if(c==='\\'){i++;continue;}if(c===quote)quote='';continue;}
    if(c==='"'||c==="'"||c==='`'){quote=c;continue;}
    if(c==='{')depth++;
    if(c==='}'&&--depth===0)return source.slice(start,i+1);
  }
  throw Error('unterminated method '+name);
}
const activityStates=[],records=new Map(),opened=[],activated=[];
let status={state:'building',progress:38},networkError=false,finishDownload;
class Client {
  async status(){if(networkError)throw Error('offline');return status;}
  async downloadView(){return 'view';}
  async downloadGaussian(){if(finishDownload)await new Promise(resolve=>finishDownload=resolve);return 'gaussian';}
  async downloadPreview(){} async downloadPreview3d(){} async downloadScene3d(){}
}
const live={shared:()=>({sync:s=>activityStates.push(s)})};
const methods=['returnOrigin','minimizeReconstruction','openReconstructionProgress','progressCapsuleWidth',
  'progressCapsuleY','hasProgressCapsule','progressAwareTop','panelHeight','panelY','syncReconstructionActivity','trackReconstruction','finishReconstruction',
  'finishCancelledReconstruction','pollReconstruction','onBackPress'].map(method).join('\n');
const code=(await transform('class Harness{'+methods+'}\nmodule.exports=Harness;',{loader:'ts',format:'cjs'})).code;
const module={exports:{}};
new Function('module','Curve','setInterval','clearInterval','fs','ReconstructionTransportClient','ReconstructionLiveActivity',code)(
  module,{EaseInOut:0},()=>14,()=>{},
  {accessSync:p=>records.has(p),unlinkSync:p=>records.delete(p)},Client,live);
const create=()=>Object.assign(new module.exports(),{
  reconstructionActive:true,waitingMinimized:false,reconstructionOutcome:'',reconstructionReadyId:'',
  journey:'forming',reconJob:'a'.repeat(32),reconSubmitting:false,reconProgress:20,reconTimer:14,
  reconCancelling:false,reconChecking:false,foreground:true,keptStarName:'晚星',starNameKept:true,
  surfaceHeight:844,windowWidth:390,skyMounted:false,skyOpen:false,skyTransition:'idle',detail:'',
  cameraLive:false,careLibraryOpen:false,productOpen:false,legacyEditorOpen:false,tool:'NAVIGATE',introStage:0,
  language:'zh',context:{filesDir:'/private'},starNameController:{stopEditing(){}},
  assets:{writeAtomic:(p,v)=>records.set(p,JSON.parse(v))},stars:{upsert(){}},
  clearStarNameFocus(){},markInteraction(){},revealStory(){},setFormationLine(){},refreshStars(){},
  clearSkyTimers(){},clearGalaxyCaption(){},personalActive(){return false;},cueStory(){},
  activateGaussian:s=>activated.push(s),openStar:id=>opened.push(id),setStarNameKept(){},
  close(){this.detail='';this.cameraLive=false;},getUIContext(){return {animateTo:(o,f)=>f()};}
});
const pending='/private/reconstruction-pending.json';records.set(pending,{jobId:'a'.repeat(32),name:'晚星'});
const p=create();const interval=p.reconTimer;p.returnOrigin();
assert.equal(p.waitingMinimized,true);assert.equal(p.journey,'idle');assert.equal(p.reconJob,'a'.repeat(32));
assert.equal(p.reconTimer,interval);assert.equal(records.get(pending).name,'晚星');
p.detail='设置';p.skyOpen=true;await p.pollReconstruction();
assert.equal(p.reconProgress,38);assert.equal(p.detail,'设置');assert.equal(p.skyOpen,true);
networkError=true;await p.pollReconstruction();networkError=false;
assert.equal(p.reconProgress,38);assert.equal(p.reconstructionActive,true);assert.equal(p.detail,'设置');
status={state:'building',progress:51};await p.pollReconstruction();assert.equal(p.reconProgress,51);
p.openReconstructionProgress();assert.equal(p.waitingMinimized,false);assert.equal(p.journey,'forming');
assert.equal(p.detail,'');assert.equal(p.skyOpen,false);assert.equal(p.reconJob,'a'.repeat(32));
assert.equal(p.onBackPress(),true);assert.equal(p.waitingMinimized,true);
assert.equal(p.onBackPress(),false,'back at the origin can exit the app without cancelling the job');
// Upload handoff must not restore the full waiting page after the user left it.
p.trackReconstruction('b'.repeat(32));assert.equal(p.journey,'idle');assert.equal(records.get(pending).name,'晚星');
await new Promise(resolve=>setImmediate(resolve));
status={state:'gaussian_ready'};p.detail='留一句话';await p.pollReconstruction();
assert.equal(p.reconstructionActive,false);assert.equal(p.reconstructionOutcome,'ready');
assert.equal(p.detail,'留一句话');assert.equal(activated.length,0,'completion does not replace the current page');
assert.equal(p.reconstructionReadyId,'b'.repeat(32));assert.equal(p.reconProgress,100);
p.openReconstructionProgress();assert.equal(opened.at(-1),'b'.repeat(32));assert.equal(p.reconstructionOutcome,'');
// Return to full waiting while a completion download is in flight.
const race=create();race.minimizeReconstruction();finishDownload=true;
const downloading=race.pollReconstruction();await new Promise(resolve=>setImmediate(resolve));
race.openReconstructionProgress();finishDownload();finishDownload=null;await downloading;
assert.equal(race.journey,'revealing');assert.equal(activated.length,1);
const background=create();background.foreground=false;await background.pollReconstruction();
assert.equal(background.reconstructionActive,true);assert.equal(background.reconProgress,85);
assert.equal(activated.length,1,'background completion defers model transfer and navigation');
status={state:'failed',message:'camera_angles_insufficient'};
const failed=create();failed.minimizeReconstruction();failed.detail='设置';await failed.pollReconstruction();
assert.equal(failed.reconstructionOutcome,'failed');assert.equal(failed.detail,'设置');assert.equal(failed.journey,'idle');
failed.openReconstructionProgress();assert.equal(failed.journey,'failed');
status={state:'cancelled'};const cancelled=create();cancelled.minimizeReconstruction();await cancelled.pollReconstruction();
assert.equal(cancelled.reconstructionActive,false);assert.equal(cancelled.waitingMinimized,false);assert.equal(cancelled.reconstructionOutcome,'');
for(const [w,h] of [[360,640],[390,844],[832,1248],[1280,800]]){
  const v=create();v.windowWidth=w;v.surfaceHeight=h;v.wide=w>=840;v.detailTop=110;v.anchorY=16;v.panelPreferredHeight=()=>610;v.minimizeReconstruction();
  assert.ok(v.progressCapsuleWidth()<=w-40);assert.equal(v.progressCapsuleY(),v.wide?42:104);
  v.detail='设置';assert.ok(v.panelY()>=v.progressCapsuleY()+48+16);
  assert.ok(v.panelY()+v.panelHeight()<=h-20);
}
assert.match(source,/ReconstructionProgressCapsule\([\s\S]*?\.zIndex\(120\)/,'capsule is above nested panels');

// Execute the production Live View coordinator against a controlled system API.
const service=fs.readFileSync('entry/src/main/ets/services/ReconstructionLiveActivity.ets','utf8').replace(/^import .*;\r?\n/gm,'');
const serviceCode=(await transform(service+'\nmodule.exports=ReconstructionLiveActivity;',{loader:'ts',format:'cjs'})).code;
const calls=[],storage=new Map(),timers=new Map();let serial=0,clock=10000,enabled=true,rightsError=false,storedActive=false,buildBarrier=null;
const api={LayoutType:{LAYOUT_TYPE_PROGRESS:3},ExtensionType:{EXTENSION_TYPE_PROGRESS:5},CapsuleType:{CAPSULE_TYPE_TEXT:1},
  LifeCycleMode:{AUTO_STOP_WHEN_APP_TERMINATE:1},
  async isLiveViewEnabled(){return enabled;},async getActiveLiveView(){if(!storedActive)throw Error('not found');return {};},
  async startLiveView(v){if(rightsError)throw {code:1003500005};calls.push(['start',v]);storedActive=true;return {resultCode:0};},
  async updateLiveView(v){calls.push(['update',v]);return {resultCode:0};},
  async stopLiveView(v){calls.push(['stop',v]);storedActive=false;return {resultCode:0};}};
const sm={exports:{}};
new Function('module','exports','liveViewManager','wantAgent','AppStorage','setTimeout','clearTimeout','Date','deviceInfo',serviceCode)(
  sm,sm.exports,api,{OperationType:{START_ABILITY:0},WantAgentFlags:{UPDATE_PRESENT_FLAG:0},
    async getWantAgent(info){assert.equal(info.actionType,0);assert.deepEqual(info.actionFlags,[0]);
      if(buildBarrier)await new Promise(resolve=>buildBarrier=resolve);return {};}},
  {setOrCreate:(k,v)=>storage.set(k,v)},(f,delay)=>{timers.set(++serial,{f,delay});return serial;},id=>timers.delete(id),{now:()=>clock},{sdkApiVersion:26});
const Activity=sm.exports;const state={active:true,name:'晚星',progress:37,message:'正在构建',english:false};
const a=new Activity();a.sync(state);await a.flush();assert.equal(calls.length,0,'no activity in foreground');
a.setForeground(false);await a.flush();assert.equal(calls.at(-1)[0],'start');
assert.equal(calls.at(-1)[1].event,'PROGRESS');assert.equal(calls.at(-1)[1].liveViewData.capsule.content,'37%');
assert.equal(calls.at(-1)[1].lifeCycleMode,1,'local-only activities cannot remain stale after process death');
assert.equal(calls.at(-1)[1].liveViewData.primary.layoutData.nodeIcons.length,2);
clock+=500;a.sync({...state,progress:52});assert.equal(timers.get(a.timer).delay,700,'coalesced system updates stay below 1/second');
clock+=700;await a.flush();assert.equal(calls.at(-1)[0],'update');
a.setForeground(true);await a.flush();assert.equal(calls.at(-1)[0],'stop');assert.equal(calls.at(-1)[1].liveViewData.capsule.status,-1);
a.setForeground(false);a.sync({...state,active:false});await a.flush();assert.equal(calls.at(-1)[0],'stop','idle background does not create activity');
const blocked=new Activity();blocked.sync(state);blocked.setForeground(false);rightsError=true;await blocked.flush();
assert.equal(storage.get('selfLiveViewStatus'),'rights-required');rightsError=false;const before=calls.length;
await blocked.flush();assert.equal(calls.length,before,'no repeated entitlement failures on progress callbacks');
const late=new Activity();late.sync(state);late.setForeground(false);buildBarrier=true;const entering=late.flush();
await new Promise(resolve=>setImmediate(resolve));late.setForeground(true);buildBarrier();buildBarrier=null;await entering;
assert.equal(calls.length,before,'a late system start cannot show after returning to foreground');
storedActive=true;const restarted=new Activity();await restarted.flush();assert.equal(calls.at(-1)[0],'stop','restart removes stale activity');
enabled=false;const disabled=new Activity();disabled.sync(state);disabled.setForeground(false);await disabled.flush();
assert.equal(storage.get('selfLiveViewStatus'),'disabled');
console.log('PASS: minimize/resume/back, upload handoff, offline recovery, completion without navigation, completion race, background transfer deferral, failure/cancel, four screen sizes, Live View lifecycle/throttle/entitlement/foreground race/restart cleanup');
