import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

// Read-only audit. No application data, build configuration or Git state is changed.
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const git = (...args) => execFileSync('git', ['-c', `safe.directory=${root.replaceAll('\\', '/')}`,
  '-C', root, ...args], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
const sha256 = async filename => {
  const digest = crypto.createHash('sha256');
  for await (const chunk of fs.createReadStream(filename)) digest.update(chunk);
  return digest.digest('hex');
};
const readJson = relative => JSON.parse(fs.readFileSync(path.join(root, relative), 'utf8'));
const modelRoot = path.join(root, 'backend/.data/reconstruction');
const modelArgument = process.argv.find(arg => arg.startsWith('--model='));
const sample = modelArgument ? path.resolve(modelArgument.slice(8)) : fs.readdirSync(modelRoot)
  .sort().map(id => path.join(modelRoot, id, 'portrait.gaussian.ply')).find(p => fs.existsSync(p));
if (!sample) throw new Error('No saved representative PLY: supply --model=<path>.');

const handle = fs.openSync(sample, 'r');
let ply;
try {
  const prefix = Buffer.alloc(65536);
  const size = fs.readSync(handle, prefix, 0, prefix.length, 0);
  const marker = prefix.indexOf('end_header\n');
  if (marker < 0 || marker + 11 > size) throw new Error('PLY header missing or larger than audit bound.');
  const offset = marker + 11;
  const header = prefix.subarray(0, offset).toString('ascii');
  const lines = header.trim().split('\n');
  const encoding = lines.find(line => line.startsWith('format '));
  const count = Number(lines.find(line => line.startsWith('element vertex '))?.split(' ')[2]);
  const properties = lines.filter(line => line.startsWith('property ')).map(line => {
    const [, type, name] = line.split(' '); return { type, name };
  });
  if (encoding !== 'format binary_little_endian 1.0' || !Number.isSafeInteger(count) || count <= 0 ||
      properties.some(property => property.type !== 'float')) throw new Error('Audit currently expects f32 LE vertices.');
  const stride = properties.length * 4;
  const bytes = fs.statSync(sample).size;
  if (offset + count * stride !== bytes) throw new Error('PLY length does not match header.');
  const xyzOffsets = ['x', 'y', 'z'].map(name => properties.findIndex(property => property.name === name) * 4);
  if (xyzOffsets.some(index => index < 0)) throw new Error('Missing position.');
  const min = [Infinity, Infinity, Infinity], max = [-Infinity, -Infinity, -Infinity];
  let nonFinitePositions = 0;
  // Fixed-size reads, including for very large PLY files.
  const rowsPerRead = Math.max(1, Math.floor(1048576 / stride));
  const buffer = Buffer.alloc(rowsPerRead * stride);
  for (let vertex = 0; vertex < count;) {
    const rows = Math.min(rowsPerRead, count - vertex), required = rows * stride;
    let read = 0;
    while (read < required) {
      const n = fs.readSync(handle, buffer, read, required - read, offset + vertex * stride + read);
      if (!n) throw new Error('Truncated vertices.');
      read += n;
    }
    for (let row = 0; row < rows; row++) {
      for (let axis = 0; axis < 3; axis++) {
        const value = buffer.readFloatLE(row * stride + xyzOffsets[axis]);
        if (!Number.isFinite(value)) { nonFinitePositions++; continue; }
        min[axis] = Math.min(min[axis], value); max[axis] = Math.max(max[axis], value);
      }
    }
    vertex += rows;
  }
  const rest = properties.filter(property => /^f_rest_\d+$/.test(property.name)).length;
  ply = { sample: path.relative(root, sample).replaceAll('\\', '/'), bytes,
    sha256: await sha256(sample), header, encoding: 'binary_little_endian', vertexCount: count,
    properties, shRestProperties: rest, shDegree: Math.sqrt(rest / 3 + 1) - 1,
    bounds: { min, max }, nonFinitePositions };
} finally { fs.closeSync(handle); }

const sdk = 'C:/Program Files/Huawei/DevEco Studio/sdk/default';
const product = readJson('build-profile.json5').app.products[0];
const app = readJson('AppScope/app.json5').app;
const module = readJson('entry/src/main/module.json5').module;
const signatures = fs.readFileSync(`${sdk}/hms/ets/api/@hms.collaboration.harmonyShare.d.ts`, 'utf8');
const files = ['viewer-gs/main.js', 'node_modules/playcanvas/package.json',
  'node_modules/playcanvas/build/playcanvas/src/framework/parsers/ply.js',
  'node_modules/playcanvas/build/playcanvas/src/scene/gsplat/gsplat-data.js'];
const sourceHashes = [];
for (const file of files) sourceHashes.push({ file, sha256: await sha256(path.join(root, file)) });
console.log(JSON.stringify({ auditOnly: true, project: path.basename(root),
  git: { branch: git('branch', '--show-current'), head: git('rev-parse', 'HEAD'),
    recent: git('log', '-5', '--oneline').split('\n'), status: git('status', '--short').split('\n') },
  sdk: JSON.parse(fs.readFileSync(`${sdk}/sdk-pkg.json`, 'utf8')).data,
  targetSdkVersion: product.targetSdkVersion, compatibleSdkVersion: product.compatibleSdkVersion,
  compileSdkVersion: product.compileSdkVersion ?? 'not explicitly set; resolved by Hvigor target/default SDK',
  stage: readJson('entry/build-profile.json5').apiType,
  bundleName: app.bundleName, appVersion: app.versionName, moduleName: module.name,
  mainElement: module.mainElement, mainWindowSource: 'entry/src/main/ets/entryability/EntryAbility.ets:onWindowStageCreate',
  harmonyShareSignatures: signatures.split('\n').map(line => line.trim()).filter(line =>
    /^(function (on|off)\(event: '(knockShare|dataReceive)'|share\(data:|receive\(receiveUri:)/.test(line)),
  sourceHashes, ply,
  verification: { packageRoundTrip: 'not implemented', import: 'not implemented',
    viewerVisualInterop: 'not run', deviceTransfer: 'not run' }
}, null, 2));
