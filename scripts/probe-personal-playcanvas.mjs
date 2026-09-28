// Isolated computer draw of an unreleased research PLY through SELF's bundled
// PlayCanvas 2.22.4 viewer. This never writes to the app or a tablet.
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import { chromium } from 'playwright-core';

const root = process.cwd();
const defaultSource = path.join(root, 'backend', '.sources', 'quality-geometry-20260926-temp',
  'flame_open_e2_20260927', 'private-optimized-subset-900-footprint-1.00',
  'private-reference-0035-ply-contract');
const privateRoot = path.join(root, 'backend', '.sources');
const source = process.argv[2] ? path.resolve(process.argv[2]) : defaultSource;
const relativeSource = path.relative(privateRoot, source);
if (!relativeSource || relativeSource.startsWith('..') || path.isAbsolute(relativeSource)) {
  throw Error('research_source_must_stay_in_private_sources');
}
const view = JSON.parse(await fs.readFile(path.join(source, 'portrait.view.json'), 'utf8'));
const referenceFrame = Number(/^frame_(\d{4})\.png$/.exec(view.sourceFrame)?.[1]);
if (!Number.isInteger(referenceFrame)) throw Error('invalid_reference_view_contract');
const frameTag = String(referenceFrame).padStart(4, '0');
const ply = path.join(source, 'research-head-only.gaussian.ply');
const out = path.join(source, 'playcanvas');
await fs.mkdir(out, { recursive: true });
const browser = await chromium.launch({
  executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
  headless: true,
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-webgl']
});
const page = await browser.newPage({ viewport: { width: 1080, height: 1920 },
  deviceScaleFactor: 1 });
const messages = [];
page.on('console', message => messages.push(`${message.type()}: ${message.text()}`));
page.on('pageerror', error => messages.push(`pageerror: ${error.message}`));
const files = new Map([
  ['/index.html', [path.join(root, 'viewer-gs', 'index.html'), 'text/html']],
  ['/gs-viewer.js', [path.join(root, 'entry', 'src', 'main', 'resources', 'rawfile', 'gs-viewer.js'), 'text/javascript']],
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
try {
  await page.goto('https://self.local/index.html', { waitUntil: 'load' });
  await page.waitForFunction(() => {
    const status = document.querySelector('#status')?.textContent || '';
    return status.includes('已载入') || status.includes('失败') || status.includes('不可用');
  }, null, { timeout: 30000 });
  const status = await page.locator('#status').textContent();
  const webgl2 = await page.evaluate(() => !!document.querySelector('#portrait')?.getContext('webgl2'));
  if (!status.includes('已载入') || !webgl2) throw Error(`PlayCanvas draw failed: ${status}`);
  await page.evaluate(() => {
    const channel = new MessageChannel();
    window.__probePort = channel.port1;
    window.__probeCapture = null;
    channel.port1.onmessage = event => {
      if (typeof event.data !== 'string') return;
      const frame = JSON.parse(event.data);
      if (frame.type === 'READY') channel.port1.postMessage(JSON.stringify({
        schemaVersion: 1, type: 'INIT', sessionId: 'research-probe',
        assetId: 'unreleased-reference-head', assetVersion: 1, revision: 0
      }));
      if (frame.type === 'GS_CAPTURE') window.__probeCapture = frame.payload.gsView;
    };
    window.postMessage('SELF_PORT_V1', '*', [channel.port2]);
  });
  await page.waitForTimeout(600);
  await page.evaluate(() => window.__probePort.postMessage(JSON.stringify({
    schemaVersion: 1, type: 'GS_COMMAND', sessionId: 'research-probe',
    assetId: 'unreleased-reference-head', payload: { action: 'CAPTURE' }
  })));
  await page.waitForFunction(() => window.__probeCapture !== null, null, { timeout: 10000 });
  await page.waitForTimeout(300);
  const raw = await page.evaluate(() => document.querySelector('#portrait').toDataURL('image/png'));
  const image = path.join(out, `private-reference-${frameTag}-canvas.png`);
  await fs.writeFile(image, Buffer.from(raw.split(',')[1], 'base64'));
  const snapshot = await page.evaluate(() => window.__probeCapture);
  const report = { status, webgl2, playcanvas: '2.22.4', sourceAsset: ply,
    plySha256: crypto.createHash('sha256').update(await fs.readFile(ply)).digest('hex'),
    referenceFrame, sourceView: view, renderedView: snapshot,
    canvasSize: await page.evaluate(() => {
      const canvas = document.querySelector('#portrait');
      return [canvas.width, canvas.height];
    }), image, messages,
    note: 'Real desktop Chrome/SwiftShader PlayCanvas draw only; not HarmonyOS, not release eligibility' };
  await fs.writeFile(path.join(out, 'audit.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ status, webgl2, canvasSize: report.canvasSize,
    plySha256: report.plySha256, image }));
} catch (error) {
  console.error(JSON.stringify({ error: String(error), messages }));
  process.exitCode = 1;
} finally {
  await browser.close();
}
