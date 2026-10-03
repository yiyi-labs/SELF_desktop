// Real PlayCanvas/WebGL draw check for the existing four-splat contract asset.
// It does not alter the shipped viewer or any personal portrait.
import fs from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright-core';

const root = process.cwd();
const output = path.join(root, 'backend', '.sources', 'gs-contract-probe', 'playcanvas');
await fs.mkdir(output, { recursive: true });
const browser = await chromium.launch({
  executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  headless: true,
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-webgl']
});
const page = await browser.newPage({ viewport: { width: 512, height: 512 }, deviceScaleFactor: 1 });
const messages = [];
page.on('console', message => messages.push(`${message.type()}: ${message.text()}`));
page.on('pageerror', error => messages.push(`pageerror: ${error.message}`));
const view = {schemaVersion:1,target:[0,0,1.9],camera:[0,0,-1],up:[0,1,0],
  fovDegrees:45,targetFaceFraction:.5,editableSplats:4,sourceFrame:'synthetic',faceTrackCount:4};
const files = new Map([
  ['/index.html', [path.join(root,'viewer-gs','index.html'), 'text/html']],
  ['/gs-viewer.js', [path.join(root,'entry','src','main','resources','rawfile','gs-viewer.js'), 'text/javascript']],
  ['/portrait.gaussian.ply', [path.join(root,'backend','.sources','gs-contract-probe','anisotropic-occlusion.ply'), 'application/octet-stream']]
]);
await page.route('https://self.local/**', async route => {
  const pathname = new URL(route.request().url()).pathname;
  if (pathname === '/portrait.view.json') {
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(view)});
  } else if (files.has(pathname)) {
    const [file, contentType] = files.get(pathname);
    await route.fulfill({status:200,contentType,body:await fs.readFile(file)});
  } else {
    await route.fulfill({status:404,body:pathname});
  }
});
try {
  await page.goto('https://self.local/index.html', {waitUntil:'load'});
  await page.waitForFunction(() => {
    const status = document.querySelector('#status')?.textContent || '';
    return status.includes('已载入') || status.includes('失败') || status.includes('不可用');
  }, null, {timeout:20000});
  const status = await page.locator('#status').textContent();
  const webgl2 = await page.evaluate(() => !!document.querySelector('#portrait')?.getContext('webgl2'));
  if (!status.includes('已载入 4') || !webgl2) throw Error(`PlayCanvas draw failed: ${status}`);
  await page.evaluate(async () => {
    const channel = new MessageChannel();
    window.__probePort = channel.port1;
    window.__probeCaptures = [];
    channel.port1.onmessage = event => {
      if (typeof event.data !== 'string') return;
      const frame = JSON.parse(event.data);
      if (frame.type === 'READY') channel.port1.postMessage(JSON.stringify({
        schemaVersion:1,type:'INIT',sessionId:'synthetic-probe',assetId:'four-splats',
        assetVersion:1,revision:0
      }));
      if (frame.type === 'GS_CAPTURE') window.__probeCaptures.push(frame.payload.gsView);
    };
    window.postMessage('SELF_PORT_V1','*',[channel.port2]);
  });
  await page.waitForTimeout(700);
  const samples = [];
  for (const [label, drag] of [['front',0],['one-side',75],['other-side',-150]]) {
    if (drag) {
      await page.mouse.move(256,256);
      await page.mouse.down();
      await page.mouse.move(256+drag,256,{steps:12});
      await page.mouse.up();
      await page.waitForTimeout(850);
    }
    const image = path.join(output,`${label}.png`);
    await page.locator('#portrait').screenshot({path:image});
    const before = await page.evaluate(() => window.__probeCaptures.length);
    await page.evaluate(() => window.__probePort.postMessage(JSON.stringify({
      schemaVersion:1,type:'GS_COMMAND',sessionId:'synthetic-probe',assetId:'four-splats',
      payload:{action:'CAPTURE'}
    })));
    await page.waitForFunction(previous => window.__probeCaptures.length > previous, before);
    const snapshot = await page.evaluate(() => window.__probeCaptures.at(-1));
    const raw = await page.evaluate(() => document.querySelector('#portrait').toDataURL('image/png'));
    const rawImage = path.join(output,`${label}-canvas.png`);
    await fs.writeFile(rawImage,Buffer.from(raw.split(',')[1],'base64'));
    const pixels = await page.evaluate(() => {
      const canvas = document.querySelector('#portrait');
      const target = document.createElement('canvas'); target.width=64;target.height=64;
      const ctx = target.getContext('2d',{willReadFrequently:true});
      ctx.drawImage(canvas,0,0,64,64);
      const bytes=ctx.getImageData(0,0,64,64).data;
      let visible=0, red=0, blue=0;
      for (let i=0;i<bytes.length;i+=4) if (bytes[i+3]>2) {
        visible++;red+=bytes[i];blue+=bytes[i+2];
      }
      return {visible,meanRed:visible?red/visible:0,meanBlue:visible?blue/visible:0};
    });
    samples.push({label,image,rawImage,snapshot,...pixels});
  }
  if (samples.some(sample => sample.visible < 10)) throw Error('WebGL canvas has no visible splats');
  const report = {playcanvas:'2.22.4',webgl2,status,samples,
    sourceAsset:'backend/.sources/gs-contract-probe/anisotropic-occlusion.ply',
    note:'real Chrome WebGL draw with bundled production viewer; same synthetic asset, not HarmonyOS verification',messages};
  await fs.writeFile(path.join(output,'report.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify({webgl2,status,samples}));
} catch (error) {
  console.error(JSON.stringify({error:String(error),messages}));
  process.exitCode=1;
} finally {
  await browser.close();
}
