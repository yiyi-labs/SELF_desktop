// Existing PlayCanvas lasso + reversible digital preview on one unreleased PLY.
// This does not alter product code, publish the asset, or transfer old masks.
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import { chromium } from 'playwright-core';

const root=process.cwd();
const source=path.resolve(process.argv[2]||'');
const fullScene=process.argv.includes('--full-scene');
const projectedRegion=process.argv.includes('--projected-region');
const diagnosticPreserveOrder=process.argv.includes('--preserve-source-order-diagnostic');
const privateRoot=path.join(root,'backend','.sources');
const relative=path.relative(privateRoot,source);
if(!process.argv[2]||!relative||relative.startsWith('..')||path.isAbsolute(relative))
  throw Error('research_source_must_stay_private');
const ply=path.join(source,fullScene?'portrait.gaussian.ply':'research-head-only.gaussian.ply');
const view=JSON.parse(await fs.readFile(path.join(source,'portrait.view.json'),'utf8'));
const hash=crypto.createHash('sha256').update(await fs.readFile(ply)).digest('hex');
const binding=fullScene?{gaussianCount:view.editableSplats+view.recordedEnvironmentSplats,
  bindingNpZSha256:null}:JSON.parse(await fs.readFile(path.join(source,'private-edit-binding.json'),'utf8'));
if(!fullScene&&binding.assetSha256!==hash)throw Error('edit_binding_asset_mismatch');
if(!Number.isSafeInteger(binding.gaussianCount)||binding.gaussianCount<1)
  throw Error('edit_partition_count_invalid');
const out=path.join(source,(fullScene?'edit-compatibility-full-scene-v2':'edit-compatibility-bounded-v2')+
  (diagnosticPreserveOrder?'-loader-diagnostic':''));
await fs.mkdir(out,{recursive:true});
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',
  headless:true,args:['--use-gl=angle','--use-angle=swiftshader','--enable-webgl']});
const context=await browser.newContext({viewport:{width:720,height:1280},deviceScaleFactor:1});
const page=await context.newPage();
const errors=[];
page.on('pageerror',e=>errors.push(String(e)));
const files=new Map([
  ['/index.html',[path.join(root,'viewer-gs','index.html'),'text/html']],
  ['/gs-viewer.js',[path.join(root,'entry','src','main','resources','rawfile','gs-viewer.js'),'text/javascript']],
  ['/portrait.gaussian.ply',[ply,'application/octet-stream']]
]);
await page.route('https://self.local/**',async route=>{
  const pathname=new URL(route.request().url()).pathname;
  if(pathname==='/portrait.view.json')return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(view)});
  if(files.has(pathname)){
    const [file,contentType]=files.get(pathname);
    if(pathname==='/gs-viewer.js'&&diagnosticPreserveOrder){
      const original=await fs.readFile(file,'utf8');
      const needle='"Personal 3DGS","gsplat",{url:"https://self.local/portrait.gaussian.ply"}';
      if(!original.includes(needle))throw Error('diagnostic_loader_constructor_not_found');
      return route.fulfill({status:200,contentType,body:original.replace(needle,needle+',{reorder:false}')});
    }
    return route.fulfill({status:200,contentType,body:await fs.readFile(file)});
  }
  return route.fulfill({status:404,body:pathname});
});
const events=[];
const save=async label=>{
  await page.waitForTimeout(250);
  const dataUrl=await page.evaluate(()=>document.querySelector('#portrait').toDataURL('image/png'));
  const bytes=Buffer.from(dataUrl.split(',')[1],'base64');
  const target=path.join(out,`private-${label}.png`);
  await fs.writeFile(target,bytes);
  return {path:target,sha256:crypto.createHash('sha256').update(bytes).digest('hex')};
};
const command=async payload=>{
  await page.evaluate(value=>window.__editPort.postMessage(JSON.stringify({schemaVersion:1,
    type:'GS_COMMAND',sessionId:'research-edit',assetId:'unreleased-head-edit-contract',payload:value})),payload);
};
let report;
try{
  await page.goto('https://self.local/index.html',{waitUntil:'load'});
  await page.waitForFunction(()=>document.querySelector('#status')?.textContent?.includes('已载入'),null,{timeout:30000});
  await page.evaluate(()=>{
    const channel=new MessageChannel();
    window.__editPort=channel.port1;
    window.__editEvents=[];
    window.__editMaskChunks=[];
    window.__editMask=null;
    window.__editMaskActive=false;
    channel.port1.onmessage=event=>{
      if(typeof event.data!=='string'){
        if(window.__editMaskActive&&event.data instanceof ArrayBuffer)
          window.__editMaskChunks.push(new Uint8Array(event.data));
        return;
      }
      const message=JSON.parse(event.data);
      window.__editEvents.push(message);
      if(message.type==='TRANSFER_BEGIN'&&message.payload?.kind==='gs-mask'){
        window.__editMaskActive=true;
        window.__editMaskChunks=[];
      }
      if(message.type==='TRANSFER_END'&&window.__editMaskActive){
        const count=window.__editMaskChunks.reduce((n,x)=>n+x.length,0);
        const mask=new Uint8Array(count);
        let offset=0;
        for(const chunk of window.__editMaskChunks){mask.set(chunk,offset);offset+=chunk.length;}
        window.__editMask=mask;
        window.__editMaskActive=false;
      }
      if(message.type==='READY')channel.port1.postMessage(JSON.stringify({schemaVersion:1,
        type:'INIT',sessionId:'research-edit',assetId:'unreleased-head-edit-contract',
        assetVersion:1,revision:0}));
    };
    window.postMessage('SELF_PORT_V1','*',[channel.port2]);
  });
  await page.waitForTimeout(600);
  const original=await save('original');
  await command({action:'TOOL',tool:'lasso'});
  let cx=376,cy=761,rx=49,ry=32;
  if(projectedRegion){
    await command({action:'VIEW_SNAPSHOT'});
    await page.waitForFunction(()=>window.__editEvents.some(x=>x.type==='GS_VIEW'),null,{timeout:12000});
    const camera=await page.evaluate(()=>window.__editEvents.findLast(x=>x.type==='GS_VIEW').payload.gsView);
    const bytes=await fs.readFile(ply),end=bytes.indexOf(Buffer.from('end_header\n'))+11;
    const header=bytes.subarray(0,end).toString('ascii');
    const properties=[...header.matchAll(/^property float (\S+)/gm)].map(x=>x[1]);
    const stride=properties.length*4,xyz=['x','y','z'].map(key=>properties.indexOf(key)*4);
    if(!header.includes('format binary_little_endian')||xyz.some(x=>x<0))throw Error('projected_probe_ply_layout_unknown');
    const [qx,qy,qz,qw]=camera.rotation,[px,py,pz]=camera.position;
    const rotation=[1-2*(qy*qy+qz*qz),2*(qx*qy-qz*qw),2*(qx*qz+qy*qw),
      2*(qx*qy+qz*qw),1-2*(qx*qx+qz*qz),2*(qy*qz-qx*qw),
      2*(qx*qz-qy*qw),2*(qy*qz+qx*qw),1-2*(qx*qx+qy*qy)];
    const focal=camera.viewportHeight/(2*Math.tan(camera.fovDegrees*Math.PI/360));
    const points=[];
    for(let i=0;i<view.editableSplats;i++){
      const x=bytes.readFloatLE(end+i*stride+xyz[0])-px,y=bytes.readFloatLE(end+i*stride+xyz[1])-py,
        z=bytes.readFloatLE(end+i*stride+xyz[2])-pz;
      const X=rotation[0]*x+rotation[3]*y+rotation[6]*z,
        Y=-(rotation[1]*x+rotation[4]*y+rotation[7]*z),Z=-(rotation[2]*x+rotation[5]*y+rotation[8]*z);
      const u=focal*X/Z+camera.viewportWidth/2,v=focal*Y/Z+camera.viewportHeight/2;
      if(Z>0&&u>30&&u<camera.viewportWidth-30&&v>30&&v<camera.viewportHeight-30)points.push([u,v]);
    }
    if(points.length<30)throw Error('no_visible_editable_projection');
    const xs=points.map(p=>p[0]).sort((a,b)=>a-b),ys=points.map(p=>p[1]).sort((a,b)=>a-b);
    cx=xs[Math.floor(xs.length*.5)];cy=ys[Math.floor(ys.length*.60)];
    rx=Math.max(30,(xs[Math.floor(xs.length*.9)]-xs[Math.floor(xs.length*.1)])*.20);
    ry=Math.max(22,(ys[Math.floor(ys.length*.9)]-ys[Math.floor(ys.length*.1)])*.10);
  }
  await page.mouse.move(cx+rx,cy);
  await page.mouse.down();
  for(let i=1;i<=48;i++){
    const t=i*Math.PI*2/48;
    await page.mouse.move(cx+rx*Math.cos(t),cy+ry*Math.sin(t));
  }
  await page.mouse.up();
  await page.waitForFunction(()=>window.__editEvents.some(x=>x.type==='GS_SELECTION'||x.type==='GS_FAILED'),null,{timeout:12000});
  const selected=await page.evaluate(()=>window.__editEvents.findLast(x=>x.type==='GS_SELECTION'||x.type==='GS_FAILED'));
  if(selected.type==='GS_FAILED')throw Error(`selection_failed:${JSON.stringify(selected)}`);
  const selectionMask=Buffer.from(await page.evaluate(()=>Array.from(window.__editMask||[])));
  if(selectionMask.length!==binding.gaussianCount)throw Error('selection_mask_asset_length_mismatch');
  await fs.writeFile(path.join(out,'private-selection-mask.bin'),selectionMask);
  await command({action:'APPLY',preset:'rose',strength:.32});
  await page.waitForFunction(()=>window.__editEvents.some(x=>x.type==='GS_APPLIED'&&x.payload?.action==='APPLY'),null,{timeout:12000});
  const changed=await save('changed');
  await command({action:'COMPARE_ORIGINAL'});
  await page.waitForFunction(()=>window.__editEvents.some(x=>x.type==='GS_APPLIED'&&x.payload?.action==='COMPARE_ORIGINAL'),null,{timeout:12000});
  const restored=await save('restored');
  await command({action:'COMPARE_EDIT'});
  await page.waitForFunction(()=>window.__editEvents.some(x=>x.type==='GS_APPLIED'&&x.payload?.action==='COMPARE_EDIT'),null,{timeout:12000});
  const replay=await save('replayed');
  events.push(...await page.evaluate(()=>window.__editEvents.filter(x=>['GS_SELECTION','GS_APPLIED','GS_FAILED'].includes(x.type))));
  report={status:'actual_playcanvas_unreleased_asset_edit_compatibility',plySha256:hash,
    loaderMode:diagnosticPreserveOrder?'isolated_reorder_false_diagnostic':'existing_product',
    assetScope:fullScene?'recorded_person_and_room':'research_head_only',
    selectionProbeRegion:{cx,cy,rx,ry,method:projectedRegion?'actual_editable_points_browser_camera':'historical_fixed_screen_region'},
    editBindingSha256:binding.bindingNpZSha256,original,changed,restored,replay,
    events,browserErrors:errors,
    selectionMaskSha256:crypto.createHash('sha256').update(selectionMask).digest('hex'),
    selectedGaussianCount:selectionMask.reduce((n,v)=>n+(v>0),0),
    selectedEditableCount:selectionMask.subarray(0,view.editableSplats)
      .reduce((n,v)=>n+(v>0),0),
    selectedEnvironmentCount:selectionMask.subarray(view.editableSplats)
      .reduce((n,v)=>n+(v>0),0),
    visualChanged:changed.sha256!==original.sha256,
    exactRestored:restored.sha256===original.sha256,
    exactReplayed:replay.sha256===changed.sha256,
    limits:['Digital rose preview only; no OLAY effect calibration',
      'Existing renderer and lasso, no edit-mask migration across asset versions',
      'Desktop PlayCanvas graphics probe, not HarmonyOS device evidence']};
  await fs.writeFile(path.join(out,'audit.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify({status:report.status,visualChanged:report.visualChanged,
    exactRestored:report.exactRestored,exactReplayed:report.exactReplayed,
    selectedEditableCount:report.selectedEditableCount,
    selectedEnvironmentCount:report.selectedEnvironmentCount,
    events:events.map(x=>({type:x.type,payload:x.payload})),browserErrors:errors}));
}catch(error){
  await fs.writeFile(path.join(out,'failure.json'),JSON.stringify({error:String(error),plySha256:hash,
    loaderMode:diagnosticPreserveOrder?'isolated_reorder_false_diagnostic':'existing_product',
    events:await page.evaluate(()=>window.__editEvents||[]),browserErrors:errors},null,2));
  throw error;
}finally{await context.close();await browser.close();}
