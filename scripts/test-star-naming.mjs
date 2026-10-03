import fs from 'node:fs';
import assert from 'node:assert/strict';
import {transform} from 'esbuild';
import {chromium} from 'playwright-core';

const pageSource=fs.readFileSync('entry/src/main/ets/pages/SelfMirrorPage.ets','utf8').replace(/\r\n/g,'\n');
const skySource=fs.readFileSync('entry/src/main/ets/pages/NightSkySurface.ets','utf8');
const storeSource=fs.readFileSync('entry/src/main/ets/services/PortraitStarStore.ets','utf8');
const section=(source,start,end)=>source.slice(source.indexOf(start),source.indexOf(end));
const methods=section(pageSource,'  private saveStarName()','  private setFormationLine(')+
  section(pageSource,'  private trackReconstruction(','  private async submitCapture(');
const code=(await transform(`class PortraitStarStore {${section(storeSource,'  static cleanName(','  private directory(')}}
  class NameHarness {${methods}} module.exports=NameHarness;`,{loader:'ts',format:'cjs'})).code;
const timers=new Map();let timerId=0,now=1000,failWrite=false,status={state:'building',progress:20};
const saved=new Map(),completed=[],animations=[];
const presenceKeys=['starNameEditorPresence','starNameLabelPresence'];
class Client {
  async status(){return status;}
  async downloadView(){return 'view';}
  async downloadGaussian(){return 'gaussian';}
  async downloadPreview(){}
  async downloadPreview3d(){}
  async downloadScene3d(){}
}
const module={exports:{}};
new Function('module','exports','Curve','setTimeout','clearTimeout','setInterval','clearInterval','fs','ReconstructionTransportClient',code)(
  module,module.exports,{EaseInOut:'ease',EaseOut:'ease'},
  fn=>{timers.set(++timerId,fn);return timerId;},id=>timers.delete(id),()=>99,()=>{},
  {accessSync:path=>saved.has(path),unlinkSync:path=>saved.delete(path)},Client);
const create=()=>Object.assign(new module.exports(),{
  journey:'forming',starNameDraft:'',keptStarName:'',starNameKept:false,starNameError:'',
  starNameEditorPresence:1,starNameLabelPresence:0,surfaceWidth:390,surfaceHeight:844,wide:false,
  language:'zh',motion:true,reconCancelling:false,reconJob:'a'.repeat(32),reconChecking:false,reconTimer:-1,
  starNameFocusTimer:-1,reconProgress:22,context:{filesDir:'/private'},
  assets:{writeAtomic(path,value){if(failWrite)throw Error('disk unavailable');saved.set(path,JSON.parse(value));}},
  stars:{upsert(id,name){completed.push(name);}},markInteraction(){},clearSkyTimers(){},syncReconstructionActivity(){},foreground:true,
  starNameController:{stopEditing(){}},getUIContext(){return {
    animateTo:(options,fn)=>{const from=presenceKeys.map(key=>this[key]);fn();animations.push({options,from,to:presenceKeys.map(key=>this[key])});},
    getFocusController(){return {requestFocus(){throw Error('late focus');}}}
  };},setFormationLine(){},activateGaussian(){},refreshStars(){},cueStory(){}
});
const pending='/private/reconstruction-pending.json';
const p=create();p.starNameDraft='  晚星  ';p.saveStarName();
assert.equal(p.starNameKept,true);assert.equal(saved.get(pending).name,'晚星');
p.saveStarName();assert.equal(animations.length,2,'double tap does not restart either layer');
p.editStarName();assert.equal(p.starNameDraft,'晚星');assert.equal(p.starNameKept,false);
p.starNameDraft='晨光';p.saveStarName();assert.equal(saved.get(pending).name,'晨光');
p.editStarName();p.starNameDraft='还没确认';p.focusStarName();
status={state:'gaussian_ready'};await p.pollReconstruction();
assert.equal(completed.at(-1),'晨光','completion during editing retains the last confirmed name');
assert.equal(timers.size,0,'completion cancels pending keyboard focus');
assert.equal(p.journey,'revealing');p.editStarName();p.saveStarName();assert.equal(completed.length,1);
const blank=create();blank.starNameDraft='   ';blank.saveStarName();assert.equal(blank.starNameKept,false);
const error=create();error.starNameDraft='重试的名字';failWrite=true;error.saveStarName();
assert.equal(error.starNameKept,false);assert.ok(error.starNameError);failWrite=false;error.saveStarName();assert.equal(error.starNameKept,true);
const uploading=create();uploading.reconJob='';uploading.starNameDraft='上传中的名字';uploading.saveStarName();
status={state:'building',progress:24};uploading.trackReconstruction('b'.repeat(32));
assert.equal(saved.get(pending).name,'上传中的名字','a name confirmed before upload completion follows its job');
const cancel=create();cancel.reconCancelling=true;cancel.starNameDraft='禁止晚到提交';cancel.saveStarName();assert.equal(cancel.starNameKept,false);
const still=create();still.motion=false;still.starNameDraft='静夜';const count=animations.length;
still.saveStarName();assert.equal(still.starNameEditorPresence,0);assert.equal(still.starNameLabelPresence,1);
still.editStarName();assert.equal(still.starNameEditorPresence,1);assert.equal(still.starNameLabelPresence,0);
assert.equal(animations.length,count,'reduced motion has no delays or movement');
for(let i=0;i<50;i++){
  still.starNameDraft='星辰 '+i;still.saveStarName();still.editStarName();
}
assert.equal(still.keptStarName,'星辰 49');assert.equal(still.starNameKept,false);
still.clearStarNameFocus();error.clearStarNameFocus();uploading.clearStarNameFocus();
assert.equal(timers.size,0);
const restored=create();restored.setStarNameKept(true,false);
assert.equal(restored.starNameEditorPresence,0);assert.equal(restored.starNameLabelPresence,1);

const skyTs=skySource.slice(0,skySource.indexOf('  build(){'))+'}\nmodule.exports=NightSkySurface;';
const skyJs=(await transform(skyTs.replace(/^import .*;\r?\n/gm,'').replace('@Component','')
  .replace('export struct NightSkySurface','class NightSkySurface').replace(/@Prop\s+/g,''),{loader:'ts',format:'cjs'})).code;
const skyModule={exports:{}};
new Function('module','exports','CanvasRenderingContext2D','RenderingContextSettings','Date',skyJs)(skyModule,skyModule.exports,function(){return {};},function(){},{now:()=>now});
const s=new skyModule.exports();s.phaseMode='forming';s.nameKept=true;s.orbTime=11;s.orbVelocity=4;s.advanceNameFormation();
for(let i=0;i<32;i++){now+=33;s.advanceNameFormation();}
assert.equal(s.nameGather,1);assert.equal(s.orbTime,11);assert.equal(s.orbVelocity,4);
s.nameKept=false;now+=33;s.advanceNameFormation();const reversing=s.nameGather;
assert.ok(reversing>0&&reversing<1);s.nameKept=true;now+=33;s.advanceNameFormation();assert.ok(s.nameGather>reversing);
s.nameKept=false;for(let i=0;i<20;i++){now+=33;s.advanceNameFormation();}assert.equal(s.nameGather,0);
s.motion=false;s.nameKept=true;s.advanceNameFormation();assert.equal(s.nameGather,1);
s.nameKept=false;s.advanceNameFormation();assert.equal(s.nameGather,0);
console.log('PASS: repeated rename, save failure/retry, blank/double taps, upload handoff, completion during edit, focus cleanup, cancellation guard, reduced motion, reversible particles, independent ring physics');

// Capture the actual ArkUI declarations in a minimal offline tree adapter. This
// checks the production hierarchy/attributes, not a separately hand-written mock.
const formingAt=pageSource.indexOf("if(this.journey==='forming'){",pageSource.indexOf('@Builder nightHome()'));
const uiStart=pageSource.indexOf('        Button({type:ButtonType.Normal,stateEffect:false}){',formingAt);
const uiEnd=pageSource.indexOf("\n      }\n      if(this.journey==='failed'",uiStart);
assert.ok(uiStart>0&&uiEnd>uiStart);
function matching(source,start,open,close){
  let depth=0,quote='';
  for(let i=start;i<source.length;i++){
    const c=source[i];
    if(quote){if(c==='\\'){i++;continue;}if(c===quote)quote='';continue;}
    if(c==='"'||c==="'"||c==='`'){quote=c;continue;}
    if(c===open)depth++;if(c===close&&--depth===0)return i;
  }
  throw Error('Unbalanced UI source');
}
function childrenToCallbacks(source){
  const pattern=/\b(Button|Column|Row|Stack)\(/g;let output='',cursor=0,match;
  while((match=pattern.exec(source))){
    const open=match.index+match[0].length-1,end=matching(source,open,'(',')');
    let body=end+1;while(/\s/.test(source[body]||'!'))body++;
    if(source[body]!=='{')continue;
    const close=matching(source,body,'{','}'),args=source.slice(open+1,end);
    output+=source.slice(cursor,open+1)+args+(args.trim()?',':'')+'()=>{'+childrenToCallbacks(source.slice(body+1,close))+'})';
    cursor=close+1;pattern.lastIndex=cursor;
  }
  return output+source.slice(cursor);
}
const uiCode=(await transform('function build(){'+childrenToCallbacks(pageSource.slice(uiStart,uiEnd))+'}\nreturn build;',
  {loader:'ts',format:'cjs'})).code;
function nativeTree(state){
  const roots=[],stack=[];
  const kinds=['Button','Column','Row','Stack','Text','TextInput','Progress'];
  const creators=kinds.map(kind=>(...args)=>{
    const children=typeof args.at(-1)==='function'?args.pop():null;
    const node={kind,args,attrs:{},children:[]};
    (stack.at(-1)?.children||roots).push(node);
    if(children){stack.push(node);children();stack.pop();}
    const proxy=new Proxy({}, {get:(_,key)=>(...values)=>{node.attrs[key]=values[0];return proxy;}});
    return proxy;
  });
  const enums=['ButtonType','FontWeight','TextAlign','TextOverflow','Color','HitTestMode','EnterKeyType','ProgressType','FlexAlign'];
  const values={Normal:'normal',Medium:500,Center:'center',Ellipsis:'ellipsis',Transparent:'transparent',None:'none',Default:'default',Done:'done',Linear:'linear'};
  new Function(...kinds,...enums,uiCode)(...creators,...enums.map(()=>values)).call(state);
  return roots;
}
function find(nodes,id){for(const n of nodes){if(n.attrs.id===id)return n;const child=find(n.children,id);if(child)return child;}}
const motionState=create();motionState.starNameDraft='晚星';animations.length=0;motionState.saveStarName();
const keepAnimations=animations.splice(0);motionState.editStarName();const editAnimations=animations.splice(0);motionState.clearStarNameFocus();
function easeOut(x){
  if(x<=0)return 0;if(x>=1)return 1;
  let low=0,high=1;
  for(let i=0;i<24;i++){const t=(low+high)/2,bx=3*(1-t)*t*t*.58+t*t*t;if(bx<x)low=t;else high=t;}
  const t=(low+high)/2;return 3*(1-t)*t*t+t*t*t;
}
function sample(tracks,time,initial){
  const values=[...initial];
  for(const track of tracks){
    const t=Math.min(1,Math.max(0,(time-(track.options.delay||0))/track.options.duration));
    track.from.forEach((from,i)=>{if(from!==track.to[i])values[i]=from+(track.to[i]-from)*easeOut(t);});
  }
  return values;
}
// Retarget at multiple intermediate frames, including during the name's delay.
for(const time of [20,80,120,220,400]){
  const rapid=create();rapid.starNameDraft=rapid.keptStarName='随时重新命名';rapid.starNameKept=true;
  [rapid.starNameEditorPresence,rapid.starNameLabelPresence]=sample(keepAnimations,time,[1,0]);
  const before=presenceKeys.map(key=>rapid[key]);animations.length=0;rapid.editStarName();
  assert.deepEqual(sample(animations,0,before),before,'reversing must start at the current visual state');
  assert.deepEqual(sample(animations,400,before),[1,0]);rapid.clearStarNameFocus();
}
const rapid=create();rapid.starNameDraft='连续点击';
for(let i=0;i<50;i++){rapid.saveStarName();rapid.editStarName();}
assert.equal(rapid.starNameKept,false);assert.equal(rapid.starNameEditorPresence,1);
assert.equal(timers.size,1,'only the newest focus request survives rapid renaming');
rapid.journey='revealing';for(const [id,fn] of timers){timers.delete(id);fn();}rapid.clearStarNameFocus();
assert.equal(timers.size,0,'a late focus callback after completion cannot request focus');
const report={environment:'Offline ArkUI declaration adapter + desktop Chromium Canvas; not HarmonyOS runtime',
  logic:'passed',dimensions:[],frames:[],references:['https://fluent2.microsoft.design/motion','https://developer.android.com/reference/com/google/android/material/transition/MaterialFadeThrough']};
const sizes=[[320,480],[390,844],[844,390],[800,1280],[1280,800],[1920,1080]];
for(const [width,height] of sizes){
  const state=create();state.surfaceWidth=width;state.surfaceHeight=height;state.wide=width>=840;
  state.starNameDraft=state.keptStarName='每一面的我都值得被看见这是一颗有很长名字的星辰';
  let anchor;
  for(const kept of [false,true])for(const presence of [0,.15,.5,.85,1]){
    state.starNameKept=kept;state.starNameEditorPresence=presence;state.starNameLabelPresence=1-presence;
    const nodes=nativeTree(state),editor=find(nodes,'star-name-editor'),name=find(nodes,'edit-star-name');
    const footer=nodes.find(node=>find(node.children,'cancel-reconstruction'));
    const geometry=[editor.attrs.position,editor.attrs.width,editor.attrs.height,footer.attrs.position];
    if(anchor)assert.deepEqual(geometry,anchor,'input and footer anchors must not change at any transition frame');else anchor=geometry;
    assert.equal(editor.attrs.position.x+editor.attrs.width/2,width/2);
    assert.equal(editor.attrs.scale.centerX,'50%');assert.equal(editor.attrs.scale.centerY,'50%');
    assert.equal(editor.attrs.translate,undefined,'editor must have no translation');
    assert.equal(name.attrs.translate.x,0);
    assert.ok(name.attrs.position.y+name.attrs.height<=footer.attrs.position.y,'long name cannot cover cancel');
    assert.ok(footer.attrs.position.y+60<=height,'footer stays inside short viewports');
    assert.equal(editor.attrs.hitTestBehavior,kept?'none':'default');
    assert.equal(editor.attrs.accessibilityLevel,kept?'no-hide-descendants':'auto');
    assert.equal(find(nodes,'star-name-input').attrs.focusable,!kept);
    assert.equal(name.attrs.focusable,kept);
  }
  report.dimensions.push({width,height,stableAnchors:true,footerVisible:true,hiddenInputInert:true});
}
// Exercise the production event bindings as well as the methods.
const wired=create();wired.starNameDraft='通过键盘提交';
find(nativeTree(wired),'star-name-input').attrs.onSubmit();assert.equal(wired.starNameKept,true);
find(nativeTree(wired),'star-name-input').attrs.onChange('隐藏输入不应更新');assert.equal(wired.starNameDraft,'通过键盘提交');
find(nativeTree(wired),'edit-star-name').attrs.onClick();assert.equal(wired.starNameKept,false);wired.clearStarNameFocus();
console.log('PASS: 6 viewport sizes × 10 transition states; fixed centers, stable footer, long-name clearance, hidden focus/accessibility, actual event bindings');

// Browser geometry/visual audit of the captured native hierarchy. It does not
// simulate native keyboards, ArkUI rendering/compositing, or device performance.
const browser=await chromium.launch({executablePath:process.env.SELF_CHROME||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
try{
  const page=await browser.newPage();
  async function render(state,gather=1){
    const width=state.surfaceWidth,height=state.surfaceHeight;
    await page.setViewportSize({width,height});
    await page.setContent('<style>*{box-sizing:border-box}body{margin:0;background:#080C1B;color:#F1F4FF;font-family:"Microsoft YaHei",sans-serif}button,input{font:inherit;outline:none;margin:0}canvas{position:absolute;inset:0}#caption{position:absolute;font-weight:500;letter-spacing:2px}#label{position:absolute;left:18px;top:16px;font-size:11px;color:#7386a2}</style><canvas></canvas><div id="ui"></div><div id="caption">每一面的你，都在慢慢靠近。</div><div id="label">离线动效校验 · 桌面渲染</div>');
    await page.evaluate(({nodes,source,width,height,gather,lightY})=>{
      const px=value=>typeof value==='number'?value+'px':value;
      const color=value=>typeof value==='string'&&/^#[a-f\d]{8}$/i.test(value)?'#'+value.slice(3)+value.slice(1,3):value;
      function draw(node){
        const a=node.attrs,kind=node.kind,el=document.createElement(kind==='Button'?'button':kind==='TextInput'?'input':'div');
        if(a.id)el.id=a.id;
        const css={position:a.position?'absolute':'relative',flexShrink:0};
        if(kind==='Column'||kind==='Row'||kind==='Button')Object.assign(css,{display:'flex',flexDirection:kind==='Row'?'row':'column',alignItems:'center',justifyContent:kind==='Button'?'center':'flex-start',gap:px(node.args[0]?.space||0)});
        if(kind==='Text'){el.textContent=node.args[0];css.fontSize='16px';css.lineHeight='1.2';}
        if(kind==='TextInput'){el.value=node.args[0].text;el.placeholder=node.args[0].placeholder;css.padding='0 16px';css.fontSize='16px';}
        if(kind==='Button'){css.border='none';if(typeof node.args[0]==='string')el.textContent=node.args[0];}
        for(const key of ['width','height','fontSize','lineHeight','letterSpacing','borderRadius'])if(a[key]!==undefined)css[key]=px(a[key]);
        if(a.position){css.left=px(a.position.x);css.top=px(a.position.y);}
        if(a.padding){for(const [key,value]of Object.entries(a.padding))css['padding'+key[0].toUpperCase()+key.slice(1)]=px(value);}
        if(a.fontColor)css.color=color(a.fontColor);if(a.fontWeight)css.fontWeight=a.fontWeight;
        if(a.backgroundColor)css.backgroundColor=color(a.backgroundColor);
        if(a.border)css.border=px(a.border.width)+' solid '+color(a.border.color);
        if(a.opacity!==undefined)css.opacity=a.opacity;
        if(a.textAlign)css.textAlign=a.textAlign;
        if(a.textShadow)css.textShadow='0 0 '+px(a.textShadow.radius)+' '+color(a.textShadow.color);
        if(a.blur)css.filter='blur('+px(a.blur)+')';
        if(a.scale)css.transform='scale('+a.scale.x+','+a.scale.y+')';
        if(a.translate)css.transform='translate('+px(a.translate.x||0)+','+px(a.translate.y||0)+')';
        if(a.zIndex)css.zIndex=a.zIndex;
        if(a.maxLines)Object.assign(css,{display:'-webkit-box',WebkitLineClamp:a.maxLines,WebkitBoxOrient:'vertical',overflow:'hidden'});
        if(a.hitTestBehavior==='none')css.pointerEvents='none';
        if(a.accessibilityLevel==='no-hide-descendants')el.setAttribute('aria-hidden','true');
        if(a.focusable===false)el.tabIndex=-1;
        if(kind==='Progress'){
          css.borderRadius='2px';css.background='linear-gradient(to right,#BEDCF4 '+node.args[0].value+'%,#263A54 0)';
        }
        Object.assign(el.style,css);for(const child of node.children)el.append(draw(child));return el;
      }
      for(const node of nodes)document.querySelector('#ui').append(draw(node));
      Object.assign(document.querySelector('#caption').style,{left:(width>=840?50:26)+'px',top:height*(width>=840?.22:.18)+'px',fontSize:(width>=840?27:21)+'px',maxWidth:Math.min(width-48,width>=840?460:340)+'px'});
      const canvas=document.querySelector('canvas');canvas.width=width;canvas.height=height;
      const ctx=canvas.getContext('2d');ctx.width=width;ctx.height=height;
      const module={exports:{}};
      new Function('module','exports','CanvasRenderingContext2D','RenderingContextSettings',source)(module,module.exports,function(){return ctx;},function(){});
      const sky=new module.exports();sky.phaseMode='forming';sky.wasForming=true;sky.orbTime=12;sky.elapsed=12;
      sky.orbImpactIndex=5;sky.orbFirstImpactAt=1.1;sky.orbImpactAt=11.5;sky.orbHeight=1.8;sky.orbVelocity=2;sky.orbImpactStrength=1;
      sky.nameKept=true;sky.nameGather=gather;sky.nameLightY=lightY;sky.prepare();
      sky.ambient(ctx,width,height,12);sky.drawSky(ctx,width,height,12);sky.drawFormationParticles(ctx,width,height);
      sky.drawFormationOrb(ctx,width,height);sky.drawNamedStar(ctx,width,height);
    },{nodes:JSON.parse(JSON.stringify(nativeTree(state))),source:skyJs,width,height,gather,lightY:state.starNameLightY()});
  }
  const state=create();state.starNameDraft=state.keptStarName='晚星';state.starNameKept=true;
  fs.mkdirSync('artifacts/star-naming-offline',{recursive:true});
  let cancelCenter;
  for(const time of [0,80,160,220,380,660]){
    [state.starNameEditorPresence,state.starNameLabelPresence]=sample(keepAnimations,time,[1,0]);
    await render(state,Math.min(1,time/950));
    const box=await page.locator('#star-name-editor').boundingBox(),cancel=await page.locator('#cancel-reconstruction').boundingBox();
    assert.ok(Math.abs(box.x+box.width/2-195)<.02,'rendered input center must remain fixed');
    if(cancelCenter)assert.deepEqual(cancel,cancelCenter);else cancelCenter=cancel;
    const path='artifacts/star-naming-offline/keep-'+time+'.png';await page.screenshot({path});
    report.frames.push({time,editorPresence:state.starNameEditorPresence,namePresence:state.starNameLabelPresence,centerX:box.x+box.width/2,path});
  }
  state.surfaceWidth=1280;state.surfaceHeight=800;state.wide=true;
  state.starNameEditorPresence=0;state.starNameLabelPresence=1;
  await render(state);await page.screenshot({path:'artifacts/star-naming-offline/named-tablet.png'});
  for(const [width,height]of sizes){
    state.surfaceWidth=width;state.surfaceHeight=height;state.wide=width>=840;
    state.keptStarName='每一面的我都值得被看见这是一颗有很长名字的星辰';
    state.starNameEditorPresence=0;state.starNameLabelPresence=1;
    await render(state);
    const label=await page.locator('#edit-star-name').boundingBox(),cancel=await page.locator('#cancel-reconstruction').boundingBox();
    assert.ok(label.y+label.height<=cancel.y,'rendered long name cannot cover cancel');
    assert.ok(cancel.y+cancel.height<=height);
    if(width===320||width===1280||height===390)await page.screenshot({path:`artifacts/star-naming-offline/long-name-${width}x${height}.png`});
  }
  // Reopening reverses the fade while keeping both centers and the footer fixed.
  state.surfaceWidth=390;state.surfaceHeight=844;state.wide=false;state.starNameKept=false;
  for(const time of [0,80,160,280,380]){
    [state.starNameEditorPresence,state.starNameLabelPresence]=sample(editAnimations,time,[0,1]);
    await render(state,Math.max(0,1-time/480));
    const box=await page.locator('#star-name-editor').boundingBox();assert.ok(Math.abs(box.x+box.width/2-195)<.02);
  }
  fs.writeFileSync('artifacts/star-naming-offline/results.json',JSON.stringify(report,null,2));
  console.log('PASS: sampled save/reopen geometry in Chromium, 6 long-name layouts, and actual star/particle Canvas rendering');
}finally{await browser.close();}
