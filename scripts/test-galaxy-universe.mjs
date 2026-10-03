// Real browser/WebGL presentation checks. Uses a synthetic PLY, never a user's model data.
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {chromium} from 'playwright-core';

const out=path.resolve('artifacts/galaxy-review');await fs.mkdir(out,{recursive:true});
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,
  args:['--use-gl=angle','--use-angle=swiftshader','--enable-webgl']});
const errors=[],messages=[],requests=[];
const page=await browser.newPage({viewport:{width:832,height:1248},deviceScaleFactor:2});
page.on('pageerror',error=>errors.push(String(error)));
page.on('console',message=>{if(message.text().startsWith('SELF_GALAXY_'))messages.push(message.text());});
const view={schemaVersion:1,target:[0,0,0],camera:[0,0,4],up:[0,1,0]};
const names=['外婆','新的我','我的样子','未命名的星辰','很久以前的那个晴天','未命名的星辰'];
const records=count=>Array.from({length:count},(_,index)=>({id:(index+1).toString(16).padStart(32,'0'),
  name:names[index%names.length],view,ready:index<3}));
const properties=['x','y','z','f_dc_0','f_dc_1','f_dc_2','opacity','scale_0','scale_1','scale_2','rot_0','rot_1','rot_2','rot_3'];
const header=Buffer.from('ply\nformat binary_little_endian 1.0\nelement vertex 160\n'+properties.map(p=>'property float '+p+'\n').join('')+'end_header\n');
const data=Buffer.alloc(160*properties.length*4);
for(let i=0;i<160;i++){
  const angle=i*.42,r=.1+Math.sqrt(i/160)*.5;
  const values=[Math.cos(angle)*r,Math.sin(angle)*r*.7,Math.sin(angle*.8)*.2,.3,.5,.7,1.5,-3.8,-3.8,-3.8,1,0,0,0];
  values.forEach((value,j)=>data.writeFloatLE(value,(i*properties.length+j)*4));
}
const ply=Buffer.concat([header,data]);let failAssets=false;
await page.route('https://self.local/**',async route=>{
  const pathname=new URL(route.request().url()).pathname;
  if(pathname==='/galaxies.json')return route.fulfill({json:{items:records(13)}});
  if(/^\/galaxy-assets\/memory-galaxy(?:-blue|-violet)?\.png$/.test(pathname))return route.fulfill({contentType:'image/png',body:await fs.readFile('viewer-gs/assets/'+path.basename(pathname))});
  if(pathname.startsWith('/galaxy/')){
    requests.push(pathname);return route.fulfill({status:failAssets?503:200,contentType:'application/octet-stream',body:failAssets?'unavailable':ply});
  }
  const file=pathname==='/index.html'?'viewer-gs/universe.html':pathname==='/gs-universe.js'?'entry/src/main/resources/rawfile/gs-universe.js':null;
  return route.fulfill(file?{contentType:pathname.endsWith('.js')?'text/javascript':'text/html',body:await fs.readFile(file)}:{status:404,body:''});
});
const boxes=()=>page.locator('.galaxy-name').evaluateAll(nodes=>nodes.filter(node=>getComputedStyle(node).visibility==='visible').map(node=>{
  const r=node.getBoundingClientRect();return {name:node.textContent,x:r.x,y:r.y,width:r.width,height:r.height,selected:node.classList.contains('chosen')};
}));
const checkLabels=async()=>{
  // Software WebGL and a concurrent native build can delay frames. Wait for the
  // camera to settle instead of assuming a wall-clock delay equals animation time.
  await page.waitForFunction(()=>{
    const node=document.querySelector('.galaxy-name.chosen');
    if(!node||getComputedStyle(node).visibility!=='visible')return false;
    const r=node.getBoundingClientRect(),x=(r.x+r.width/2)/innerWidth,y=r.y/innerHeight;
    return x>.23&&x<.38&&y>.65;
  },null,{timeout:10000});
  const labels=await boxes();assert.ok(labels.length>0&&labels.length<=5);assert.ok(labels.some(label=>label.selected));
  const chosen=labels.find(label=>label.selected),viewport=page.viewportSize();
  assert.ok((chosen.x+chosen.width/2)/viewport.width>.23&&(chosen.x+chosen.width/2)/viewport.width<.38,'selected galaxy is misaligned at device pixel ratio 2');
  assert.ok(chosen.y/viewport.height>.65,'selected memory must remain in the lower left');
  for(let i=0;i<labels.length;i++)for(let j=i+1;j<labels.length;j++){
    const a=labels[i],b=labels[j];assert.ok(a.x+a.width<=b.x||b.x+b.width<=a.x||a.y+a.height<=b.y||b.y+b.height<=a.y,'labels overlap');
  }
  return labels;
};
try{
  await page.goto('https://self.local/index.html');
  await page.waitForFunction(()=>document.querySelectorAll('.galaxy-name').length===13);
  await page.waitForTimeout(2200);
  assert.ok(messages.some(line=>line.startsWith('SELF_GALAXY_ASSET_READY')),'real splats did not load');
  const portrait=await checkLabels();await page.screenshot({path:path.join(out,'portrait.png')});
  await page.setViewportSize({width:1366,height:900});await page.waitForTimeout(1600);
  const landscape=await checkLabels();await page.screenshot({path:path.join(out,'landscape.png')});
  await page.setViewportSize({width:390,height:844});await page.waitForTimeout(1000);
  const phone=await checkLabels();await page.screenshot({path:path.join(out,'phone.png')});
  await page.setViewportSize({width:832,height:1248});await page.waitForTimeout(900);
  const nextLabel=page.locator('.galaxy-name:not(.chosen)').filter({visible:true}).first();
  const backgroundSampling=page.evaluate(()=>new Promise(resolve=>{
    const samples=[];
    const timer=setInterval(()=>{
      const c=document.getElementById('stars'),ctx=c.getContext('2d');
      const bytes=ctx.getImageData(Math.round(c.width*.3),Math.round(c.height*.3),30,30).data;
      const rgb=[0,0,0];for(let i=0;i<bytes.length;i+=4)for(let channel=0;channel<3;channel++)rgb[channel]+=bytes[i+channel]/900;
      samples.push(rgb);if(samples.length===26){clearInterval(timer);resolve(samples);}
    },100);
  }));
  await nextLabel.click();await page.waitForTimeout(2100);await checkLabels();
  const backgroundSamples=await backgroundSampling;
  assert.ok(backgroundSamples[0].reduce((sum,value,index)=>sum+Math.abs(value-backgroundSamples.at(-1)[index]),0)>1,'background theme did not change');
  assert.ok(backgroundSamples.slice(1).every((sample,index)=>sample.every((value,channel)=>Math.abs(value-backgroundSamples[index][channel])<5)),'background theme changed abruptly');
  assert.match(await page.locator('.galaxy-name.chosen small').textContent(),/02 \/ 13/);
  await page.setViewportSize({width:390,height:844});await page.waitForTimeout(600);
  await page.locator('#universe').focus();await page.keyboard.press('ArrowDown');await page.waitForTimeout(2100);
  assert.match(await page.locator('.galaxy-name.chosen small').textContent(),/01 \/ 13/);
  await page.mouse.move(300,320);await page.mouse.down();await page.mouse.move(40,650,{steps:20});await page.mouse.up();
  await page.waitForTimeout(2100);await checkLabels();
  assert.match(await page.locator('.galaxy-name.chosen small').textContent(),/02 \/ 13/);
  await page.evaluate(items=>window.selfGalaxy.sync({items}),records(200));
  await page.evaluate(()=>window.selfGalaxy.goTo((199).toString(16).padStart(32,'0')));
  await page.waitForTimeout(3500);await checkLabels();
  assert.match(await page.locator('.galaxy-name.chosen small').textContent(),/199 \/ 200/);
  await page.evaluate(items=>window.selfGalaxy.sync({items}),records(13));
  await page.evaluate(()=>window.selfGalaxy.goTo('00000000000000000000000000000001'));
  await page.waitForTimeout(2300);
  await page.evaluate(()=>window.selfGalaxy.travelTo('00000000000000000000000000000001'));
  await page.waitForTimeout(1100);await page.screenshot({path:path.join(out,'approach.png')});
  await page.waitForFunction(()=>document.body.classList.contains('travelling'));
  await page.waitForTimeout(2500);
  assert.equal(messages.filter(line=>line==='SELF_GALAXY_APPROACH_COMPLETE 00000000000000000000000000000001').length,1);
  await page.screenshot({path:path.join(out,'crossing.png')});
  await page.evaluate(()=>window.selfGalaxy.cancelTravel());await page.waitForTimeout(2300);await checkLabels();
  await page.evaluate(()=>window.selfGalaxy.configure({motion:false,language:'en'}));
  await page.evaluate(()=>window.selfGalaxy.travelTo('00000000000000000000000000000001'));
  await page.waitForTimeout(500);assert.equal(messages.filter(line=>line.startsWith('SELF_GALAXY_APPROACH_COMPLETE')).length,2);
  await page.evaluate(()=>window.selfGalaxy.cancelTravel());
  await page.evaluate(()=>window.selfGalaxy.sync({items:[]}));await page.waitForTimeout(500);
  assert.equal(await page.locator('.galaxy-name').count(),0);
  failAssets=true;const before=requests.length;
  await page.evaluate(items=>window.selfGalaxy.sync({items}),records(1));await page.waitForTimeout(2500);
  assert.equal(requests.length-before,1,'failed assets must not retry every frame');await checkLabels();
  assert.equal(errors.length,0,errors.join('\n'));
  const result={passed:true,portrait,landscape,phone,backgroundSamples,checks:['13 memories','200 memories','label collisions','DPR 2 alignment','WebGL PLY rendering','continuous background colour','label click','keyboard','pointer drag','approach handshake','cancel','reduced motion','empty history','failed asset retry budget'],messages};
  await fs.writeFile(path.join(out,'report.json'),JSON.stringify(result,null,2));console.log(JSON.stringify({passed:true,checks:result.checks,out}));
}catch(error){
  await page.screenshot({path:path.join(out,'failed-browser-check.png')}).catch(()=>{});
  console.error(JSON.stringify({error:String(error),errors,messages,labels:await boxes()}));process.exitCode=1;
}
finally{await browser.close();}
