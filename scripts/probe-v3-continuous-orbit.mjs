// One fixed unreleased PLY, one PlayCanvas session, one continuous orbit video.
// No model replacement, refitting, per-view export, or tablet transfer.
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import { chromium } from 'playwright-core';

const root = process.cwd();
const privateRoot = path.join(root, 'backend', '.sources');
const source = path.resolve(process.argv[2] || '');
const fullScene = process.argv.includes('--full-scene');
const smallInteraction = process.argv.includes('--small-interaction');
const relative = path.relative(privateRoot, source);
if (!process.argv[2] || !relative || relative.startsWith('..') || path.isAbsolute(relative)) {
  throw Error('fixed_asset_must_stay_in_private_sources');
}
const ply = path.join(source, fullScene ? 'portrait.gaussian.ply' : 'research-head-only.gaussian.ply');
const view = JSON.parse(await fs.readFile(path.join(source, 'portrait.view.json'), 'utf8'));
const plyBytes = await fs.readFile(ply);
const plySha256 = crypto.createHash('sha256').update(plyBytes).digest('hex');
const out = path.join(source, smallInteraction ? 'continuous-orbit-small' : 'continuous-orbit');
await fs.mkdir(out, { recursive: true });
const browser = await chromium.launch({
  executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  headless: true,
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-webgl']
});
const context = await browser.newContext({
  viewport: { width: 720, height: 1280 }, deviceScaleFactor: 1
});
const page = await context.newPage();
const browserErrors = [];
page.on('pageerror', error => browserErrors.push(String(error)));
const files = new Map([
  ['/index.html', [path.join(root, 'viewer-gs', 'index.html'), 'text/html']],
  ['/gs-viewer.js', [path.join(source, 'research-viewer.js'), 'text/javascript']],
  ['/portrait.gaussian.ply', [ply, 'application/octet-stream']]
]);
await page.route('https://self.local/**', async route => {
  const pathname = new URL(route.request().url()).pathname;
  if (pathname === '/portrait.view.json') {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(view) });
  } else if (files.has(pathname)) {
    const [file, contentType] = files.get(pathname);
    await route.fulfill({ status: 200, contentType, body: await fs.readFile(file) });
  } else {
    await route.fulfill({ status: 404, body: pathname });
  }
});

let samples = [];
let status = '';
const videoFile = path.join(out, 'private-fixed-asset-continuous-orbit.webm');
try {
  await page.goto('https://self.local/index.html', { waitUntil: 'load' });
  await page.waitForFunction(() => {
    const value = document.querySelector('#status')?.textContent || '';
    return value.includes('已载入') || value.includes('失败') || value.includes('不可用');
  }, null, { timeout: 30000 });
  status = await page.locator('#status').textContent();
  if (!status.includes('已载入')) throw Error(status);
  await page.evaluate(() => {
    const channel = new MessageChannel();
    window.__orbitPort = channel.port1;
    window.__orbitViews = [];
    channel.port1.onmessage = event => {
      if (typeof event.data !== 'string') return;
      const frame = JSON.parse(event.data);
      if (frame.type === 'READY') {
        channel.port1.postMessage(JSON.stringify({schemaVersion:1,type:'INIT',
          sessionId:'fixed-orbit',assetId:'unreleased-fixed-asset',assetVersion:1,revision:0}));
      }
      if (frame.type === 'GS_VIEW') window.__orbitViews.push(frame.payload.gsView);
    };
    window.postMessage('SELF_PORT_V1', '*', [channel.port2]);
  });
  const snapshot = async label => {
    const before = await page.evaluate(() => window.__orbitViews.length);
    await page.evaluate(() => window.__orbitPort.postMessage(JSON.stringify({
      schemaVersion:1,type:'GS_COMMAND',sessionId:'fixed-orbit',
      assetId:'unreleased-fixed-asset',payload:{action:'VIEW_SNAPSHOT'}})));
    await page.waitForFunction(count => window.__orbitViews.length > count, before,
      { timeout: 10000 });
    const gsView = await page.evaluate(() => window.__orbitViews.at(-1));
    const raw = await page.evaluate(() => document.querySelector('#portrait').toDataURL('image/png'));
    const rawImage = path.join(out, `private-${label}-canvas.png`);
    await fs.writeFile(rawImage, Buffer.from(raw.split(',')[1], 'base64'));
    samples.push({ label, gsView, rawImage });
  };
  await page.waitForTimeout(700);
  await page.evaluate(() => {
    const canvas = document.querySelector('#portrait');
    const stream = canvas.captureStream(24);
    const chunks = [];
    const recorder = new MediaRecorder(stream, { mimeType: 'video/webm;codecs=vp8' });
    recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
    window.__orbitRecorder = { recorder, chunks };
    recorder.start(250);
  });
  await snapshot('front-start');
  await page.screenshot({path:path.join(out,'private-front-ui.png')});
  const x0 = 360, y = 630;
  await page.mouse.move(x0, y);
  await page.mouse.down();
  const sweep = async (from, to, steps, label) => {
    for (let i = 1; i <= steps; i++) {
      await page.mouse.move(from + (to-from)*i/steps, y);
      await page.waitForTimeout(45);
    }
    await page.waitForTimeout(450);
    await snapshot(label);
  };
  if (smallInteraction) {
    await sweep(x0, x0+26, 18, 'small-yaw-positive-about-12');
    await sweep(x0+26, x0-26, 36, 'small-yaw-negative-about-12');
    await sweep(x0-26, x0, 18, 'front-return');
    for (const [dy,label] of [[17,'small-pitch-positive-about-8'],[-17,'small-pitch-negative-about-8'],[0,'front-pitch-return']]) {
      const current = await page.evaluate(() => window.__smallOrbitY || 0);
      for(let i=1;i<=18;i++) {
        await page.mouse.move(x0,y+current+(dy-current)*i/18);
        await page.waitForTimeout(45);
      }
      await page.evaluate(value => {window.__smallOrbitY=value;},dy);
      await page.waitForTimeout(450);
      await snapshot(label);
    }
  } else {
    await sweep(x0, 491, 18, 'yaw-positive-about-60');
    await sweep(491, 229, 36, 'yaw-negative-about-60');
    await sweep(229, x0, 18, 'front-return');
  }
  await page.mouse.up();
  await page.waitForTimeout(600);
  await snapshot('front-settled');
  const finalSha = crypto.createHash('sha256').update(await fs.readFile(ply)).digest('hex');
  if (finalSha !== plySha256) throw Error('fixed_asset_changed_during_orbit');
  const videoDataUrl = await page.evaluate(async () => {
    const { recorder, chunks } = window.__orbitRecorder;
    const ended = new Promise(resolve => { recorder.onstop = resolve; });
    recorder.stop();
    await ended;
    const blob = new Blob(chunks, { type: 'video/webm' });
    return await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  });
  await fs.writeFile(videoFile, Buffer.from(videoDataUrl.split(',')[1], 'base64'));
} finally {
  await context.close();
  await browser.close();
}
const report = {
  status: 'single_unreleased_asset_real_playcanvas_continuous_orbit',
  assetScope: fullScene ? 'recorded_person_and_room' : 'research_head_only',
  playcanvas: '2.22.4', browserBackend: 'Chrome SwiftShader WebGL2',
  interactionScope:smallInteraction?'small_yaw_and_pitch':'large_yaw',
  sourceAsset: ply, plySha256, sourceView: view,
  video: videoFile,
  videoSha256: crypto.createHash('sha256').update(await fs.readFile(videoFile)).digest('hex'),
  samples, browserErrors,
  limits: [fullScene ? 'One frozen reference person and room; no expression change' :
             'One frozen reference head only; no expression change or room',
    'Continuous orbit is graphics evidence, not truthful unobserved-side geometry',
    'Desktop SwiftShader is not target-device performance evidence']
};
await fs.writeFile(path.join(out, 'audit.json'), JSON.stringify(report, null, 2));
console.log(JSON.stringify({status:report.status,plySha256,samples:samples.map(s =>
  ({label:s.label,yaw:s.gsView.yaw,position:s.gsView.position})),
  video:report.video,videoSha256:report.videoSha256,browserErrors}));
