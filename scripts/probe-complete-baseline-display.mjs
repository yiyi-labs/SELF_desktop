// Native-canvas desktop draw of explicit private assets. No shipped viewer edits.
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import { chromium } from 'playwright-core';
import { build } from 'esbuild';
const root=process.cwd(),privateRoot=path.join(root,'backend','.sources');
const inside=value=>{const rel=path.relative(privateRoot,path.resolve(value));return rel&&!rel.startsWith('..')&&!path.isAbsolute(rel);};
const [config,out]=process.argv.slice(2).map(value=>path.resolve(value));
if(!config||!out||!inside(config)||!inside(out))throw Error('fresh private config/output required');
const spec=JSON.parse(await fs.readFile(config,'utf8'));
const version=JSON.parse(await fs.readFile(path.join(root,'node_modules','playcanvas','package.json'),'utf8')).version;
if(version!=='2.22.4')throw Error('locked PlayCanvas 2.22.4 required');
for(const asset of spec.assets){
  if(!inside(asset.ply))throw Error('asset outside project private sources');
  const bytes=await fs.readFile(asset.ply);
  if(crypto.createHash('sha256').update(bytes).digest('hex')!==asset.hash)throw Error('asset identity changed');
}
await fs.mkdir(out);
const entry=`import * as pc from 'playcanvas';
const spec=await(await fetch('/config.json')).json();
const canvas=document.querySelector('canvas');canvas.width=spec.width;canvas.height=spec.height;
const app=new pc.Application(canvas,{graphicsDeviceOptions:{antialias:false,alpha:true,preserveDrawingBuffer:true}});
app.graphicsDevice.maxPixelRatio=1;app.setCanvasResolution(pc.RESOLUTION_FIXED,spec.width,spec.height);
const camera=new pc.Entity('fixed-camera');camera.addComponent('camera',{clearColor:new pc.Color(0,0,0,0),nearClip:spec.near,farClip:spec.far,fov:2*Math.atan(spec.height/(2*spec.K[1][1]))*180/Math.PI});
app.root.addChild(camera);camera.setPosition(...spec.camera);camera.lookAt(...spec.target,...spec.up);
camera.camera.calculateProjection=mat=>{const{K,width:w,height:h,near:n,far:f}=spec;mat.set([2*K[0][0]/w,0,0,0,0,2*K[1][1]/h,0,0,1-2*K[0][2]/w,2*K[1][2]/h-1,-(f+n)/(f-n),-1,0,0,-2*f*n/(f-n),0]);};
const asset=new pc.Asset('fixed-asset','gsplat',{url:'/asset.ply'},{reorder:false});app.assets.add(asset);
asset.on('load',()=>{const model=new pc.Entity('fixed-gs');model.addComponent('gsplat',{asset});app.root.addChild(model);window.probe={pc,app,camera,asset,model};window.ready=true;});
asset.on('error',error=>window.failure=String(error));app.assets.load(asset);app.start();`;
await fs.writeFile(path.join(out,'entry.js'),entry);
await build({stdin:{contents:entry,resolveDir:root,sourcefile:'complete-baseline-display.js',loader:'js'},bundle:true,
  external:['node:worker_threads'],format:'esm',outfile:path.join(out,'bundle.js'),minify:false});
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,
  args:['--use-gl=angle','--use-angle=swiftshader','--enable-webgl']});
const rows=[];
try{
  for(const asset of spec.assets){
    const page=await browser.newPage({viewport:{width:spec.width,height:spec.height},deviceScaleFactor:1});
    const errors=[];page.on('pageerror',error=>errors.push(String(error)));
    await page.route('**/*',async route=>{
      const url=new URL(route.request().url());
      if(url.hostname!=='self.local')return route.abort();
      const p=url.pathname;
      if(p==='/')await route.fulfill({contentType:'text/html',body:'<style>html,body{margin:0;background:black}canvas{display:block}</style><canvas></canvas><script type="module" src="/bundle.js"></script>'});
      else if(p==='/config.json')await route.fulfill({contentType:'application/json',body:JSON.stringify(spec)});
      else if(p==='/bundle.js')await route.fulfill({contentType:'text/javascript',body:await fs.readFile(path.join(out,'bundle.js'))});
      else if(p==='/asset.ply')await route.fulfill({contentType:'application/octet-stream',body:await fs.readFile(asset.ply)});
      else await route.fulfill({status:404,body:p});
    });
    await page.goto('https://self.local/');
    await page.waitForFunction(()=>window.ready||window.failure,null,{timeout:60000});
    const failure=await page.evaluate(()=>window.failure);if(failure)throw Error(failure);
    await page.waitForTimeout(2200);
    const result=await page.evaluate(()=>{
      const{pc,app,camera,asset,model}=window.probe,canvas=document.querySelector('canvas'),gl=app.graphicsDevice.gl;
      const rgba=new Uint8Array(canvas.width*canvas.height*4);gl.readPixels(0,0,canvas.width,canvas.height,gl.RGBA,gl.UNSIGNED_BYTE,rgba);
      let binary='';for(let i=0;i<rgba.length;i+=32768)binary+=String.fromCharCode(...rgba.subarray(i,i+32768));
      return{png:canvas.toDataURL(),raw:btoa(binary),info:{version:pc.version,canvas:[canvas.width,canvas.height],css:[canvas.clientWidth,canvas.clientHeight],
        gamma:camera.camera.gammaCorrection,toneMapping:camera.camera.toneMapping,exposure:app.scene.exposure,fog:app.scene.fog,
        postEffects:camera.camera.postEffects.effects.length,context:gl.getContextAttributes(),projection:Array.from(camera.camera.projectionMatrix.data),
        world:Array.from(camera.getWorldTransform().data),count:asset.resource.gsplatData.numSplats,unified:model.gsplat.unified,
        settings:{antiAlias:app.scene.gsplat.antiAlias,dataFormat:app.scene.gsplat.dataFormat,minPixelSize:app.scene.gsplat.minPixelSize,radialSorting:app.scene.gsplat.radialSorting},
        renderer:gl.getParameter(gl.RENDERER)}};
    });
    if(errors.length)throw Error(errors.join('\n'));
    await fs.writeFile(path.join(out,asset.label+'.png'),Buffer.from(result.png.split(',')[1],'base64'));
    await fs.writeFile(path.join(out,asset.label+'.rgba'),Buffer.from(result.raw,'base64'));
    rows.push({asset,info:result.info,errors});await page.close();
  }
}finally{await browser.close();}
await fs.writeFile(path.join(out,'report.json'),JSON.stringify({sourceContract:spec,rows,
  scope:'actual desktop SwiftShader draw, NOT HarmonyOS or device FPS',
  scriptSha256:crypto.createHash('sha256').update(await fs.readFile(new URL(import.meta.url))).digest('hex')},null,2));
console.log(JSON.stringify(rows.map(row=>({asset:row.asset.label,points:row.info.count,errors:row.errors}))));
