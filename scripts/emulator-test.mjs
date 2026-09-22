import fs from 'node:fs/promises';import {execFileSync} from 'node:child_process';import {PNG} from 'pngjs';import assert from 'node:assert/strict';import {connect} from './cdp.mjs';
const hdc=process.env.SELF_HDC||'C:/Program Files/Huawei/DevEco Studio/sdk/default/openharmony/toolchains/hdc.exe';
const targets=execFileSync(hdc,['list','targets'],{encoding:'utf8'}).trim().split(/\s+/).filter(x=>x&&x!=='[Empty]');
const device=process.env.SELF_DEVICE||(targets.length===1?targets[0]:'');if(!device)throw Error('Choose exactly one device with SELF_DEVICE');
const h=(...args)=>execFileSync(hdc,['-t',device,...args],{encoding:'utf8'});
const dir='docs/evidence/emulator';await fs.mkdir(dir,{recursive:true});const checks=[];
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function layout(){h('shell','uitest','dumpLayout','-b','com.self.mirror','-p','/data/local/tmp/self-layout.json');h('file','recv','/data/local/tmp/self-layout.json',`${process.cwd()}/${dir}/layout.json`);return JSON.parse(await fs.readFile(`${dir}/layout.json`));}
function nodes(n){return [n,...(n.children||[]).flatMap(nodes)];}
async function click(text){const j=await layout(),n=nodes(j).find(n=>n.attributes?.text===text);if(!n)throw Error(`No native control: ${text}`);const [x1,y1,x2,y2]=n.attributes.bounds.match(/\d+/g).map(Number);h('shell','uitest','uiInput','click',String(Math.round((x1+x2)/2)),String(Math.round((y1+y2)/2)));await pause(500);}
async function capture(name){h('shell','uitest','screenCap','-p',`/data/local/tmp/self-${name}.png`);h('file','recv',`/data/local/tmp/self-${name}.png`,`${process.cwd()}/${dir}/${name}.png`);}
async function check(name,fn){try{checks.push({name,status:'passed',details:await fn()});console.log('PASS',name);}catch(e){checks.push({name,status:'failed',error:String(e)});console.log('FAIL',name,String(e));}}
const logs=()=>h('shell','hilog','-x','-e','SELF');
let c;let forwarding='';
try{
 const pid=h('shell','pidof','com.self.mirror').trim();assert.match(pid,/^\d+$/);
 const socket=h('shell','cat','/proc/net/unix').split('\n').find(l=>l.endsWith(`@webview_devtools_remote_${pid}\r` )||l.trim().endsWith(`@webview_devtools_remote_${pid}`));assert.ok(socket);
 forwarding=`tcp:9223 localabstract:webview_devtools_remote_${pid}`;
 const existing=h('fport','ls').split('\n').find(l=>l.includes('tcp:9223 localabstract:webview_devtools_remote_'));
 if(existing){const remote=existing.match(/localabstract:webview_devtools_remote_\d+/)[0];h('fport','rm','tcp:9223',remote);}
 h('fport','tcp:9223',`localabstract:webview_devtools_remote_${pid}`);await pause(200);c=await connect();
 await check('ArkWeb on actual API 19 emulator',async()=>{return {device,os:h('shell','param','get','const.product.software.version').trim(),runtime:(await c.send('Runtime.evaluate',{expression:'navigator.userAgent',returnByValue:true})).result.value};});
 await check('native ArrayBuffer / Chinese / quotes / NUL roundtrip',async()=>{const l=logs();assert.ok(l.includes('SELF_BINARY_ROUNDTRIP true'));assert.ok(l.includes('ECHO_RESULT'));await fs.writeFile(`${dir}/bridge.log`,l);return {binaryBytes:65539};});
 await capture('baseline-ui');
 await check('native button authorizes actual rendering',async()=>{await click('试一下轻唇色');assert.ok(logs().includes('RENDER_SUCCEEDED'));});
 await check('comparison then full PNG saved by native',async()=>{
  await click('对照');await click('导出 PNG');assert.ok(logs().includes('SELF_EXPORT_SAVED'));
  h('file','recv','/data/app/el2/100/base/com.self.mirror/haps/entry/files/self-export.png',`${process.cwd()}/${dir}/export-after-compare.png`);
  const png=PNG.sync.read(await fs.readFile(`${dir}/export-after-compare.png`));assert.equal(png.width,768);assert.equal(png.height,1024);
  let darkUpper=0;for(let y=60;y<400;y++)for(let x=200;x<568;x++){const i=(y*768+x)*4;if(png.data[i]<200)darkUpper++;}assert.ok(darkUpper>10000,'Expected head in upper/centre area; catch DPR crop regression');
  return {width:png.width,height:png.height,bytes:(await fs.stat(`${dir}/export-after-compare.png`)).size};
 });
 await check('closed screen lasso creates actual native mask',async()=>{
  await click('圈选');
  await c.send('Input.dispatchMouseEvent',{type:'mousePressed',x:146,y:223,button:'left',clickCount:1});
  for(const [x,y]of [[156,219],[169,221],[175,232],[172,245],[160,248],[148,240],[146,223]])await c.send('Input.dispatchMouseEvent',{type:'mouseMoved',x,y,button:'left',buttons:1});
  await c.send('Input.dispatchMouseEvent',{type:'mouseReleased',x:146,y:223,button:'left',clickCount:1});
  for(let i=0;i<20;i++){await pause(500);if(h('shell','ls','/data/app/el2/100/base/com.self.mirror/haps/entry/files').includes('selection.mask'))break;}
  h('file','recv','/data/app/el2/100/base/com.self.mirror/haps/entry/files/selection.mask',`${process.cwd()}/${dir}/selection.mask`);
  const m=await fs.readFile(`${dir}/selection.mask`);assert.equal(m.length,1048576);const n=m.reduce((n,v)=>n+(v>0?1:0),0);assert.ok(n>50&&n<30000);await click('局部试色');return {bytes:m.length,selectedTexels:n};
 });
 await capture('after-selection-ui');
 await check('background and foreground recover',async()=>{h('shell','uitest','uiInput','keyEvent','Home');await pause(500);h('shell','aa','start','-a','EntryAbility','-b','com.self.mirror');await pause(700);const j=await layout();assert.ok(nodes(j).some(n=>n.attributes?.text==='SELF'));});
 await fs.writeFile(`${dir}/final.log`,logs());
}finally{c?.close();await fs.writeFile(`${dir}/results.json`,JSON.stringify({environment:'HarmonyOS phone emulator, actual HAP / ArkUI / ArkWeb',date:new Date().toISOString(),checks},null,2));}
if(checks.some(c=>c.status==='failed'))process.exitCode=1;
