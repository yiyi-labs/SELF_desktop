import {chromium} from 'playwright-core';
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
import {serve} from './serve.mjs';
const server=await serve(4176);
const browser=await chromium.launch({executablePath:process.env.SELF_CHROME||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--disable-3d-apis']});
const page=await browser.newPage(),errors=[],checks=[];
page.on('pageerror',e=>errors.push(String(e)));
try{
 await page.route('**/renderer.js',route=>route.fulfill({path:'entry/src/main/resources/rawfile/renderer/renderer.js',contentType:'application/javascript'}));
 await page.goto('http://127.0.0.1:4176');
 await page.locator('#status[role=alert]').waitFor();
 assert.match(await page.locator('#status').textContent(),/限制了 3D/);
 assert.equal(await page.evaluate(()=>document.body.classList.contains('still')),true);
 const messages=await page.evaluate(()=>new Promise((resolve,reject)=>{
  const channel=new MessageChannel(),received=[];
  const timer=setTimeout(()=>reject(Error('Bridge timeout')),3000);
  channel.port1.onmessage=e=>{
   const m=JSON.parse(e.data);received.push(m);
   if(m.type==='READY')channel.port1.postMessage(JSON.stringify({schemaVersion:1,type:'INIT',revision:0,sessionId:'test',assetId:'test',assetVersion:'v1',requestId:'init',payload:{}}));
   if(m.type==='RENDER_FAILED'){clearTimeout(timer);channel.port1.close();resolve(received);}
  };
  window.postMessage('SELF_PORT_V1','*',[channel.port2]);
 }));
 assert.equal(messages[0].payload.webgl2,false);
 assert.deepEqual(messages.map(m=>m.type),['READY','RENDER_FAILED']);
 assert.deepEqual(errors,[]);
 assert.equal(await page.evaluate(()=>typeof window.selfTest),'undefined');
 checks.push({status:'passed',name:'Production bundle reports unavailable graphics, keeps bridge alive, rejects INIT, pauses motion, and has no uncaught error or test surface'});
}catch(e){checks.push({status:'failed',error:String(e)});process.exitCode=1;}
finally{await fs.writeFile('docs/evidence/browser/startup-results.json',JSON.stringify({environment:'Desktop Chrome with disabled 3D APIs; NOT HarmonyOS emulator',date:new Date().toISOString(),checks},null,2));await browser.close();server.close();}
console.log(JSON.stringify(checks));
