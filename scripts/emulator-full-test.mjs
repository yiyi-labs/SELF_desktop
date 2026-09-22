import fs from 'node:fs/promises';import {execFileSync} from 'node:child_process';import {PNG} from 'pngjs';import assert from 'node:assert/strict';import {connect} from './cdp.mjs';
const hdc=process.env.SELF_HDC||'C:/Program Files/Huawei/DevEco Studio/sdk/default/openharmony/toolchains/hdc.exe';
const targets=execFileSync(hdc,['list','targets'],{encoding:'utf8'}).trim().split(/\s+/).filter(x=>x&&x!=='[Empty]');const device=process.env.SELF_DEVICE||(targets.length===1?targets[0]:'');if(!device)throw Error('Set SELF_DEVICE to one connected emulator');
const h=(...a)=>execFileSync(hdc,['-t',device,...a],{encoding:'utf8'}),dir='docs/evidence/emulator-full',privateRoot='/data/app/el2/100/base/com.self.mirror/haps/entry';await fs.mkdir(dir,{recursive:true});
const pause=ms=>new Promise(r=>setTimeout(r,ms));const checks=[];let c,pid,remote;
const logs=()=>h('shell','hilog','-x','-e','SELF').split('\n').filter(l=>new RegExp(`\\s${pid}\\s`).test(l)).join('\n');
function nodes(n){return [n,...(n.children||[]).flatMap(nodes)];}
async function layout(){h('shell','uitest','dumpLayout','-b','com.self.mirror','-p','/data/local/tmp/self-layout.json');h('file','recv','/data/local/tmp/self-layout.json',`${process.cwd()}/${dir}/layout.json`);return JSON.parse(await fs.readFile(`${dir}/layout.json`));}
async function click(text){for(let attempt=0;attempt<6;attempt++){const n=nodes(await layout()).find(n=>n.attributes?.text===text);if(n){const b=n.attributes.bounds.match(/\d+/g).map(Number),y=Math.round((b[1]+b[3])/2);if(y>180&&y<2620&&b[3]>b[1]){h('shell','uitest','uiInput','click',String(Math.round((b[0]+b[2])/2)),String(y));await pause(450);return;}}h('shell','uitest','uiInput','swipe','600','2000','600','650','500');await pause(250);}throw Error('Native control unavailable: '+text);}
async function screenshot(name){h('shell','uitest','screenCap','-p',`/data/local/tmp/self-${name}.png`);h('file','recv',`/data/local/tmp/self-${name}.png`,`${process.cwd()}/${dir}/${name}.png`);}
async function check(name,f){try{checks.push({name,status:'passed',details:await f()});console.log('PASS',name);}catch(e){checks.push({name,status:'failed',error:String(e)});console.log('FAIL',name,String(e));}}
async function waitLog(fragment,previous=0){for(let i=0;i<30;i++){const found=logs().split(fragment).length-1;if(found>previous)return;await pause(200);}throw Error('Timed out: '+fragment);}
async function exportCurrent(filename){const count=logs().split('SELF_EXPORT_SAVED').length-1;const j=nodes(await layout());if(j.some(n=>n.attributes?.text==='导出 PNG'))await click('导出 PNG');else{await click('工具');await click('保存当前画面 PNG');}await waitLog('SELF_EXPORT_SAVED',count);h('file','recv',privateRoot+'/files/self-export.png',`${process.cwd()}/${dir}/${filename}`);return await fs.readFile(`${dir}/${filename}`);}
let baseline,edited,createdId;
try{
 pid=h('shell','pidof','com.self.mirror').trim();assert.match(pid,/^\d+$/);remote=`localabstract:webview_devtools_remote_${pid}`;
 await waitLog('RENDER_SUCCEEDED');
 const existing=h('fport','ls').split('\n').find(l=>l.includes('tcp:9223 localabstract:webview_devtools_remote_'));if(existing)h('fport','rm','tcp:9223',existing.match(/localabstract:webview_devtools_remote_\d+/)[0]);
 h('fport','tcp:9223',remote);c=await connect();
 await check('actual ArkWeb and chunked 65539-byte native roundtrip',async()=>{await waitLog('SELF_BINARY_ROUNDTRIP true');assert.ok(logs().includes('ECHO_RESULT'));return {device,pid,os:h('shell','param','get','const.product.software.version').trim(),userAgent:(await c.send('Runtime.evaluate',{expression:'navigator.userAgent',returnByValue:true})).result.value,chunkSize:65536,bytes:65539};});
 await screenshot('initial-ui');
 await check('original export available without editing',async()=>{baseline=await exportCurrent('original.png');const p=PNG.sync.read(baseline);assert.equal(p.width,768);assert.equal(p.height,1024);assert.ok(p.data.every((v,i)=>i%4!==3||v===255));return {bytes:baseline.length};});
 await check('candidate does not render; consent commits; undo and redo',async()=>{
  const before=logs().split('RENDER_SUCCEEDED').length-1;await click('工具');await click('建议轻唇色');assert.equal(logs().split('RENDER_SUCCEEDED').length-1,before);await screenshot('consent-ui');
  await click('试一下');await waitLog('RENDER_SUCCEEDED',before);edited=await exportCurrent('lip.png');assert.notDeepEqual(edited,baseline);
  await click('撤销');assert.deepEqual(await exportCurrent('undo.png'),baseline);
  await click('工具');await click('重做');assert.deepEqual(await exportCurrent('redo.png'),edited);
 });
 await check('comparison exports full frame with identical effective pixels',async()=>{await click('对照');assert.deepEqual(await exportCurrent('after-compare.png'),edited);await click('对照');});
 await check('actual closed lasso returns native mask, then local consent',async()=>{
  await click('圈选');const r=(await c.send('Runtime.evaluate',{expression:'JSON.stringify({w:innerWidth,h:innerHeight})',returnByValue:true})).result.value;const {w,h:height}=JSON.parse(r);
  const coords=[[.34,.44],[.41,.44],[.41,.52],[.34,.52],[.34,.44]].map(([x,y])=>[x*w,y*height]);const [x,y]=coords[0];
  await c.send('Input.dispatchMouseEvent',{type:'mousePressed',x,y,button:'left',clickCount:1});for(const [x,y]of coords.slice(1))await c.send('Input.dispatchMouseEvent',{type:'mouseMoved',x,y,buttons:1,button:'left'});await c.send('Input.dispatchMouseEvent',{type:'mouseReleased',x,y,button:'left',clickCount:1});
  await waitLog('SELF_SELECTION_SAVED');const line=logs().match(/SELF_SELECTION_SAVED (region-\d+) (\d+)/);assert.ok(line);h('file','recv',privateRoot+'/cache/'+line[1]+'.mask',`${process.cwd()}/${dir}/selection.mask`);const mask=await fs.readFile(`${dir}/selection.mask`),selected=mask.reduce((n,v)=>n+(v>0?1:0),0);assert.equal(mask.length,1048576);assert.ok(selected>30);
  await click('工具');await click('局部试色');await click('试一下');await screenshot('local-ui');return {selectedTexels:selected,bytes:mask.length};
 });
 await check('current appearance protection survives later color adjustment',async()=>{
  await click('工具');await click('这里别动');await click('本次保留当前效果');const before=await exportCurrent('protected-before.png');
  await click('工具');await click('换一种颜色');assert.deepEqual(await exportCurrent('protected-after.png'),before);return 'whole PNG identical: changed operation lies wholly inside protected lasso';
 });
 await check('save, alter, reopen and delete actual private workspace',async()=>{
  const expected=await exportCurrent('before-save.png');await click('工具');await click('作品与记录');await click('保存当前作品');await waitLog('SELF_WORK_SAVED');createdId=logs().match(/SELF_WORK_SAVED (work-\d+)/)[1];
  h('file','recv',privateRoot+'/files/works/'+createdId+'/workspace.json',`${process.cwd()}/${dir}/saved-workspace.json`);const saved=JSON.parse(await fs.readFile(`${dir}/saved-workspace.json`));assert.ok(saved.snapshots[saved.cursor].operations.length>=2);assert.ok(saved.protection.anchorOperations.length>=2);
  await click('关闭');await click('工具');await click('回到原始');await click('工具');await click('作品与记录');await click('示例面容作品');await pause(500);assert.deepEqual(await exportCurrent('reopened.png'),expected);
  await click('工具');await click('作品与记录');await click('删除作品');assert.ok(!h('shell','ls',privateRoot+'/files/works').includes(createdId));await click('关闭');return {workspace:createdId,actualOperations:saved.snapshots[saved.cursor].operations.length};
 });
 await check('native photo picker cancellation preserves current image',async()=>{const before=await exportCurrent('before-picker.png');await click('工具');await click('选择一张照片');await pause(1500);await screenshot('native-photo-picker');h('shell','uitest','uiInput','keyEvent','Back');
  for(let i=0;i<12;i++){await pause(500);if(!nodes(await layout()).some(n=>n.attributes?.id==='PickerCamera'))break;}
  if(nodes(await layout()).some(n=>n.attributes?.id==='PickerCamera'))throw Error('System picker did not dismiss');
  await click('关闭');assert.deepEqual(await exportCurrent('after-picker.png'),before);});
 await check('background then foreground recovers same export',async()=>{const before=await exportCurrent('before-background.png');h('shell','uitest','uiInput','keyEvent','Home');await pause(500);h('shell','aa','start','-a','EntryAbility','-b','com.self.mirror');await pause(600);assert.deepEqual(await exportCurrent('after-background.png'),before);});
 await screenshot('final-ui');
}finally{await fs.writeFile(`${dir}/hilog.txt`,logs());c?.close();if(remote)h('fport','rm','tcp:9223',remote);await fs.writeFile(`${dir}/results.json`,JSON.stringify({environment:'Actual HAP / ArkUI / ArkWeb in Huawei Phone HarmonyOS API 19 emulator',date:new Date().toISOString(),checks},null,2));}
if(checks.some(c=>c.status==='failed'))process.exitCode=1;
