import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import vm from 'node:vm';
import { execFileSync } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { transformSync } from 'esbuild';

const project = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..').replaceAll('\\', '/');
const bundledPython = path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe');
const python = process.env.SELF_TRANSFER_TEST_PYTHON || (fs.existsSync(bundledPython) ? bundledPython : 'python');
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'self-transfer-tests-')).replaceAll('\\', '/');
const zipHelper = `${project}/scripts/self-transfer-test-zip.py`;
const json = (filename, value) => fs.writeFileSync(filename, JSON.stringify(value));
const sha = filename => {
  const hash = crypto.createHash('sha256'), fd = fs.openSync(filename, 'r'), buffer = Buffer.alloc(1048576);
  try { for (;;) { const n = fs.readSync(fd, buffer); if (!n) break; hash.update(buffer.subarray(0, n)); } }
  finally { fs.closeSync(fd); } return hash.digest('hex');
};
const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
let extractionCount = 0;
let freeBytes = Number.MAX_SAFE_INTEGER;
globalThis.canIUse = () => true;
const sdk = { sdkApiVersion: 26, deviceType: 'tablet' };
const stats = filename => {
  const value = typeof filename === 'number' ? fs.fstatSync(filename) : fs.statSync(filename);
  return { size: value.size, mtime: value.mtimeMs / 1000, isFile: () => value.isFile(), isDirectory: () => value.isDirectory(), isSymbolicLink: () => value.isSymbolicLink() };
};
const fileIo = {
  OpenMode: { READ_ONLY: fs.constants.O_RDONLY, READ_WRITE: fs.constants.O_RDWR, CREATE: fs.constants.O_CREAT, TRUNC: fs.constants.O_TRUNC },
  accessSync: fs.existsSync, statSync: stats,
  lstatSync: filename => { const value = fs.lstatSync(filename); return { ...stats(filename), isSymbolicLink: () => value.isSymbolicLink() }; },
  openSync: (filename, flags) => ({ fd: fs.openSync(filename.startsWith?.('file://') ? fileURLToPath(filename) : filename, flags) }),
  closeSync: file => fs.closeSync(typeof file === 'number' ? file : file.fd),
  writeSync: (fd, value) => fs.writeSync(fd, typeof value === 'string' ? value : Buffer.from(value)), fsyncSync: fs.fsyncSync,
  readTextSync: filename => fs.readFileSync(filename, 'utf8'),
  read: (fd, target, options = {}) => new Promise((resolve, reject) => fs.read(fd, Buffer.from(target), 0, options.length ?? target.byteLength,
    options.offset ?? null, (error, n) => error ? reject(error) : resolve(n))),
  readSync: (fd, target, options = {}) => fs.readSync(fd, Buffer.from(target), 0, options.length ?? target.byteLength, options.offset ?? null),
  listFileSync: fs.readdirSync, mkdirSync: (filename, recursive = false) => fs.mkdirSync(filename, { recursive }),
  rename: fs.promises.rename, renameSync: fs.renameSync, unlinkSync: fs.unlinkSync, rmdirSync: fs.rmdirSync,
  copyFileSync: (source, destination) => {
    if (typeof source === 'string') return fs.copyFileSync(source, destination);
    const dest = fs.openSync(destination, 'w'), buffer = Buffer.alloc(1048576); let offset = 0;
    try { for (;;) { const n = fs.readSync(source, buffer, 0, buffer.length, offset); if (!n) break; fs.writeSync(dest, buffer, 0, n); offset += n; } }
    finally { fs.closeSync(dest); }
  },
  copyFile: async (source, destination) => fileIo.copyFileSync(source, destination)
};
const zip = (operation, source, destination) => execFileSync(python, [zipHelper, operation, source, destination], { stdio: 'pipe' });
const zlib = {
  CompressLevel: { COMPRESS_LEVEL_NO_COMPRESSION: 0 },
  compressFile: async (source, destination) => zip('pack', source, destination),
  decompressFile: async (source, destination) => { extractionCount++; zip('extract', source, destination); }
};
const share = { send: new Map(), receive: new Map(), calls: [],
  on: (kind, capability, callback) => { const map = kind === 'knockShare' ? share.send : share.receive;
    assert.equal(map.has(capability.windowId), false, 'duplicate native listener'); map.set(capability.windowId, callback); share.calls.push(['on', kind, capability.windowId]); },
  off: (kind, capability, callback) => { const map = kind === 'knockShare' ? share.send : share.receive;
    assert.equal(map.get(capability.windowId), callback, 'off must use exact callback reference'); map.delete(capability.windowId); share.calls.push(['off', kind, capability.windowId]); },
  SharableErrorCode: { NO_CONTENT_ERROR: 1 }, ReceivableErrorCode: { NO_RECEIVABLE_ERROR: 1 },
  ShareResultCode: { SHARE_SUCCESS: 0, SEND_FAILED: 1, CANCEL_BY_SENDER: 2, CANCEL_BY_RECEIVER: 3 }
};
class SharedData { constructor(record) { this.record = record; } getRecords() { return [this.record]; } }
const imports = {
  '@kit.AbilityKit': { bundleManager: { BundleFlag: { GET_BUNDLE_INFO_DEFAULT: 0 }, getBundleInfoForSelfSync: () => ({ versionName: '0.1.0' }) } },
  '@kit.CoreFileKit': { fileIo, hash: { hash: async filename => sha(filename) }, statfs: { getFreeSize: async () => freeBytes },
    fileUri: { getUriFromPath: value => pathToFileURL(value).href, FileUri: class { constructor(value) { this.path = fileURLToPath(value).replaceAll('\\', '/'); } } } },
  '@kit.ArkTS': { util: { generateRandomUUID: () => crypto.randomUUID(), TextEncoder: class { encodeInto(value) { return new TextEncoder().encode(value); } },
    Base64Helper: class { decodeSync(value) { return new Uint8Array(Buffer.from(value, 'base64')); } encodeToStringSync(value) { return Buffer.from(value).toString('base64'); } } } },
  '@kit.BasicServicesKit': { deviceInfo: sdk, zlib }, '@kit.MediaLibraryKit': {},
  '@kit.ShareKit': { harmonyShare: share, systemShare: { SharedData, getSharedData: async want => want.data } },
  '@kit.ArkData': { uniformTypeDescriptor: { getTypeDescriptor: value => ({ belongsTo: target => target === 'general.file' && value === 'general.zip-archive' }) } }
};

function loader(root = project) {
  const cache = new Map();
  const load = filename => {
    if (cache.has(filename)) return cache.get(filename).exports;
    const module = { exports: {} }; cache.set(filename, module);
    const source = fs.readFileSync(filename, 'utf8');
    const code = transformSync(source, { loader: 'ts', format: 'cjs', target: 'es2022', tsconfigRaw: { compilerOptions: { useDefineForClassFields: false } } }).code;
    const require = name => {
      if (name in imports) return imports[name];
      assert.ok(name.startsWith('.'), `Unexpected platform import ${name}`);
      return load(path.resolve(path.dirname(filename), name + '.ets'));
    };
    vm.runInThisContext(`(function(require,module,exports){${code}\n})`, { filename })(require, module, module.exports);
    return module.exports;
  };
  return name => load(`${root}/entry/src/main/ets/transfer/${name}.ets`);
}
const load = loader(), { TransferCoordinator } = load('TransferCoordinator'), state = load('TransferState');
const contract = load('SelfTransferContract'), { SelfTransferPackage } = load('SelfTransferPackage');
const { HarmonyShareBridge } = load('HarmonyShareBridge');

function context(name) {
  const root = `${temporary}/${name}`; for (const folder of ['files', 'cache']) fs.mkdirSync(root + '/' + folder, { recursive: true });
  return { filesDir: root + '/files', cacheDir: root + '/cache', applicationInfo: { name: name.includes('harmony') ? 'com.self.mirror.harmony' : 'com.self.mirror', debug: true } };
}
function seed(ctx, realModel) {
  const id = crypto.randomBytes(16).toString('hex'), directory = `${ctx.filesDir}/models/${id}`;
  fs.mkdirSync(directory, { recursive: true });
  const names = ['x', 'y', 'z', 'f_dc_0', 'f_dc_1', 'f_dc_2', ...Array.from({ length: 45 }, (_, i) => 'f_rest_' + i),
    'opacity', 'scale_0', 'scale_1', 'scale_2', 'rot_0', 'rot_1', 'rot_2', 'rot_3'];
  const header = Buffer.from(`ply\nformat binary_little_endian 1.0\nelement vertex 32\n${names.map(n => 'property float ' + n).join('\n')}\nend_header\n`);
  const data = Buffer.alloc(32 * names.length * 4);
  for (let i = 0; i < 32; i++) for (let p = 0; p < names.length; p++) {
    const name = names[p], value = name === 'rot_0' ? 1 : name.startsWith('scale_') ? -3 : name === 'x' ? i * 0.01 : 0;
    data.writeFloatLE(value, (i * names.length + p) * 4);
  }
  if (realModel) fs.copyFileSync(realModel, directory + '/portrait.gaussian.ply');
  else fs.writeFileSync(directory + '/portrait.gaussian.ply', Buffer.concat([header, data]));
  json(directory + '/portrait.view.json', { schemaVersion: 1, target: [0, 0, 0], camera: [0, 0, 3], up: [0, 1, 0], fovDegrees: 45,
    sourceFrame: '', faceTrackCount: 0, sourceFaceFraction: 0.5, targetFaceFraction: 0.5 });
  json(ctx.filesDir + '/portrait-stars.json', { schemaVersion: 1, stars: [{ jobId: id, name: '测试星辰', createdAt: 1 }], deletedIds: [] });
  return { id, directory, path: directory + '/portrait.gaussian.ply' };
}
function incoming(ctx, source) {
  const directory = `${ctx.cacheDir}/self_transfer/incoming/${crypto.randomUUID()}`; fs.mkdirSync(directory, { recursive: true });
  const filename = directory + '/test.self3d.zip'; fs.copyFileSync(source, filename); return filename;
}
function fakeTransport() {
  return { mode: '', registrations: 0, supported: () => true, automaticReceive: () => true,
    clear() { this.mode = ''; }, listenSend(p, begin, submitted, error) { assert.equal(this.mode, ''); this.mode = 'SEND'; this.registrations++; this.prepared = p; this.begin = begin; this.submitted = submitted; this.error = error; },
    listenReceive(begin, file, error) { assert.equal(this.mode, ''); this.mode = 'RECEIVE'; this.registrations++; this.begin = begin; this.file = file; this.error = error; } };
}
function fakeModels() {
  return { prepare: async (modelId, revision) => ({ path: 'prepared.zip', packageId: 'package', modelId, revision }),
    importPackage: async (_path, cancelled) => { if (cancelled()) throw Error('cancelled'); return { modelId: 'received', packageId: 'package', duplicate: false, sha256: 'digest', name: 'name' }; } };
}
test('page intent, override, background, busy and exact-once lifecycle', async () => {
  const port = fakeTransport(), coordinator = new TransferCoordinator(port, fakeModels());
  let last; coordinator.onChanged = value => { last = value; }; coordinator.setForeground(true);
  coordinator.setSurface({ kind: 'HOME', modelId: '', revision: '' }); assert.equal(last.phase, 'RECEIVE_READY'); assert.equal(port.mode, 'RECEIVE');
  coordinator.setSurface({ kind: 'VIEWER', modelId: 'open-model', revision: 'r1' }); assert.equal(last.phase, 'PREPARING_SEND'); await flush();
  assert.equal(last.phase, 'SEND_READY'); assert.equal(port.prepared.modelId, 'open-model');
  const registrations = port.registrations; for (let i = 0; i < 20; i++) coordinator.setSurface({ kind: 'VIEWER', modelId: 'open-model', revision: 'r1' });
  assert.equal(port.registrations, registrations);
  coordinator.forceReceive(true); assert.equal(last.phase, 'RECEIVE_READY'); assert.equal(port.mode, 'RECEIVE');
  coordinator.forceReceive(false); await flush(); assert.equal(last.phase, 'SEND_READY');
  coordinator.setForeground(false); assert.equal(port.mode, ''); assert.equal(last.intent, 'NONE');
  coordinator.setForeground(true); await flush(); assert.equal(port.mode, 'SEND');
  coordinator.setSurface({ kind: 'BUSY', modelId: '', revision: '' }); assert.equal(port.mode, '');
  coordinator.setSurface({ kind: 'LIST', modelId: '', revision: '' }); assert.equal(port.mode, 'RECEIVE');
  coordinator.setSurface({ kind: 'NONE', modelId: '', revision: '' }); assert.equal(port.mode, ''); coordinator.dispose();
});
test('late package preparation cannot register after page exit', async () => {
  let resolve; const port = fakeTransport(), models = fakeModels(); models.prepare = () => new Promise(r => { resolve = r; });
  const coordinator = new TransferCoordinator(port, models); coordinator.setForeground(true);
  coordinator.setSurface({ kind: 'VIEWER', modelId: 'old', revision: '1' }); coordinator.setSurface({ kind: 'HOME', modelId: '', revision: '' });
  resolve({ path: 'old.zip', modelId: 'old', revision: '1' }); await flush(); assert.equal(port.mode, 'RECEIVE'); coordinator.dispose();
});
test('receive started before background cannot publish after foreground resumes', async () => {
  const port = fakeTransport(); const coordinator = new TransferCoordinator(port, fakeModels()); let imports = 0;
  coordinator.onImported = () => imports++; coordinator.setForeground(true); coordinator.setSurface({ kind: 'HOME', modelId: '', revision: '' });
  assert.equal(port.begin(), true); const file = port.file; coordinator.setForeground(false); coordinator.setForeground(true); file('late.zip');
  await flush(); assert.equal(imports, 0); coordinator.dispose();
});
test('manual receive restores AUTO and reports duplicate import separately', async () => {
  const port = fakeTransport(), coordinator = new TransferCoordinator(port, fakeModels()); let last;
  coordinator.onChanged = value => { last = value; }; coordinator.setForeground(true); coordinator.setSurface({ kind: 'VIEWER', modelId: 'current', revision: '1' }); await flush();
  await coordinator.receiveManually('received.zip'); await flush(); assert.equal(last.policy, 'AUTO'); assert.equal(port.mode, 'SEND'); coordinator.dispose();
});

test('manual copy reservation excludes automatic receipt and cancels publication after navigation', async () => {
  const port = fakeTransport(), coordinator = new TransferCoordinator(port, fakeModels());
  let imported = 0; coordinator.onImported = () => imported++;
  coordinator.setForeground(true); coordinator.setSurface({ kind: 'HOME', modelId: '', revision: '' });
  const automaticBegin = port.begin;
  assert.equal(coordinator.reserveManualReceive(), true); assert.equal(port.mode, '');
  assert.equal(automaticBegin(), false); assert.equal(coordinator.reserveManualReceive(), false);
  coordinator.setSurface({ kind: 'BUSY', modelId: '', revision: '' });
  await coordinator.importFile('finished-copy.zip', true); assert.equal(imported, 0);
  coordinator.releaseManualReceive(); assert.equal(port.mode, '');
  coordinator.setSurface({ kind: 'HOME', modelId: '', revision: '' }); assert.equal(port.mode, 'RECEIVE'); coordinator.dispose();
});
test('bridge uses real window identity, exact callback off, exclusive directions, and API<20 guard', () => {
  const ctx = context('bridge'), bridge = new HarmonyShareBridge(ctx.cacheDir + '/self_transfer', 739);
  const prepared = { path: 'model.zip' };
  for (let i = 0; i < 20; i++) { bridge.listenReceive(() => true, () => {}, () => {}); bridge.listenSend(prepared, () => true, () => {}, () => {}); }
  assert.equal(share.receive.size, 0); assert.equal(share.send.size, 1); assert.ok(share.send.has(739)); bridge.clear();
  const calls = share.calls.length; sdk.sdkApiVersion = 19; bridge.listenReceive(() => true, () => {}, () => {}); bridge.listenSend(prepared, () => true, () => {}, () => {}); bridge.clear();
  assert.equal(share.calls.length, calls); sdk.sdkApiVersion = 26;
  sdk.deviceType = 'phone'; bridge.listenReceive(() => true, () => {}, () => {}); assert.equal(share.receive.size, 0); assert.equal(bridge.automaticReceive(), false);
  sdk.deviceType = 'tablet'; bridge.clear();
});

test('official receive callback waits for BOTH data and success; accepts native sandbox paths; cancellation never publishes', async () => {
  for (const order of ['data-first', 'result-first', 'local-path', 'cancel']) {
    const ctx = context('receive-order-' + order), bridge = new HarmonyShareBridge(ctx.cacheDir + '/self_transfer', 851);
    let delivered = 0, failures = 0, callbacks, directory;
    bridge.listenReceive(() => true, () => delivered++, () => failures++);
    const listener = share.receive.get(851);
    listener({ reject: async () => {}, receive: async (uri, cb) => { assert.ok(share.receive.has(851), 'sandbox receiver must remain registered'); directory = fileURLToPath(uri); callbacks = cb; } });
    await flush(); assert.ok(callbacks);
    const filename = path.join(directory, 'model.self3d.zip'); fs.writeFileSync(filename, 'zip-fixture');
    const data = new SharedData({ utd: order === 'local-path' ? 'general.object' : 'general.zip-archive', uri: order === 'local-path' ? filename.replaceAll('\\', '/') : pathToFileURL(filename).href });
    if (order === 'data-first') { callbacks.onDataReceived(data); assert.equal(delivered, 0); callbacks.onResult(0); }
    if (order === 'result-first') { callbacks.onResult(0); assert.equal(delivered, 0); callbacks.onDataReceived(data); }
    if (order === 'local-path') { callbacks.onResult(0); callbacks.onDataReceived(data); }
    if (order === 'cancel') { callbacks.onResult(2); callbacks.onDataReceived(data); assert.equal(delivered, 0); assert.equal(failures, 1); assert.equal(fs.existsSync(directory), false); }
    else { assert.equal(delivered, 1); assert.equal(failures, 0); callbacks.onResult(0); assert.equal(delivered, 1); }
    bridge.clear();
  }
});

const senderContext = context('sender-harmony'), senderModel = seed(senderContext), senderPackages = new SelfTransferPackage(senderContext);
test('sandbox reception rejects files outside its isolated directory without touching them', async () => {
  const ctx = context('sandbox-outside'), bridge = new HarmonyShareBridge(ctx.cacheDir + '/self_transfer', 853);
  const outside = ctx.filesDir + '/untouched.zip'; fs.writeFileSync(outside, 'existing-user-file');
  let delivered = 0, failures = 0, callbacks, directory;
  bridge.listenReceive(() => true, () => delivered++, () => failures++);
  share.receive.get(853)({ reject: async () => {}, receive: async (uri, cb) => { directory = fileURLToPath(uri); callbacks = cb; } });
  await flush(); callbacks.onDataReceived(new SharedData({ utd: 'general.object', uri: outside.replaceAll('\\', '/') })); callbacks.onResult(0);
  assert.equal(delivered, 0); assert.equal(failures, 1); assert.equal(fs.existsSync(directory), false);
  assert.equal(fs.readFileSync(outside, 'utf8'), 'existing-user-file'); bridge.clear();
});
let prepared;
test('create standard package, manifest, immutable PLY, cache reuse and optional camera', async () => {
  prepared = await senderPackages.prepare(senderModel.id, 'revision1');
  const directory = `${temporary}/unpacked`; fs.mkdirSync(directory); zip('extract', prepared.path, directory);
  const manifest = JSON.parse(fs.readFileSync(directory + '/manifest.json', 'utf8')); contract.validateManifest(manifest);
  assert.equal(manifest.protocolVersion, 1); assert.equal(sha(directory + '/model/model.ply'), sha(senderModel.path));
  assert.ok(manifest.optionalFeatures.includes('viewer.camera.v1')); assert.equal((await senderPackages.prepare(senderModel.id, 'revision1')).packageId, prepared.packageId);
});
test('atomic repository import, new local ID, duplicate package, no overwrite', async () => {
  const ctx = context('receiver'), existing = seed(ctx), packages = new SelfTransferPackage(ctx);
  const result = await packages.importPackage(incoming(ctx, prepared.path), () => false);
  assert.notEqual(result.modelId, senderModel.id); assert.notEqual(result.modelId, existing.id);
  assert.equal(sha(`${ctx.filesDir}/models/${result.modelId}/portrait.gaussian.ply`), sha(senderModel.path));
  assert.equal((await packages.importPackage(incoming(ctx, prepared.path), () => false)).modelId, result.modelId);
  assert.equal(fs.readdirSync(ctx.filesDir + '/models').length, 2); assert.equal(fs.readdirSync(ctx.cacheDir + '/self_transfer/staging').length, 0);
});
test('system sandbox listener survives acceptance through file completion, then imports and opens the same named star', async () => {
  const ctx = context('sandbox-coordinator'), packages = new SelfTransferPackage(ctx);
  const bridge = new HarmonyShareBridge(packages.root, 852), coordinator = new TransferCoordinator(bridge, packages);
  let callbacks, directory, opened;
  coordinator.onImported = value => { opened = value; };
  coordinator.setForeground(true); coordinator.setSurface({ kind: 'HOME', modelId: '', revision: '' });
  const listener = share.receive.get(852);
  const target = { reject: async () => { throw Error('ready receiver rejected'); }, receive: async (uri, cb) => {
    assert.equal(share.receive.get(852), listener, 'off before receive causes system fallback');
    directory = fileURLToPath(uri); callbacks = cb;
  } };
  listener(target); await flush(); assert.ok(callbacks);
  let duplicates = 0; listener({ reject: async () => { duplicates++; }, receive: async () => { throw Error('duplicate accepted'); } });
  assert.equal(duplicates, 1); assert.equal(coordinator.diagnostic().phase, 'TRANSFERRING');
  const filename = path.join(directory, 'named.self3d.zip'); fs.copyFileSync(prepared.path, filename);
  callbacks.onDataReceived(new SharedData({ utd: 'general.zip-archive', uri: pathToFileURL(filename).href }));
  assert.equal(share.receive.get(852), listener); callbacks.onResult(0);
  for (let attempt = 0; attempt < 200 && !opened; attempt++) await new Promise(resolve => setTimeout(resolve, 5));
  assert.ok(opened, 'automatic receive must invoke original model-open callback'); assert.equal(opened.name, '测试星辰');
  assert.equal(sha(`${ctx.filesDir}/models/${opened.modelId}/portrait.gaussian.ply`), sha(senderModel.path));
  const index = JSON.parse(fs.readFileSync(ctx.filesDir + '/portrait-stars.json', 'utf8'));
  assert.equal(index.stars.find(star => star.jobId === opened.modelId).name, '测试星辰'); coordinator.dispose();
});
test('renaming a star refreshes package metadata without changing its PLY; repeated reception preserves its name', async () => {
  const ctx = context('rename-sender'), model = seed(ctx), packages = new SelfTransferPackage(ctx);
  const first = await packages.prepare(model.id, 'same-ply'), digest = sha(model.path);
  const index = JSON.parse(fs.readFileSync(ctx.filesDir + '/portrait-stars.json', 'utf8'));
  index.stars[0].name = '晚风与星光 ✦'; json(ctx.filesDir + '/portrait-stars.json', index);
  const renamed = await packages.prepare(model.id, 'same-ply');
  assert.notEqual(renamed.packageId, first.packageId); assert.equal(renamed.displayName, index.stars[0].name);
  assert.equal(sha(model.path), digest);
  const receiver = context('rename-receiver'), target = new SelfTransferPackage(receiver);
  const received = await target.importPackage(incoming(receiver, renamed.path), () => false);
  assert.equal(received.name, index.stars[0].name);
  const duplicate = await target.importPackage(incoming(receiver, renamed.path), () => false);
  assert.equal(duplicate.modelId, received.modelId); assert.equal(duplicate.name, received.name);
  const roundtrip = await target.prepare(received.modelId, 'received'); assert.equal(roundtrip.displayName, received.name);
});
for (const mode of ['missing-manifest', 'missing-model', 'bad-sha', 'unsupported-version', 'unknown-required', 'invalid-zip', 'traversal', 'backslash', 'absolute', 'drive', 'duplicate-entry', 'local-central-mismatch', 'local-unicode-path', 'local-size-mismatch', 'unsupported-ply', 'bad-length']) {
  test(`reject ${mode} without publishing partial model; remove staging and incoming`, async () => {
    const ctx = context('negative-' + mode), packages = new SelfTransferPackage(ctx), directory = `${temporary}/variant-${mode}`; fs.mkdirSync(directory);
    const manifest = JSON.parse(fs.readFileSync(`${temporary}/unpacked/manifest.json`, 'utf8'));
    if (mode === 'bad-sha') manifest.assets[0].sha256 = manifest.model.sha256 = '0'.repeat(64);
    if (mode === 'unsupported-version') manifest.protocolVersion = 2;
    if (mode === 'unknown-required') manifest.requiredFeatures.push('unknown.feature');
    if (mode === 'bad-length') manifest.assets[0].byteLength = manifest.model.byteLength = 20;
    let plyFile = senderModel.path;
    if (mode === 'unsupported-ply') {
      plyFile = directory + '/unsupported.ply'; const bytes = fs.readFileSync(senderModel.path); bytes.write('binary_big_endian ', 11, 'ascii'); fs.writeFileSync(plyFile, bytes);
      manifest.assets[0].sha256 = manifest.model.sha256 = sha(plyFile);
    }
    json(directory + '/manifest.json', manifest);
    const modelName = { traversal: '../escape.ply', backslash: 'model\\..\\escape.ply', absolute: '/escape.ply', drive: 'C:/escape.ply' }[mode] || 'model/model.ply';
    const entries = [{ path: 'manifest.json', source: directory + '/manifest.json' }, { path: modelName, source: plyFile },
      { path: 'viewer/viewer_state.json', source: `${temporary}/unpacked/viewer/viewer_state.json` }];
    if (mode === 'missing-manifest') entries.splice(0, 1); if (mode === 'missing-model') entries.splice(1, 1);
    if (mode === 'duplicate-entry') entries.push(entries[1]);
    if (mode === 'local-unicode-path') entries[1].extra = '75700000';
    const archive = directory + '/test.zip'; json(directory + '/entries.json', entries); zip('compose', directory + '/entries.json', archive);
    if (mode === 'invalid-zip') fs.writeFileSync(archive, 'not a zip');
    if (mode === 'local-central-mismatch') {
      const bytes = fs.readFileSync(archive);
      let offset = 0, changed = false;
      while (offset < bytes.length - 30) {
        if (bytes.readUInt32LE(offset) === 0x04034b50 && bytes.subarray(offset + 30, offset + 30 + bytes.readUInt16LE(offset + 26)).toString() === 'model/model.ply') {
          bytes[offset + 30] = 'x'.charCodeAt(0); changed = true; break;
        } offset++;
      }
      assert.ok(changed); fs.writeFileSync(archive, bytes);
    }
    if (mode === 'local-size-mismatch' || mode === 'local-unicode-path') {
      const bytes = fs.readFileSync(archive); let changed = false;
      for (let offset = 0; offset < bytes.length - 46; offset++) {
        if (mode === 'local-size-mismatch' && bytes.readUInt32LE(offset) === 0x04034b50) { bytes.writeUInt32LE(1, offset + 22); changed = true; break; }
        if (mode === 'local-unicode-path' && bytes.readUInt32LE(offset) === 0x02014b50 && bytes.readUInt16LE(offset + 30) > 0) {
          bytes.writeUInt16LE(0xaaaa, offset + 46 + bytes.readUInt16LE(offset + 28)); changed = true; break;
        }
      }
      assert.ok(changed); fs.writeFileSync(archive, bytes);
    }
    const extractedBefore = extractionCount;
    await assert.rejects(packages.importPackage(incoming(ctx, archive), () => false));
    if (['traversal', 'backslash', 'absolute', 'drive', 'duplicate-entry', 'local-central-mismatch', 'local-unicode-path', 'local-size-mismatch'].includes(mode)) assert.equal(extractionCount, extractedBefore, 'unsafe ZIP rejected before extraction');
    assert.equal(fs.readdirSync(ctx.filesDir + '/models').length, 0); assert.equal(fs.readdirSync(ctx.cacheDir + '/self_transfer/staging').length, 0);
    assert.equal(fs.readdirSync(ctx.cacheDir + '/self_transfer/incoming').length, 0);
  });
}
test('unknown optional feature is ignored and missing optional asset remains optional', async () => {
  const ctx = context('optional'), packages = new SelfTransferPackage(ctx), manifest = JSON.parse(fs.readFileSync(`${temporary}/unpacked/manifest.json`, 'utf8'));
  manifest.optionalFeatures.push('future.something'); const directory = `${temporary}/optional-archive`; fs.mkdirSync(directory); json(directory + '/manifest.json', manifest);
  json(directory + '/entries.json', [{ path: 'manifest.json', source: directory + '/manifest.json' }, { path: 'model/model.ply', source: senderModel.path }]);
  zip('compose', directory + '/entries.json', directory + '/test.zip'); const result = await packages.importPackage(incoming(ctx, directory + '/test.zip'), () => false);
  assert.equal(result.duplicate, false);
});
test('cancelled import and insufficient space never register a model', async () => {
  const ctx = context('space'), packages = new SelfTransferPackage(ctx);
  await assert.rejects(packages.importPackage(incoming(ctx, prepared.path), () => true));
  freeBytes = 0; try { await assert.rejects(packages.importPackage(incoming(ctx, prepared.path), () => false), /空间不足/); } finally { freeBytes = Number.MAX_SAFE_INTEGER; }
  assert.equal(fs.readdirSync(ctx.filesDir + '/models').length, 0);
});
test('saved visual edits cannot silently send the original PLY', async () => {
  const ctx = context('edits'), model = seed(ctx), packages = new SelfTransferPackage(ctx);
  json(model.directory + '/portrait.edit.v2.json', { groups: [{ groupId: 'colour-change' }] });
  await assert.rejects(packages.prepare(model.id, '1'), /试色记录不完整/);
});
const maskChecksum = bytes => { let value = 2166136261; for (const byte of bytes) value = Math.imul(value ^ byte, 16777619) >>> 0; return value.toString(16); };
const savedHistory = model => {
  const mask = Buffer.alloc(32); mask.fill(255, 4, 18); mask[4] = 64;
  return { schemaVersion: 2, assetId: model.id, assetBytes: fs.statSync(model.path).size, splatCount: 32,
    groups: [{ groupId: 'lipstick', label: '涂成红色口红', createdAt: 1,
      careGuide: { privatePlannerContext: 'must-not-transfer' }, layers: [{ layerId: 'rose-1', regionId: 'selected-1', preset: 'rose', strength: 0.32,
        maskBase64: mask.toString('base64'), maskChecksum: maskChecksum(mask) }] }] };
};
test('all four directions preserve saved colour layers and name with remapped local IDs and unchanged PLY', async () => {
  for (const source of ['olay', 'olay_harmony']) for (const target of ['olay', 'olay_harmony']) {
    const a = context('colour-source-' + source + target), b = context('colour-target-' + source + target), model = seed(a);
    const history = savedHistory(model); json(model.directory + '/portrait.edit.v2.json', history);
    const Source = loader(project + '/../' + source)('SelfTransferPackage').SelfTransferPackage;
    const Target = loader(project + '/../' + target)('SelfTransferPackage').SelfTransferPackage;
    const packages = new Source(a), first = await packages.prepare(model.id, 'same-ply');
    const received = await new Target(b).importPackage(incoming(b, first.path), () => false);
    const restored = JSON.parse(fs.readFileSync(`${b.filesDir}/models/${received.modelId}/portrait.edit.v2.json`, 'utf8'));
    assert.equal(restored.assetId, received.modelId); assert.notEqual(restored.assetId, model.id);
    assert.equal(received.name, '测试星辰'); assert.equal(restored.groups[0].label, history.groups[0].label);
    assert.deepEqual(restored.groups[0].layers, history.groups[0].layers); assert.equal('careGuide' in restored.groups[0], false);
    assert.equal(sha(`${b.filesDir}/models/${received.modelId}/portrait.gaussian.ply`), sha(model.path));
    const replay = async (root, groups) => {
      const { applyDigitalLayers } = await import(pathToFileURL(path.resolve(root, 'viewer-gs/gs-edit.js')).href);
      const channels = [new Float32Array(32), new Float32Array(32), new Float32Array(32)];
      const data = { numSplats: 32, getProp: name => channels[Number(name.slice(-1))] };
      const layers = groups.flatMap(group => group.layers.map(layer => ({ preset: layer.preset, strength: layer.strength,
        mask: new Uint8Array(Buffer.from(layer.maskBase64, 'base64')) })));
      applyDigitalLayers({ gsplatData: data, updateColorData: () => {} }, channels.map(channel => channel.slice()), layers);
      return channels;
    };
    const before = await replay(project + '/../' + source, history.groups), after = await replay(project + '/../' + target, restored.groups);
    assert.deepEqual(after, before, 'actual source and receiver tint replays must produce identical float32 colours');
    assert.notEqual(after[1][8], 0);
    history.groups[0].layers[0].strength = .5; json(model.directory + '/portrait.edit.v2.json', history);
    const changed = await packages.prepare(model.id, 'same-ply'); assert.notEqual(changed.packageId, first.packageId);
  }
});
test('legacy saved colour masks migrate to reloadable history; corrupt saved masks never publish', async () => {
  const a = context('legacy-colour'), model = seed(a), mask = Buffer.alloc(32, 1), packages = new SelfTransferPackage(a);
  fs.writeFileSync(model.directory + '/portrait.edit.mask', mask);
  json(model.directory + '/portrait.edit.json', { schemaVersion: 1, assetId: model.id, assetBytes: fs.statSync(model.path).size,
    splatCount: 32, maskChecksum: maskChecksum(mask), preset: 'terracotta', strength: .18 });
  const prepared = await packages.prepare(model.id, 'legacy'), b = context('legacy-colour-target');
  const result = await new SelfTransferPackage(b).importPackage(incoming(b, prepared.path), () => false);
  const restored = JSON.parse(fs.readFileSync(`${b.filesDir}/models/${result.modelId}/portrait.edit.v2.json`, 'utf8'));
  assert.equal(restored.groups[0].layers[0].maskBase64, mask.toString('base64'));
  const { validateEdits } = load('SelfTransferEdits'), history = savedHistory(model);
  const portable = { schema: 'self.transfer.edits', version: 1, plySha256: sha(model.path), assetBytes: history.assetBytes, splatCount: 32, groups: history.groups };
  for (const change of [v => v.splatCount++, v => v.plySha256 = '0'.repeat(64), v => v.groups[0].layers[0].maskChecksum = 'bad',
    v => v.groups[0].layers[0].maskBase64 = Buffer.alloc(31).toString('base64'), v => v.groups[0].layers[0].preset = 'unknown',
    v => v.groups[0].layers[0].strength = 1]) {
    const invalid = structuredClone(portable); change(invalid); assert.throws(() => validateEdits(invalid, history.assetBytes, sha(model.path), 32));
  }
});
test('four code/protocol directions use the receiver adapter independent of producer.variant', async () => {
  for (const source of ['olay', 'olay_harmony']) for (const target of ['olay', 'olay_harmony']) {
    const sourceRoot = `${project}/../${source}`.replaceAll('\\', '/'), targetRoot = `${project}/../${target}`.replaceAll('\\', '/');
    const Source = loader(path.resolve(sourceRoot).replaceAll('\\', '/'))('SelfTransferPackage').SelfTransferPackage;
    const Target = loader(path.resolve(targetRoot).replaceAll('\\', '/'))('SelfTransferPackage').SelfTransferPackage;
    const a = context(`matrix-source-${source}-${target}`), b = context(`matrix-receiver-${source}-${target}`), model = seed(a);
    const p = await new Source(a).prepare(model.id, '1'), receiver = new Target(b), result = await receiver.importPackage(incoming(b, p.path), () => false);
    assert.equal(sha(model.path), sha(`${b.filesDir}/models/${result.modelId}/portrait.gaussian.ply`));
  }
});
test('saved PLY cross-app roundtrips, actual PlayCanvas parser and bounded file processing', { skip: process.env.SELF_TRANSFER_REAL_MODELS !== '1' }, async () => {
  const evidence = [];
  const samples = [
    ['olay', '0670b3d5554e4a456926d09f85ef7553', 'olay_harmony', 'tablet-representative'],
    ['olay_harmony', '07483aca583bd94566a4c115eb87636d', 'olay', 'phone-representative'],
    ['olay_harmony', 'f3a01a5c738d40a00c80d4142c473d06', 'olay_harmony', 'smallest-saved'],
    ['olay_harmony', 'a2cef3813f8864dae0bc9c6f45ea9a81', 'olay', 'largest-saved']
  ];
  for (const [source, id, target, label] of samples) {
    const sourceRoot = path.resolve(project, '..', source).replaceAll('\\', '/'), targetRoot = path.resolve(project, '..', target).replaceAll('\\', '/');
    const real = sourceRoot + '/backend/.data/reconstruction/' + id + '/portrait.gaussian.ply';
    assert.ok(fs.existsSync(real), 'saved fixture must exist: ' + real);
    const Source = loader(sourceRoot)('SelfTransferPackage').SelfTransferPackage, Target = loader(targetRoot)('SelfTransferPackage').SelfTransferPackage;
    const inspect = loader(sourceRoot)('SelfTransferPly').inspectPly;
    const a = context('real-source-' + label), b = context('real-target-' + label), model = seed(a, real), before = await inspect(real);
    const packages=new Source(a);
    const start = performance.now(), base = await packages.prepare(model.id, 'saved'), readyAt = performance.now();
    const prepared=await packages.prepareArrival(base,{schema:'self.transfer.viewer',version:1,camera:[2,1,3],target:[0,0,0],up:[0,1,0],fovDegrees:45}), packedAt = performance.now();
    const result = await new Target(b).importPackage(incoming(b, prepared.path), () => false), importedAt = performance.now();
    const received = `${b.filesDir}/models/${result.modelId}/portrait.gaussian.ply`, after = await inspect(received);
    assert.deepEqual(after, before); assert.equal(sha(real), sha(received));assert.deepEqual(result.arrivalView.camera,[2,1,3]);
    // Expose the unmodified viewer parser's internal readPly for host parsing only; no GPU resource is created.
    const parserFile = targetRoot + '/node_modules/playcanvas/build/playcanvas/src/framework/parsers/ply.js';
    let parserSource = fs.readFileSync(parserFile, 'utf8').replace(/from "(\.[^"]+)"/g, (_, relative) => 'from "' + pathToFileURL(path.resolve(path.dirname(parserFile), relative)).href + '"');
    parserSource += '\nexport { readPly };';
    const { readPly } = await import('data:text/javascript;base64,' + Buffer.from(parserSource).toString('base64'));
    const iterator = fs.createReadStream(received, { highWaterMark: 262144 })[Symbol.asyncIterator]();
    const data = await readPly({ read: async () => { const item = await iterator.next(); return item.done ? { done: true } : { done: false, value: new Uint8Array(item.value) }; } });
    await iterator.return(); assert.equal(data.numSplats, before.vertexCount);
    for (const axis of ['x', 'y', 'z', 'opacity', 'scale_0', 'rot_0', 'f_dc_0']) assert.equal(data.getProp(axis).length, before.vertexCount);
    const entry = { source, target, sample: label, sourcePath: path.relative(sourceRoot, real).replaceAll('\\', '/'), bytes: fs.statSync(real).size,
      sourceSha256: sha(real), receivedSha256: sha(received), match: true, vertexCount: before.vertexCount, min: before.min, max: before.max,
      packMs: Math.round(readyAt - start), capturePackageMs:Math.round(packedAt-readyAt), importMs: Math.round(importedAt - packedAt), viewerParser: 'PlayCanvas 2.22.4 readPly passed; GPU/visual appearance not tested',
      hostPeakRssBytes: process.resourceUsage().maxRSS * 1024, codec: 'Python zipfile desktop double; real official zlib tested separately on devices' };
    evidence.push(entry); console.info('SELF_REAL_MODEL_EVIDENCE ' + JSON.stringify(entry));
  }
  fs.mkdirSync(project + '/docs/evidence', { recursive: true });
  json(project + '/docs/evidence/self-transfer-real-models.json', evidence);
});

test.after(() => fs.rmSync(temporary, { recursive: true, force: true }));

const cameraModules = load('SelfTransferCamera');
const liveCamera = { schema: 'self.transfer.viewer', version: 1, camera: [2, 1, 3], target: [.2, .1, 0], up: [0, 1, 0], fovDegrees: 52, nearClip: .001, farClip: 10000 };
const frontProfile = model => ({ version: 2, resolverVersion: 2, verified: true,
  configHash: cameraModules.PORTRAIT_CONFIG, modelTransformHash: 'identity-ply-v1', renderContractId: 'pc2.22.4-texread-top-down-m0px',
  assetHash: sha(model.path), sourceKind: 'capture-reference', inputVersion: 'private-source-input', referenceFrameKey: 'private-source-frame',
  framingSource: 'face-only', pivot: [0, 0, 0], front: [0, 0, 1], up: [0, 1, 0], headHalf: { x: .3, u: .4, f: .2 },
  fitDistance: 1.8, fitFovY: 60, fitAspect: .5, sceneR: 3 });
test('four directions preserve current view once, durable verified front, saved edits and name independently', async () => {
  for (const source of ['olay', 'olay_harmony']) for (const target of ['olay', 'olay_harmony']) {
    const a = context('camera-source-' + source + target), b = context('camera-target-' + source + target), model = seed(a);
    const originalView = JSON.parse(fs.readFileSync(model.directory + '/portrait.view.json', 'utf8'));
    originalView.assetSha256 = sha(model.path); originalView.portraitView = frontProfile(model);
    json(model.directory + '/portrait.view.json', originalView); json(model.directory + '/portrait.edit.v2.json', savedHistory(model));
    const Source = loader(project + '/../' + source)('SelfTransferPackage').SelfTransferPackage;
    const targetLoader = loader(project + '/../' + target), Target = targetLoader('SelfTransferPackage').SelfTransferPackage;
    const packages = new Source(a), base = await packages.prepare(model.id, 'same'), baseHash = sha(base.path);
    const outgoing = await packages.prepareArrival(base, liveCamera);
    assert.notEqual(outgoing.packageId, base.packageId); assert.equal(sha(base.path), baseHash, 'published base archive stays immutable');
    assert.equal(fs.existsSync(base.exportDirectory + '/viewer/arrival_view.json'), false);
    const recipient = new Target(b), received = await recipient.importPackage(incoming(b, outgoing.path), () => false);
    assert.deepEqual(received.arrivalView, liveCamera); assert.equal(received.name, '测试星辰');
    const stored = JSON.parse(fs.readFileSync(`${b.filesDir}/models/${received.modelId}/portrait.view.json`, 'utf8'));
    assert.deepEqual(stored.camera, [0, 0, 1.8]); assert.notDeepEqual(stored.camera, liveCamera.camera);
    assert.equal(stored.portraitView.sourceKind, 'self-transfer'); assert.equal('inputVersion' in stored.portraitView, false);
    assert.equal('referenceFrameKey' in stored.portraitView, false); assert.equal('transferArrivalView' in stored, false);
    const session = targetLoader('SelfTransferCamera').SelfTransferCameraSession;
    session.arrive(received.modelId, received.arrivalView);
    assert.deepEqual(session.take(received.modelId), liveCamera); assert.equal(session.take(received.modelId), undefined, 'later open uses only durable view');
    const duplicate = await recipient.importPackage(incoming(b, outgoing.path), () => false);
    assert.equal(duplicate.modelId, received.modelId); assert.deepEqual(duplicate.arrivalView, liveCamera);
    const reexported = await recipient.prepare(received.modelId, 'again');
    const onward = context('camera-onward-' + source + target);
    const next = await new Source(onward).importPackage(incoming(onward, reexported.path), () => false);
    assert.equal(next.arrivalView, undefined, 'previous arrival cannot leak into re-export');
    const nextView = JSON.parse(fs.readFileSync(`${onward.filesDir}/models/${next.modelId}/portrait.view.json`, 'utf8'));
    assert.deepEqual(nextView.portraitView, stored.portraitView);
    const second = await packages.prepareArrival(base, { ...liveCamera, camera: [4, 1, 3] });
    const secondReceived = await recipient.importPackage(incoming(b, second.path), () => false);
    assert.deepEqual(secondReceived.arrivalView.camera, [4, 1, 3]);
  }
});
test('capture provider identity and lifetime prevent sending another model camera', async () => {
  const { SelfTransferCameraSession: session } = cameraModules;
  const provider = async () => liveCamera;
  session.register('rendered-model', provider); assert.deepEqual(await session.capture('rendered-model'), liveCamera);
  await assert.rejects(session.capture('other-model'));
  let resolve; const pending = () => new Promise(r => { resolve = r; }); session.register('rendered-model', pending);
  const captured = session.capture('rendered-model'); session.unregister('rendered-model', pending); resolve(liveCamera);
  await assert.rejects(captured, /页面已改变/);
  session.register('rendered-model', provider); session.unregister('rendered-model', pending);
  assert.deepEqual(await session.capture('rendered-model'), liveCamera); session.unregister('rendered-model', provider);
});
test('corrupt or mismatched verified front cannot publish; profile changes invalidate prepared cameras', async () => {
  const a = context('camera-corrupt'), model = seed(a), profile = frontProfile(model), packages = new SelfTransferPackage(a);
  const view = JSON.parse(fs.readFileSync(model.directory + '/portrait.view.json', 'utf8')); view.assetSha256 = sha(model.path); view.portraitView = profile;
  json(model.directory + '/portrait.view.json', view);
  const first = await packages.prepare(model.id, 'same');
  profile.fitDistance = 2.4; json(model.directory + '/portrait.view.json', view);
  await assert.rejects(packages.prepareArrival(first, liveCamera), /记录已改变/);
  const second = await packages.prepare(model.id, 'same'); assert.notEqual(first.packageId, second.packageId);
  for (const change of [p => p.assetHash = '0'.repeat(64), p => p.up = [0, 0, 1], p => p.headHalf.u = -1, p => p.fitFovY = 190, p => p.fitAspect = NaN]) {
    const damaged = structuredClone(profile); change(damaged);
    assert.throws(() => cameraModules.validateFrontView({ schema: 'self.transfer.front-view', version: 1, plySha256: sha(model.path), portraitView: damaged }, sha(model.path)));
  }
  for (const change of [v => v.up = [0, 0, 0], v => v.target = v.camera.slice(), v => v.farClip = .0001]) {
    const damaged = structuredClone(liveCamera); change(damaged); await assert.rejects(packages.prepareArrival(second, damaged));
  }
});
test('sender shares the new current camera package and retains its listener until native submission', async () => {
  const a = context('camera-native-sender'), model = seed(a), packages = new SelfTransferPackage(a);
  const bridge = new HarmonyShareBridge(packages.root, 942), coordinator = new TransferCoordinator(bridge, packages);
  bridge.prepareSend = prepared => packages.prepareArrival(prepared, liveCamera);
  coordinator.setForeground(true); coordinator.setSurface({ kind: 'VIEWER', modelId: model.id, revision: 'one' });
  for (let i = 0; i < 200 && coordinator.diagnostic().phase !== 'SEND_READY'; i++) await new Promise(r => setTimeout(r, 5));
  const listener = share.send.get(942); assert.ok(listener); let outgoing;
  let resolveShare; const submitted = new Promise(r => { resolveShare = r; });
  listener({ reject: async () => { throw Error('ready sender rejected'); }, share: async data => { outgoing = data.record; assert.equal(share.send.get(942), listener); await submitted; } });
  for (let i = 0; i < 200 && !outgoing; i++) await new Promise(r => setTimeout(r, 5));
  assert.ok(outgoing); assert.equal(coordinator.diagnostic().phase, 'TRANSFERRING');
  const b = context('camera-native-receiver'), received = await new SelfTransferPackage(b).importPackage(incoming(b, fileURLToPath(outgoing.uri)), () => false);
  assert.deepEqual(received.arrivalView, liveCamera); assert.equal(received.packageId, outgoing.extraData.packageId);
  resolveShare(); await flush(); coordinator.dispose();
});
test('both engineering trees keep identical transfer contracts and camera helpers', () => {
  const counterpart=path.resolve(project,'..',path.basename(project)==='olay'?'olay_harmony':'olay').replaceAll('\\','/');
  for (const name of fs.readdirSync(project + '/entry/src/main/ets/transfer').filter(n => n.endsWith('.ets'))) {
    assert.equal(fs.readFileSync(project + '/entry/src/main/ets/transfer/' + name, 'utf8').replaceAll('\r\n', '\n'),
      fs.readFileSync(counterpart + '/entry/src/main/ets/transfer/' + name, 'utf8').replaceAll('\r\n', '\n'), name);
  }
  for (const name of ['transfer-camera.js', 'transfer-camera-math.js']) assert.equal(fs.readFileSync(project + '/viewer-gs/' + name, 'utf8'), fs.readFileSync(counterpart + '/viewer-gs/' + name, 'utf8'));
});

test('recorded pitch-limited front keeps its status and persists without repeating analysis', async () => {
  const a=context('camera-pitch-sender'), b=context('camera-pitch-receiver'), model=seed(a), profile=frontProfile(model);
  profile.verified=false;profile.pitchLimited=true;profile.confidence='visible-face-pitch-limited';profile.attemptVersion='source-reference-r4-pitch-fallback-20261006';
  json(model.directory+'/portrait.fallback.json',profile);
  const packages=new SelfTransferPackage(a), base=await packages.prepare(model.id,'fallback'), outgoing=await packages.prepareArrival(base,liveCamera);
  const result=await new SelfTransferPackage(b).importPackage(incoming(b,outgoing.path),()=>false);
  const directory=b.filesDir+'/models/'+result.modelId, stored=JSON.parse(fs.readFileSync(directory+'/portrait.view.json','utf8'));
  assert.equal(stored.portraitView,undefined);assert.equal(stored.portraitFallback.verified,false);assert.equal(stored.portraitFallback.pitchLimited,true);
  assert.equal(stored.portraitFallback.attemptVersion,profile.attemptVersion);assert.equal(stored.portraitFallback.assetHash,sha(model.path));
  assert.equal(JSON.parse(fs.readFileSync(directory+'/portrait.fallback.json','utf8')).sourceKind,'self-transfer');
  assert.deepEqual(result.arrivalView,liveCamera);
});

test('ArkWeb JSON-encoded string result yields the same validated camera as an object result',()=>{
  const {parseWebCameraResult,cameraReadDiagnostic}=cameraModules;
  assert.deepEqual(parseWebCameraResult(JSON.stringify(JSON.stringify(liveCamera))),liveCamera);
  assert.equal(cameraReadDiagnostic().encoding,'json-string');assert.equal(cameraReadDiagnostic().valid,true);
  assert.deepEqual(parseWebCameraResult(JSON.stringify(liveCamera)),liveCamera);
  assert.equal(cameraReadDiagnostic().encoding,'json-object');
  for(const value of ['null','undefined','"null"','"undefined"','{}',JSON.stringify(JSON.stringify({...liveCamera,up:[0,0,0]}))])assert.throws(()=>parseWebCameraResult(value));
});
test('failed touch preparation restores the native sender for a second touch on the same model',async()=>{
  const ctx=context('camera-failure-recovery'),model=seed(ctx),packages=new SelfTransferPackage(ctx);
  const bridge=new HarmonyShareBridge(packages.root,954),coordinator=new TransferCoordinator(bridge,packages);
  let attempts=0;bridge.prepareSend=async prepared=>{if(++attempts===1)throw new contract.PackageValidationError('当前视角读取失败');return packages.prepareArrival(prepared,liveCamera);};
  coordinator.setForeground(true);coordinator.setSurface({kind:'VIEWER',modelId:model.id,revision:'same'});
  const ready=async()=>{for(let i=0;i<200&&coordinator.diagnostic().phase!=='SEND_READY';i++)await new Promise(r=>setTimeout(r,5));assert.equal(coordinator.diagnostic().phase,'SEND_READY');};
  await ready();let rejected=0,shared=0;
  const target={reject:async()=>{rejected++;},share:async()=>{shared++;}};
  share.send.get(954)(target);await flush();await ready();
  assert.equal(rejected,1);assert.equal(shared,0);assert.equal(bridge.diagnostic().sendRegistered,true);
  assert.match(bridge.diagnostic().lastSendError,/当前视角读取失败/);
  share.send.get(954)(target);
  for(let i=0;i<200&&shared===0;i++)await new Promise(r=>setTimeout(r,5));
  assert.equal(shared,1);await flush();await ready();assert.equal(bridge.diagnostic().sendRegistered,true);coordinator.dispose();
});
test('leaving the model during failed camera preparation rearms reception, not the obsolete sender',async()=>{
  const port=fakeTransport(),coordinator=new TransferCoordinator(port,fakeModels());
  coordinator.setForeground(true);coordinator.setSurface({kind:'VIEWER',modelId:'one',revision:'same'});await flush();
  const fail=port.error;assert.equal(port.begin(),true);
  coordinator.setSurface({kind:'HOME',modelId:'',revision:''});fail(new Error('model changed'));
  await flush();assert.equal(coordinator.diagnostic().phase,'RECEIVE_READY');assert.equal(port.mode,'RECEIVE');coordinator.dispose();
});
