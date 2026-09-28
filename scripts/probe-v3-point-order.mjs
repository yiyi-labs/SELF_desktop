import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {chromium} from 'playwright-core';
const source=path.resolve(process.argv[2]||'');
const rel=path.relative(path.resolve('backend/.sources'),source);
if(!rel||rel.startsWith('..')||path.isAbsolute(rel))throw Error('private_run_required');
const hash=b=>crypto.createHash('sha256').update(b).digest('hex');
const ply=await fs.readFile(path.join(source,'portrait.gaussian.ply'));
const manifest=JSON.parse(await fs.readFile(path.join(source,'portrait.components.json'),'utf8'));
if(hash(ply)!==manifest.assetSha256||hash(await fs.readFile(path.join(source,'portrait.components.npz')))!==manifest.sidecarSha256)throw Error('identity_hash_failed');
const end=ply.indexOf(Buffer.from('end_header\n'))+11;
const header=ply.subarray(0,end).toString('ascii');
const props=[...header.matchAll(/^property float (\S+)/gm)].map(x=>x[1]);
const n=Number(header.match(/element vertex (\d+)/)[1]);
if(n!==manifest.pointCount)throw Error('point_count_mismatch');
const expected={};for(let j=0;j<props.length;j++){
 const a=new Float32Array(n);for(let i=0;i<n;i++)a[i]=ply.readFloatLE(end+(i*props.length+j)*4);
 expected[props[j]]=hash(Buffer.from(a.buffer));
}
const original=await fs.readFile(path.join(source,'research-viewer.js'),'utf8');
const script=original.replace(/(\w+)\.gsplatData(?=[,;)])/g,'(window.__v3data=$1.gsplatData)');
if(script===original)throw Error('data_access_instrumentation_missing');
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--use-gl=angle','--use-angle=swiftshader','--enable-webgl']});
let report;
try{
 const page=await browser.newPage({viewport:{width:720,height:1280}});
 await page.route('https://self.local/**',async route=>{
  const name=new URL(route.request().url()).pathname;
  if(name==='/gs-viewer.js')return route.fulfill({contentType:'text/javascript',body:script});
  const files={'/index.html':['viewer-gs/index.html','text/html'],'/portrait.gaussian.ply':[path.join(source,'portrait.gaussian.ply'),'application/octet-stream'],'/portrait.view.json':[path.join(source,'portrait.view.json'),'application/json']};
  if(!files[name])return route.fulfill({status:404,body:name});
  return route.fulfill({contentType:files[name][1],body:await fs.readFile(files[name][0])});
 });
 await page.goto('https://self.local/index.html');
 await page.waitForFunction(()=>window.__v3data,null,{timeout:30000});
 const actual=await page.evaluate(async names=>{
  const d=window.__v3data,hashes={};
  for(const name of names){const v=d.getProp(name);if(!v)throw Error('missing_property:'+name);
   const h=await crypto.subtle.digest('SHA-256',v.buffer.slice(v.byteOffset,v.byteOffset+v.byteLength));
   hashes[name]=Array.from(new Uint8Array(h)).map(x=>x.toString(16).padStart(2,'0')).join('');}
  return {count:d.numSplats,hashes};
 },props);
 const mismatches=props.filter(name=>expected[name]!==actual.hashes[name]);
 report={plySha256:hash(ply),sidecarSha256:manifest.sidecarSha256,sourceSha256:manifest.sourceSha256,
  sourceCount:n,loadedCount:actual.count,fields:props.length,mismatches,allFieldsSameOrder:mismatches.length===0&&actual.count===n,
  expected,actual:actual.hashes,loader:'PlayCanvas 2.22.4, reorder:false',drawDepthSorting:'unchanged',
  basis:'all source field arrays, not nearest XYZ or editable-prefix proxy',Harmony:'not_tested'};
 await fs.writeFile(path.join(source,'point-order-v3.json'),JSON.stringify(report,null,2));
 if(!report.allFieldsSameOrder)throw Error('loaded_point_identity_changed');
 console.log(JSON.stringify({allFieldsSameOrder:report.allFieldsSameOrder,fields:props.length,points:n,plySha256:report.plySha256}));
}finally{await browser.close();}
