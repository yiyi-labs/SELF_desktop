import {chromium} from 'playwright-core';
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
import {PNG} from 'pngjs';
import {serve} from './serve.mjs';
await fs.mkdir('docs/evidence/browser',{recursive:true});
const server=await serve(4173);
const browser=await chromium.launch({executablePath:process.env.SELF_CHROME||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const page=await browser.newPage({viewport:{width:390,height:720},deviceScaleFactor:2});const errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
const checks=[];
async function check(name,fn){try{const details=await fn();checks.push({name,status:'passed',details});console.log('PASS',name);}catch(e){checks.push({name,status:'failed',error:String(e)});console.error('FAIL',name,e);}}
try{
 await page.goto('http://127.0.0.1:4173');await page.waitForFunction(()=>window.selfTest);
 const glb=Array.from(await fs.readFile('assets/sample-head.glb'));
 await check('GLB byte loading / embedded JPEG / WebGL2',async()=>{await page.evaluate(async bytes=>{await window.selfTest.renderer.loadGLB(new Uint8Array(bytes).buffer);},glb);return await page.evaluate(()=>({renderer:window.selfTest.renderer.renderer.getContext().getParameter(7937),triangles:window.selfTest.renderer.mesh.geometry.index.count/3}));});
 for(const name of ['lip','editable','protectionTest'])await page.evaluate(({name,bytes})=>window.selfTest.renderer.masks.set(name,new Uint8Array(bytes)),{name,bytes:Array.from(await fs.readFile(`assets/${name}.mask`))});
 const png=async()=>Buffer.from(await page.evaluate(async()=>Array.from(await window.selfTest.renderer.exportPNG(390,720))));
 let baseline,current;
 await check('RGBA8 RenderTarget readback / PNG / alpha',async()=>{baseline=await png();await fs.writeFile('docs/evidence/browser/baseline.png',baseline);const p=PNG.sync.read(baseline);assert.equal(p.width,390);assert.ok(p.data.some((v,i)=>i%4===0&&v<180));assert.ok(p.data.every((v,i)=>i%4!==3||v===255));return {bytes:baseline.length,width:p.width,height:p.height};});
 await check('same pipeline zero-operation identity',async()=>{await page.evaluate(()=>window.selfTest.renderer.apply([]));assert.deepEqual(await png(),baseline);});
 await check('actual lip tint changes local pixels / absolute strength repeat',async()=>{await page.evaluate(()=>{const r=window.selfTest.renderer;r.apply([{id:'lip-test',mask:r.masks.get('lip'),color:[.66,.12,.3],strength:.45}]);});current=await png();await fs.writeFile('docs/evidence/browser/lip-tint.png',current);const a=PNG.sync.read(baseline).data,b=PNG.sync.read(current).data;let changed=0;for(let i=0;i<a.length;i+=4)if(a[i]!==b[i]||a[i+1]!==b[i+1]||a[i+2]!==b[i+2])changed++;assert.ok(changed>20&&changed<10000,`Changed pixels ${changed}`);await page.evaluate(()=>{const r=window.selfTest.renderer;r.apply(r.operations);});assert.deepEqual(await png(),current);return {changedPixels:changed};});
 await check('comparison does not crop export',async()=>{await page.evaluate(()=>{const r=window.selfTest.renderer;r.setTool('COMPARE');r.compare=.2;r.render();});assert.deepEqual(await png(),current);await page.evaluate(()=>window.selfTest.renderer.endCompare());});
 await check('surface picking returns UV',async()=>{const hit=await page.evaluate(()=>{const h=window.selfTest.renderer.pick({x:195,y:360});return h?.uv?{u:h.uv.x,v:h.uv.y}:null;});assert.ok(hit&&hit.u>0&&hit.u<1&&hit.v>0&&hit.v<1);return hit;});
 await check('bidirectional MessagePort text and all-byte binary',async()=>{
  return await page.evaluate(async()=>{const channel=new MessageChannel(),events=[];channel.port1.onmessage=e=>events.push(e.data);window.postMessage('SELF_PORT_V1','*',[channel.port2]);await new Promise(r=>setTimeout(r,30));const base={schemaVersion:1,sessionId:'test',assetId:'sample-lee',assetVersion:'v1',requestId:'t1',revision:0};const send=(type,payload)=>channel.port1.postMessage(JSON.stringify({...base,type,payload}));send('INIT',{});send('ECHO',{text:'中文 "quoted" \u0000 end'});const bytes=Uint8Array.from({length:65539},(_,i)=>i%256);send('TRANSFER_BEGIN',{transferId:'test_bytes',sessionId:'test',assetId:'sample-lee',assetVersion:'v1',revision:0,kind:'echo',length:bytes.length});channel.port1.postMessage(bytes.buffer.slice(0,65536));channel.port1.postMessage(bytes.buffer.slice(65536));send('TRANSFER_END',{transferId:'test_bytes'});await new Promise(r=>setTimeout(r,200));const chunks=events.filter(e=>e instanceof ArrayBuffer),binary=new Uint8Array(chunks.reduce((n,b)=>n+b.byteLength,0));let offset=0;for(const b of chunks){binary.set(new Uint8Array(b),offset);offset+=b.byteLength;}const echo=events.filter(e=>typeof e==='string').map(e=>JSON.parse(e)).find(e=>e.type==='ECHO_RESULT');if(binary.length!==65539||binary.some((v,i)=>v!==i%256)||echo?.payload.text!=='中文 "quoted" \u0000 end')throw Error('Round trip damaged');channel.port1.close();return {bytes:binary.byteLength,chunks:chunks.length,text:echo.payload.text};});
 });
 await page.screenshot({path:'docs/evidence/browser/viewport-390x720.png'});
 await check('second viewport / resize',async()=>{await page.setViewportSize({width:430,height:932});await page.waitForTimeout(100);await page.screenshot({path:'docs/evidence/browser/viewport-430x932.png'});return {width:430,height:932};});
 await check('GPU errors absent',async()=>{assert.deepEqual(errors,[]);assert.equal(await page.evaluate(()=>window.selfTest.renderer.renderer.getContext().getError()),0);});
}finally{
 await fs.writeFile('docs/evidence/browser/results.json',JSON.stringify({environment:'Desktop Chrome, headless SwiftShader; NOT HarmonyOS emulator',date:new Date().toISOString(),browser:browser.version(),checks,errors},null,2));await browser.close();server.close();
}
if(checks.some(c=>c.status==='failed'))process.exitCode=1;
