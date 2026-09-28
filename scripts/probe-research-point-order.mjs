// Read-only diagnostic on the installed product bundle. Only an accessor is
// instrumented to expose loaded data; no selection or drawing code is changed.
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import { chromium } from 'playwright-core';

const root=process.cwd(),source=path.resolve(process.argv[2]||'');
const relative=path.relative(path.join(root,'backend','.sources'),source);
if(!relative||relative.startsWith('..')||path.isAbsolute(relative))throw Error('private_research_source_required');
const ply=await fs.readFile(path.join(source,'portrait.gaussian.ply'));
const view=JSON.parse(await fs.readFile(path.join(source,'portrait.view.json'),'utf8'));
const bundle=await fs.readFile(path.join(root,'entry/src/main/resources/rawfile/gs-viewer.js'),'utf8');
const exposed=bundle.replace(/(\w+)\.gsplatData(?=[,;)])/g,'(window.__researchPointData=$1.gsplatData)');
if(exposed===bundle)throw Error('data_accessor_not_found');
const headerEnd=ply.indexOf(Buffer.from('end_header\n'))+11;
const properties=[...ply.subarray(0,headerEnd).toString('ascii').matchAll(/^property float (\S+)/gm)].map(x=>x[1]);
const stride=properties.length*4,offsets=['x','y','z'].map(x=>properties.indexOf(x)*4);
const count=Number(ply.subarray(0,headerEnd).toString('ascii').match(/element vertex (\d+)/)[1]);
const original=new Float32Array(count*3);
for(let i=0;i<count;i++)for(let j=0;j<3;j++)original[i*3+j]=ply.readFloatLE(headerEnd+i*stride+offsets[j]);
const signature=(x,y,z)=>[x,y,z].map(v=>Object.is(v,-0)?0:v).join(',');
const ids=new Map();for(let i=0;i<count;i++)ids.set(signature(...original.subarray(i*3,i*3+3)),i);
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,
  args:['--use-gl=angle','--use-angle=swiftshader','--enable-webgl']});
const results=[];
try{
  for(const preserveOrder of [false,true]){
    const page=await browser.newPage({viewport:{width:720,height:1280}});
    const originalConstructor='"Personal 3DGS","gsplat",{url:"https://self.local/portrait.gaussian.ply"}';
    if(!exposed.includes(originalConstructor))throw Error('loader_constructor_not_found');
    const script=preserveOrder?exposed.replace(originalConstructor,originalConstructor+',{reorder:false}'):exposed;
    await page.route('https://self.local/**',async route=>{
      const name=new URL(route.request().url()).pathname;
      if(name==='/portrait.view.json')return route.fulfill({contentType:'application/json',body:JSON.stringify(view)});
      if(name==='/portrait.gaussian.ply')return route.fulfill({contentType:'application/octet-stream',body:ply});
      if(name==='/gs-viewer.js')return route.fulfill({contentType:'text/javascript',body:script});
      if(name==='/index.html')return route.fulfill({contentType:'text/html',body:await fs.readFile(path.join(root,'viewer-gs/index.html'))});
      return route.fulfill({status:404,body:name});
    });
    await page.goto('https://self.local/index.html');
    await page.waitForFunction(()=>document.querySelector('#status')?.textContent?.includes('已载入'),null,{timeout:30000});
    const loaded=await page.evaluate(()=>{
      const data=window.__researchPointData;if(!data)throw Error('loaded_data_unavailable');
      const x=data.getProp('x'),y=data.getProp('y'),z=data.getProp('z'),out=[];
      for(let i=0;i<data.numSplats;i++)out.push(x[i],y[i],z[i]);return out;
    });
    let ordered=0,exactXyzIndexMatches=0,missing=0,editableInPrefix=0,editableOutsidePrefix=0;
    for(let i=0;i<count;i++){
      const originalId=ids.get(signature(...loaded.slice(i*3,i*3+3)));
      if(loaded[i*3]===original[i*3]&&loaded[i*3+1]===original[i*3+1]&&loaded[i*3+2]===original[i*3+2])exactXyzIndexMatches++;
      if(originalId===undefined){missing++;continue;}
      if(originalId===i)ordered++;
      if(originalId<view.editableSplats){if(i<view.editableSplats)editableInPrefix++;else editableOutsidePrefix++;}
    }
    results.push({mode:preserveOrder?'isolated_loader_reorder_false_diagnostic':'existing_product_loader',
      count,editableSplats:view.editableSplats,ordered,exactXyzIndexMatches,missing,editableInPrefix,editableOutsidePrefix,
      loadedXyzSha256:crypto.createHash('sha256').update(Buffer.from(new Float32Array(loaded).buffer)).digest('hex')});
    await page.close();
  }
}finally{await browser.close();}
const report={plySha256:crypto.createHash('sha256').update(ply).digest('hex'),
  originalXyzSha256:crypto.createHash('sha256').update(Buffer.from(original.buffer)).digest('hex'),
  duplicatePositionCount:count-ids.size,
  originalBundleSha256:crypto.createHash('sha256').update(bundle).digest('hex'),results,
  limits:['Accessor instrumentation is isolated; no product file changed',
    'reorder:false is a diagnostic variant, not a product or Harmony pass']};
await fs.writeFile(path.join(source,'point-order-audit.json'),JSON.stringify(report,null,2));
console.log(JSON.stringify(report));
