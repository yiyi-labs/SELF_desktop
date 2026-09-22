import {chromium} from 'playwright-core';
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
import {serve} from './serve.mjs';
const server=await serve(4175),browser=await chromium.launch({executablePath:process.env.SELF_CHROME||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const page=await browser.newPage({viewport:{width:390,height:720},deviceScaleFactor:2}),checks=[];
const check=async(name,f)=>{try{checks.push({name,status:'passed',details:await f()});console.log('PASS',name);}catch(e){checks.push({name,status:'failed',error:String(e)});console.error('FAIL',name,e);}};
try{
 await page.goto('http://127.0.0.1:4175');await page.waitForFunction(()=>window.selfTest);
 await page.evaluate(async bytes=>window.selfTest.renderer.loadGLB(new Uint8Array(bytes).buffer),Array.from(await fs.readFile('assets/sample-head.glb')));
 const view=()=>page.evaluate(()=>window.selfTest.renderer.view());
 await check('decorative particles animate outside the face shader',async()=>{
  assert.equal(await page.locator('.particle').count(),18);
  const a=await page.locator('.particle').first().evaluate(n=>getComputedStyle(n).transform);await page.waitForTimeout(200);const b=await page.locator('.particle').first().evaluate(n=>getComputedStyle(n).transform);assert.notEqual(a,b);
  assert.deepEqual(await view(),{yaw:0,pitch:0,distance:16,panX:0,panY:0});
 });
 await check('OS reduced motion freezes active orbit and decorative particles',async()=>{
  await page.evaluate(()=>window.selfTest.renderer.startOrbit());await page.waitForTimeout(500);assert.ok(Math.abs((await view()).yaw)>.001);
  await page.emulateMedia({reducedMotion:'reduce'});await page.waitForFunction(()=>document.body.classList.contains('still'));
  const a=await view();await page.waitForTimeout(250);assert.deepEqual(await view(),a);
  assert.equal(await page.locator('.particle').first().evaluate(n=>getComputedStyle(n).animationPlayState),'paused');
  await page.evaluate(()=>window.selfTest.renderer.startOrbit());await page.waitForTimeout(200);assert.deepEqual(await view(),a);
 });
 await check('manual rotation remains available with reduced motion; lasso prevents rotation',async()=>{
  const before=await view();await page.mouse.move(190,330);await page.mouse.down();await page.mouse.move(280,345);await page.mouse.up();const after=await view();assert.notEqual(after.yaw,before.yaw);
  await page.evaluate(()=>window.selfTest.renderer.setTool('LASSO'));await page.mouse.move(180,320);await page.mouse.down();await page.mouse.move(240,360);await page.mouse.up();assert.deepEqual(await view(),after);
 });
}finally{
 await fs.writeFile('docs/evidence/browser/design-results.json',JSON.stringify({environment:'Desktop Chrome, emulated prefers-reduced-motion; NOT native HarmonyOS accessibility settings',date:new Date().toISOString(),checks},null,2));await browser.close();server.close();
}
if(checks.some(c=>c.status==='failed'))process.exitCode=1;
