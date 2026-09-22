import {chromium} from 'playwright-core';
import fs from 'node:fs/promises';import assert from 'node:assert/strict';import {PNG} from 'pngjs';import {serve} from './serve.mjs';
const dir='docs/evidence/browser';await fs.mkdir(dir,{recursive:true});const server=await serve(4174);
const browser=await chromium.launch({executablePath:process.env.SELF_CHROME||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const page=await browser.newPage({viewport:{width:390,height:720},deviceScaleFactor:2});const checks=[];
const check=async(name,f)=>{try{checks.push({name,status:'passed',details:await f()});console.log('PASS',name);}catch(e){checks.push({name,status:'failed',error:String(e)});console.error('FAIL',name,e);}};
const pixels=async()=>PNG.sync.read(Buffer.from(await page.evaluate(async()=>Array.from(await window.selfTest.renderer.exportPNG(390,720))))).data;
const changed=(a,b)=>{const out=[];for(let i=0;i<a.length;i+=4)if(a[i]!==b[i]||a[i+1]!==b[i+1]||a[i+2]!==b[i+2])out.push(i);return out;};
try{
 await page.goto('http://127.0.0.1:4174');await page.waitForFunction(()=>window.selfTest);
 await page.evaluate(async bytes=>window.selfTest.renderer.loadGLB(new Uint8Array(bytes).buffer),Array.from(await fs.readFile('assets/sample-head.glb')));
 for(const id of ['lip','editable','protectionTest'])await page.evaluate(({id,bytes})=>window.selfTest.renderer.masks.set(id,new Uint8Array(bytes)),{id,bytes:Array.from(await fs.readFile(`assets/${id}.mask`))});
 for(const [rotation,zoom]of [[0,16],[.38,18]])await check(`strict original and current protection at y=${rotation}, z=${zoom}`,async()=>{
  await page.evaluate(({rotation,zoom})=>{const r=window.selfTest.renderer;r.mesh.rotation.y=rotation;r.camera.position.z=zoom;r.apply([]);},{rotation,zoom});const original=await pixels();
  await page.evaluate(()=>{const r=window.selfTest.renderer;r.apply([{id:'probe',mask:r.masks.get('protectionTest'),color:[.8,.1,.2],strength:.6}]);});const anchor=await pixels(),inside=changed(original,anchor);assert.ok(inside.length>20);
  await page.evaluate(()=>{const r=window.selfTest.renderer;r.apply([{id:'full',mask:r.masks.get('editable'),color:[.1,.25,.8],strength:.6}],r.masks.get('protectionTest'));});const originalProtected=await pixels();
  for(const i of inside)assert.deepEqual(originalProtected.subarray(i,i+4),original.subarray(i,i+4));assert.ok(changed(original,originalProtected).length>100);
  await page.evaluate(()=>{const r=window.selfTest.renderer;r.apply(r.operations,r.masks.get('protectionTest'),0,[{id:'anchor',mask:r.masks.get('protectionTest'),color:[.8,.1,.2],strength:.6}]);});const currentProtected=await pixels();
  for(const i of inside)assert.deepEqual(currentProtected.subarray(i,i+4),anchor.subarray(i,i+4));
  return {protectedSamplePixels:inside.length,tolerancePerChannel:0,outsideEditedPixels:changed(original,originalProtected).length};
 });
 await check('operation order is respected and repeat does not accumulate',async()=>{
  await page.evaluate(()=>{const r=window.selfTest.renderer;const m=r.masks.get('lip');r.apply([{id:'red',mask:m,color:[.8,.1,.2],strength:.4},{id:'blue',mask:m,color:[.1,.2,.8],strength:.4}]);});const a=await pixels();
  await page.evaluate(()=>{const r=window.selfTest.renderer;r.apply([...r.operations].reverse());});const b=await pixels();assert.ok(changed(a,b).length>10);
  await page.evaluate(()=>{const r=window.selfTest.renderer;r.apply(r.operations);});assert.deepEqual(await pixels(),b);
 });
 await check('WebGL context restore retains effective pixels',async()=>{
  const before=await pixels();await page.evaluate(()=>{const r=window.selfTest.renderer;window.testContextRestored=false;r.canvas.addEventListener('webglcontextrestored',()=>{window.testContextRestored=true;},{once:true});window.testContextExtension=r.renderer.getContext().getExtension('WEBGL_lose_context');window.testContextExtension.loseContext();});
  await page.waitForTimeout(200);await page.evaluate(()=>window.testContextExtension.restoreContext());await page.waitForFunction(()=>window.testContextRestored&& !window.selfTest.renderer.renderer.getContext().isContextLost());await page.waitForTimeout(200);
  const after=await pixels();const a=new PNG({width:390,height:720});a.data=before;await fs.writeFile(`${dir}/context-before.png`,PNG.sync.write(a));a.data=after;await fs.writeFile(`${dir}/context-after.png`,PNG.sync.write(a));const differences=changed(before,after);assert.equal(differences.length,0,`Restored pixel differences: ${differences.length}`);
 });
 await check('PHOTO plane, clipping lasso, pan/zoom, no horizontal mirror',async()=>{
  const p=new PNG({width:128,height:96});for(let y=0;y<96;y++)for(let x=0;x<128;x++){const i=(y*128+x)*4;p.data.set(x<64?(y<48?[255,0,0,255]:[0,0,255,255]):(y<48?[0,255,0,255]:[255,255,0,255]),i);}
  await fs.writeFile(`${dir}/photo-fixture.png`,PNG.sync.write(p));
  await page.evaluate(async bytes=>{const r=window.selfTest.renderer;await r.loadPhoto(new Uint8Array(bytes),'image/png');},Array.from(PNG.sync.write(p)));
  const data=await pixels();const at=(x,y)=>Array.from(data.subarray((y*390+x)*4,(y*390+x)*4+3));assert.deepEqual(at(120,280),[255,0,0]);assert.deepEqual(at(270,280),[0,255,0]);assert.deepEqual(at(120,440),[0,0,255]);
  const result=await page.evaluate(async()=>{const r=window.selfTest.renderer;r.mesh.position.x=.5;r.camera.position.z=18;r.draw();const mask=await r.select([{x:10,y:150},{x:200,y:150},{x:200,y:570},{x:10,y:570},{x:10,y:150}]);return {length:mask.length,selected:mask.reduce((n,v)=>n+(v>0?1:0),0),kind:r.kind};});assert.equal(result.length,128*96);assert.ok(result.selected>100&&result.selected<128*96);await page.screenshot({path:`${dir}/photo-plane.png`});return result;
 });
 await check('repeated asset replacement releases old GPU resources',async()=>{
  const bytes=Array.from(await fs.readFile(`${dir}/photo-fixture.png`));const counts=await page.evaluate(async bytes=>{const r=window.selfTest.renderer,out=[];for(let i=0;i<8;i++){await r.loadPhoto(new Uint8Array(bytes),'image/png');r.render();await new Promise(resolve=>requestAnimationFrame(resolve));out.push({...r.renderer.info.memory,lost:r.renderer.getContext().isContextLost()});}return out;},bytes);await fs.writeFile(`${dir}/resource-counts.json`,JSON.stringify(counts,null,2));assert.deepEqual(counts.at(-1),counts[1]);assert.equal(counts.at(-1).lost,false);return counts;
 });
 await check('no remote dependency after page has loaded',async()=>{await page.context().setOffline(true);await page.evaluate(()=>{const r=window.selfTest.renderer;r.apply([]);r.render();});assert.ok((await pixels()).length>0);await page.context().setOffline(false);return 'loaded resources, not an offline-first native boot claim';});
}finally{await fs.writeFile(`${dir}/advanced-results.json`,JSON.stringify({environment:'Desktop Chrome SwiftShader; NOT HarmonyOS',date:new Date().toISOString(),checks},null,2));await browser.close();server.close();}
if(checks.some(c=>c.status==='failed'))process.exitCode=1;
