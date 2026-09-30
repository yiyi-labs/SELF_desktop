// Isolated actual PlayCanvas 2.22.4. No production viewer or asset writes.
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import { chromium } from 'playwright-core';
import { build } from 'esbuild';
const root=process.cwd();
const out=path.resolve(process.argv[2] ?? (()=>{throw Error('explicit isolated audit directory required')})());
const conf=JSON.parse(await fs.readFile(path.join(out,'display.json'),'utf8'));
let attempt=1;let dir;for(;;attempt++){dir=path.join(out,'playcanvas-'+String(attempt).padStart(2,'0'));try{await fs.mkdir(dir);break;}catch(e){if(e.code!=='EEXIST')throw e;}}
const entry=`import * as pc from 'playcanvas';
const spec=await (await fetch('/config.json')).json();
const canvas=document.querySelector('canvas');canvas.width=spec.width;canvas.height=spec.height;
const app=new pc.Application(canvas,{graphicsDeviceOptions:{antialias:false,alpha:true,preserveDrawingBuffer:true}});
app.graphicsDevice.maxPixelRatio=1;app.setCanvasResolution(pc.RESOLUTION_FIXED,spec.width,spec.height);
const camera=new pc.Entity('fixed-camera');camera.addComponent('camera',{clearColor:new pc.Color(0,0,0,0),nearClip:spec.near,farClip:spec.far,fov:2*Math.atan(spec.height/(2*spec.K[1][1]))*180/Math.PI});
app.root.addChild(camera);camera.setPosition(...spec.camera);camera.lookAt(...spec.target,...spec.up);
camera.camera.calculateProjection=(mat)=>{const {K,width:w,height:h,near:n,far:f}=spec;mat.set([2*K[0][0]/w,0,0,0,0,2*K[1][1]/h,0,0,1-2*K[0][2]/w,2*K[1][2]/h-1,-(f+n)/(f-n),-1,0,0,-2*f*n/(f-n),0]);};
const asset=new pc.Asset('fixed-asset','gsplat',{url:'/asset.ply'},{reorder:false});app.assets.add(asset);
asset.on('load',()=>{const model=new pc.Entity('fixed-gs');model.addComponent('gsplat',{asset});app.root.addChild(model);window.probe={pc,app,camera,asset,model,spec};window.ready=true;});
asset.on('error',e=>{window.failure=String(e);});app.assets.load(asset);app.start();`;
await fs.writeFile(path.join(dir,'entry.js'),entry);
await build({stdin:{contents:entry,resolveDir:root,sourcefile:'isolated-haze-display.js',loader:'js'},bundle:true,external:['node:worker_threads'],format:'esm',outfile:path.join(dir,'bundle.js'),minify:false});
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--use-gl=angle','--use-angle=swiftshader','--enable-webgl']});
const rows=[];
try{
 for(const asset of conf.assets){
  const page=await browser.newPage({viewport:{width:conf.width,height:conf.height},deviceScaleFactor:1});const errors=[];page.on('pageerror',e=>errors.push(String(e)));
  const assetPath=asset.ply.replace('/mnt/c/','C:/').replace('/mnt/d/','D:/');
  await page.route('https://self.local/**',async route=>{const p=new URL(route.request().url()).pathname;
   if(p==='/')await route.fulfill({contentType:'text/html',body:'<style>html,body{margin:0;background:black}canvas{display:block}</style><canvas></canvas><script type="module" src="/bundle.js"></script>'});
   else if(p==='/config.json')await route.fulfill({contentType:'application/json',body:JSON.stringify(conf)});
   else if(p==='/bundle.js')await route.fulfill({contentType:'text/javascript',body:await fs.readFile(path.join(dir,'bundle.js'))});
   else if(p==='/asset.ply')await route.fulfill({contentType:'application/octet-stream',body:await fs.readFile(assetPath)});
   else await route.fulfill({status:404,body:p});});
  await page.goto('https://self.local/');await page.waitForFunction(()=>window.ready||window.failure,null,{timeout:60000});
  if(await page.evaluate(()=>window.failure))throw Error(await page.evaluate(()=>window.failure));
  await page.waitForTimeout(2200);
  const result=await page.evaluate(()=>{
   const {pc,app,camera,asset,model}=window.probe,canvas=document.querySelector('canvas'),gl=app.graphicsDevice.gl;
   const rgba=new Uint8Array(canvas.width*canvas.height*4);gl.readPixels(0,0,canvas.width,canvas.height,gl.RGBA,gl.UNSIGNED_BYTE,rgba);
   let binary='';for(let i=0;i<rgba.length;i+=32768)binary+=String.fromCharCode(...rgba.subarray(i,i+32768));
   return {png:canvas.toDataURL(),raw:btoa(binary),info:{version:pc.version,canvas:[canvas.width,canvas.height],css:[canvas.clientWidth,canvas.clientHeight],maxPixelRatio:app.graphicsDevice.maxPixelRatio,
    gamma:camera.camera.gammaCorrection,toneMapping:camera.camera.toneMapping,exposure:app.scene.exposure,fog:app.scene.fog,postEffects:camera.camera.postEffects.effects.length,
    context:gl.getContextAttributes(),projection:Array.from(camera.camera.projectionMatrix.data),world:Array.from(camera.getWorldTransform().data),count:asset.resource.gsplatData.numSplats,
    resourceType:asset.resource.constructor.name,gsplatSettings:{antiAlias:app.scene.gsplat.antiAlias,dataFormat:app.scene.gsplat.dataFormat,currentRenderer:app.scene.gsplat.currentRenderer,minPixelSize:app.scene.gsplat.minPixelSize,radialSorting:app.scene.gsplat.radialSorting,splatBudget:app.scene.gsplat.splatBudget},unified:model.gsplat.unified,assetHasLod:!!asset.resource.lod,renderer:gl.getParameter(gl.RENDERER)}};
  });
  await fs.writeFile(path.join(dir,asset.label+'.png'),Buffer.from(result.png.split(',')[1],'base64'));
  await fs.writeFile(path.join(dir,asset.label+'.rgba'),Buffer.from(result.raw,'base64'));
  rows.push({asset,info:result.info,errors,engineSha256:crypto.createHash('sha256').update(await fs.readFile(path.join(root,'node_modules/playcanvas/build/playcanvas.mjs'))).digest('hex')});await page.close();
 }
}finally{await browser.close();}
await fs.writeFile(path.join(dir,'report.json'),JSON.stringify({rows,scope:'native_canvas_actual_desktop_swiftshader_not_Harmony',pipeline:'engine_default_colour_no_beautification; transparent_black_clear; premultiplied_raw_GL_RGBA8',sourceContract:conf},null,2));
console.log(JSON.stringify(rows.map(r=>({asset:r.asset.label,info:r.info,errors:r.errors}))));
