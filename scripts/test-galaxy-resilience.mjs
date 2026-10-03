// Offline fault/interaction checks against the packaged viewer. No native device or backend is used.
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {chromium} from 'playwright-core';

const out=path.resolve('artifacts/galaxy-review');await fs.mkdir(out,{recursive:true});
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,
  args:['--use-gl=angle','--use-angle=swiftshader','--enable-webgl']});
const root='entry/src/main/resources/rawfile',id=n=>n.toString(16).padStart(32,'0');
const view={schemaVersion:1,target:[0,0,0],camera:[0,0,4],up:[0,1,0]};
const records=count=>Array.from({length:count},(_,n)=>({id:id(n+1),name:n%2?'同名的星辰':'<b>那年夏天</b>',view,ready:true}));
const fields=['x','y','z','f_dc_0','f_dc_1','f_dc_2','opacity','scale_0','scale_1','scale_2','rot_0','rot_1','rot_2','rot_3'];
const header=Buffer.from('ply\nformat binary_little_endian 1.0\nelement vertex 80\n'+fields.map(p=>'property float '+p+'\n').join('')+'end_header\n');
const data=Buffer.alloc(80*fields.length*4);
for(let n=0;n<80;n++)[Math.sin(n)*.4,Math.cos(n)*.4,Math.sin(n*.5)*.2,.2,.4,.6,1.5,-4,-4,-4,1,0,0,0]
  .forEach((value,index)=>data.writeFloatLE(value,(n*fields.length+index)*4));
const ply=Buffer.concat([header,data]),errors=[],messages=[],external=[],requests=[];
let delayAssets=0,missingArt=false,manifest={items:records(13)},page;
const checks=[],resourceSamples=[];
try{
  page=await browser.newPage({viewport:{width:832,height:1248},deviceScaleFactor:2});
  page.on('pageerror',error=>errors.push(String(error)));
  page.on('console',line=>{if(line.text().startsWith('SELF_GALAXY_'))messages.push(line.text());});
  // Test-only counters observe resource disposal without exporting production internals.
  await page.addInitScript(()=>{
    const live={buffer:new Set(),texture:new Set(),program:new Set()};
    for(const [kind,name] of [['buffer','Buffer'],['texture','Texture'],['program','Program']]){
      const proto=WebGL2RenderingContext.prototype,create=proto['create'+name],remove=proto['delete'+name];
      proto['create'+name]=function(...args){const object=create.apply(this,args);if(object)live[kind].add(object);return object;};
      proto['delete'+name]=function(object){live[kind].delete(object);return remove.call(this,object);};
    }
    window.galaxyResourceCounts=()=>Object.fromEntries(Object.entries(live).map(([key,set])=>[key,set.size]));
  });
  await page.route('**/*',async route=>{
    const url=new URL(route.request().url()),pathname=url.pathname;
    if(url.origin!=='https://self.local'){external.push(url.href);return route.abort();}
    if(pathname==='/galaxies.json')return route.fulfill({json:manifest});
    if(pathname.startsWith('/galaxy/')){
      requests.push(pathname);
      if(delayAssets)await new Promise(resolve=>setTimeout(resolve,delayAssets));
      return route.fulfill({contentType:'application/octet-stream',body:ply}).catch(()=>{});
    }
    if(pathname.startsWith('/galaxy-assets/')&&missingArt)return route.fulfill({status:404,body:''});
    const file=pathname==='/index.html'?'gs-universe.html':pathname.slice(1);
    if(!/^(gs-universe\.(html|js)|galaxy-assets\/memory-galaxy(?:-blue|-violet)?\.png)$/.test(file))return route.fulfill({status:404,body:''});
    return route.fulfill({contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.png')?'image/png':'text/html',body:await fs.readFile(path.join(root,file))});
  });
  const chosen=()=>page.locator('.galaxy-name.chosen small').textContent();
  const sync=items=>page.evaluate(items=>window.selfGalaxy.sync({items}),items);
  const go=n=>page.evaluate(id=>window.selfGalaxy.goTo(id),id(n));
  await page.goto('https://self.local/index.html');await page.waitForFunction(()=>document.querySelectorAll('.galaxy-name').length===13);
  await page.waitForTimeout(2200);
  assert.equal(await page.locator('.galaxy-name b').count(),0,'memory names must remain plain text');
  checks.push('names treated as text');

  await page.mouse.move(700,400);await page.mouse.down();await page.mouse.move(90,1100,{steps:20});
  await page.locator('#universe').dispatchEvent('pointercancel',{pointerId:1});await page.mouse.up();
  await page.waitForTimeout(2300);
  assert.match(await chosen(),/02 \/ 13/,'cancelled pointer must keep the visible memory and native selection in agreement');
  checks.push('interrupted swipe selection');

  const invalid=[{...records(1)[0],id:'invalid'},{...records(1)[0],id:id(1001),view:{...view,camera:[null,0,1]}},
    {...records(1)[0],id:id(1002),name:'很'.repeat(25)}];
  await sync([...records(205),...invalid,records(1)[0]]);await page.waitForTimeout(400);
  assert.equal(await page.locator('.galaxy-name').count(),200);
  checks.push('invalid and duplicate history; 200-item cap');

  await sync([]);await page.waitForTimeout(600);delayAssets=700;
  const before=messages.length,reqBefore=requests.length;
  await sync(records(200));
  for(const n of [1,15,40,88,110,150,199]){await go(n);await page.waitForTimeout(160);}
  await page.waitForTimeout(4200);delayAssets=0;
  assert.match(await chosen(),/199 \/ 200/);
  const ready=messages.slice(before).filter(line=>line.startsWith('SELF_GALAXY_ASSET_READY'));
  assert.ok(ready.some(line=>line.includes(id(199))),'final nearby model did not load');
  assert.ok(requests.length-reqBefore<=18,'rapid navigation queued an unbounded number of models');
  checks.push('delayed models during rapid distant selection');

  await sync(records(13));await go(1);await page.waitForTimeout(3800);
  for(let cycle=0;cycle<6;cycle++){
    await sync(records(13));await go(cycle%2?7:1);await page.waitForTimeout(950);
    await sync([]);await page.waitForTimeout(450);
    resourceSamples.push(await page.evaluate(()=>window.galaxyResourceCounts()));
  }
  for(const kind of ['buffer','texture','program']){
    const counts=resourceSamples.slice(2).map(sample=>sample[kind]);
    assert.ok(Math.max(...counts)-Math.min(...counts)<=2,`WebGL ${kind}s grow across empty/reload cycles: ${counts}`);
  }
  checks.push('six unload/reload cycles release WebGL resources');

  await sync(records(13));await go(1);await page.waitForTimeout(2400);
  for(let cycle=0;cycle<5;cycle++){
    const before=messages.filter(line=>line.startsWith('SELF_GALAXY_APPROACH_COMPLETE')).length;
    await page.evaluate(id=>window.selfGalaxy.travelTo(id),id(1));await page.waitForTimeout(160+cycle*130);
    await page.evaluate(()=>window.selfGalaxy.cancelTravel());await page.waitForTimeout(450);
    assert.equal(messages.filter(line=>line.startsWith('SELF_GALAXY_APPROACH_COMPLETE')).length,before);
    assert.equal(await page.locator('body.travelling').count(),0);
  }
  await page.waitForTimeout(2200);assert.match(await chosen(),/01 \/ 13/);
  checks.push('five quick flight cancellations');

  await page.evaluate(()=>window.selfGalaxy.configure({motion:false,embedded:true,language:'en'}));
  assert.equal(await page.locator('#hint').isVisible(),false);
  assert.equal(await page.locator('html').getAttribute('lang'),'en');
  for(const viewport of [{width:320,height:640},{width:844,height:390},{width:1920,height:1080}]){
    await page.setViewportSize(viewport);await page.waitForTimeout(250);
    for(const n of [1,4,9,13]){
      await go(n);await page.waitForTimeout(100);
      const box=await page.locator('.galaxy-name.chosen').boundingBox();
      assert.ok(box&&box.x>=0&&box.x+box.width<=viewport.width&&box.y>=0&&box.y+box.height<=viewport.height*.84,
        `selected label clipped in ${viewport.width}x${viewport.height}, memory ${n}`);
    }
  }
  checks.push('small phone, short landscape and desktop labels');

  missingArt=true;manifest={items:records(3)};await page.setViewportSize({width:832,height:1248});
  await page.reload();await page.waitForFunction(()=>document.querySelectorAll('.galaxy-name').length===3,{},{timeout:20000});
  await page.waitForTimeout(2400);assert.match(await chosen(),/01 \/ 03/);
  const painted=await page.locator('#stars').evaluate(canvas=>{
    const data=canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data;
    let vivid=0;for(let n=0;n<data.length;n+=4)if(Math.max(data[n],data[n+1],data[n+2])>65)vivid++;return vivid;
  });
  assert.ok(painted>1000,'procedural fallback has no visible galaxy');
  await page.screenshot({path:path.join(out,'fallback-galaxies.png')});
  checks.push('missing galaxy artwork uses visible fallback');
  assert.deepEqual(external,[],'viewer attempted external network access');assert.deepEqual(errors,[]);
  checks.push('no external network or uncaught browser errors');
  const result={passed:true,checks,resourceSamples,modelRequests:requests.length};
  await fs.writeFile(path.join(out,'resilience-report.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}catch(error){console.error(JSON.stringify({error:String(error),checks,errors,resourceSamples,messages:messages.slice(-12)}));process.exitCode=1;}
finally{await browser.close();}
