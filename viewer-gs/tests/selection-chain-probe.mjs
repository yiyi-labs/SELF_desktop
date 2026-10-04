// 真实资产的圈选统计链探针：文件序 vs 引擎 Morton 加载序的身份差异。
import { selectVisibleSplats } from '../gs-edit.js';
import { readFileSync } from 'node:fs';

const plyPath = process.argv[2];
const viewPath = process.argv[3];
if (!plyPath || !viewPath) { console.error('usage: node selection-chain-probe.mjs <ply> <view.json>'); process.exit(2); }

function readPly(path) {
  const buf = readFileSync(path);
  let end = buf.indexOf(Buffer.from('end_header\n')) + 'end_header\n'.length;
  const header = buf.subarray(0, end).toString('ascii');
  const count = parseInt(header.match(/element vertex (\d+)/)[1]);
  const fields = [...header.matchAll(/property float (\S+)/g)].map(m => m[1]);
  const rec = buf.subarray(end);
  const byte = fields.length * 4;
  const props = {};
  for (let f = 0; f < fields.length; f++) {
    const arr = new Float32Array(count);
    for (let i = 0; i < count; i++) arr[i] = rec.readFloatLE(i * byte + f * 4);
    props[fields[f]] = arr;
  }
  return { props, count, numSplats: count, getProp: n => props[n] };
}

const data = readPly(plyPath);
const view = JSON.parse(readFileSync(viewPath, 'utf-8'));
console.log('numSplats:', data.numSplats, '| editableSplats(view):', view.editableSplats);

// ==== 引擎 calcMortonOrder 的逐行移植（来自打包引擎反混淆） ====
function engineMortonOrder(data) {
  const part = w => { w &= 1023; w = (w ^ w << 16) & 4278190335; w = (w ^ w << 8) & 50393103; w = (w ^ w << 4) & 51130563; w = (w ^ w << 2) & 153391689; return w; };
  const code = (x, y, z) => (part(z) << 2) + (part(y) << 1) + part(x);
  const s = data.getProp('x'), i = data.getProp('y'), r = data.getProp('z');
  const mm = a => { let min = a[0], max = a[0]; for (let k = 1; k < a.length; k++) { if (a[k] < min) min = a[k]; if (a[k] > max) max = a[k]; } return { min, max }; };
  const { min: ax, max: ao } = mm(s), { min: ay, max: aA } = mm(i), { min: az, max: aB } = mm(r);
  const ux = ax === ao ? 0 : 1024 / (ao - ax), uy = ay === aA ? 0 : 1024 / (aA - ay), uz = az === aB ? 0 : 1024 / (aB - az);
  const buckets = new Map();
  for (let n = 0; n < data.numSplats; n++) {
    const X = Math.min(1023, Math.floor((s[n] - ax) * ux));
    const Y = Math.min(1023, Math.floor((i[n] - ay) * uy));
    const Z = Math.min(1023, Math.floor((r[n] - az) * uz));
    const c = code(X, Y, Z);
    const b = buckets.get(c); if (b) b.push(n); else buckets.set(c, [n]);
  }
  const keys = Array.from(buckets.keys()).sort((p, q) => p - q);
  const S = new Uint32Array(data.numSplats); let v = 0;
  for (const k of keys) for (const idx of buckets.get(k)) S[v++] = idx;
  return S;
}
const S = engineMortonOrder(data);
let identity = 0; for (let l = 0; l < S.length; l++) if (S[l] === l) identity++;
console.log('Morton 置换 vs 恒等: 相同位置数 =', identity, '/', S.length);
// 旧实现（前缀）在 Morton 域里实际覆盖的文件序可编辑点数：
const editableSplats = view.editableSplats;
let prefixHits = 0; for (let l = 0; l < editableSplats; l++) if (S[l] < editableSplats) prefixHits++;
console.log(`旧前缀扫描(前${editableSplats}个加载点)中真正属于可编辑文件域的: ${prefixHits} (${(100 * prefixHits / editableSplats).toFixed(1)}%)`);

// ==== 模拟相机与选区（与 App 同参数体系） ====
const target = view.target, camPos = view.camera;
const width = 720, height = 1600;
const fovY = view.fovDegrees * Math.PI / 180;
const dist = Math.hypot(...target.map((v, i) => v - camPos[i]));
// 把主点放画面中心：project = worldToScreen（以视锥中心近似 App 相机对准 target）
const forward = target.map((v, i) => (v - camPos[i]) / dist);
function project(x, y, z) {
  const rx = x - camPos[0], ry = y - camPos[1], rz = z - camPos[2];
  const depth = rx * forward[0] + ry * forward[1] + rz * forward[2];
  // 以 forward 为光轴的像面坐标（正交基）
  const up0 = [0, 1, 0];
  let right = [forward[1] * up0[2] - forward[2] * up0[1], forward[2] * up0[0] - forward[0] * up0[2], forward[0] * up0[1] - forward[1] * up0[0]];
  const rl = Math.hypot(...right); right = right.map(v => v / rl);
  const up = [forward[1] * right[2] - forward[2] * right[1], forward[2] * right[0] - forward[0] * right[2], forward[0] * right[1] - forward[1] * right[0]];
  const u = rx * right[0] + ry * right[1] + rz * right[2];
  const v = rx * up[0] + ry * up[1] + rz * up[2];
  const f = (height / 2) / Math.tan(fovY / 2);
  return { x: width / 2 + f * u / depth, y: height / 2 - f * v / depth };
}

// 脸部中心投影（target 即脸表面均值）
const c = project(...target);
console.log('脸部投影中心:', c.x.toFixed(0), c.y.toFixed(0));

// ==== 逐级计数（正确身份 = Morton 域中文件序 < editableSplats 的加载点） ====
const editableLoaded = [];
for (let l = 0; l < S.length; l++) if (S[l] < editableSplats) editableLoaded.push(l);
console.log('正确身份的可编辑加载点数:', editableLoaded.length);

const opacity = data.getProp('opacity'), x = data.getProp('x'), y = data.getProp('y'), z = data.getProp('z');
for (const r of [80, 140, 220]) {
  const polygon = Array.from({ length: 48 }, (_, i) => {
    const t = i * Math.PI * 2 / 48;
    return { x: c.x + r * Math.cos(t), y: c.y + r * Math.sin(t) };
  });
  const radius = dist * .32;
  let inRadius = 0, alphaPass = 0, inPoly = 0;
  for (const i of editableLoaded) {
    const dx = x[i] - target[0], dy = y[i] - target[1], dz = z[i] - target[2];
    if (dx * dx + dy * dy + dz * dz > radius * radius) continue; inRadius++;
    const a = 1 / (1 + Math.exp(-opacity[i]));
    if (a < .12) continue; alphaPass++;
    const p = project(x[i], y[i], z[i]);
    if (p.x < 0 || p.x >= width || p.y < 0 || p.y >= height) continue;
    // insidePolygon
    let inside = false;
    for (let k = 0, j = polygon.length - 1; k < polygon.length; j = k++) {
      const A = polygon[k], B = polygon[j];
      if ((A.y > p.y) !== (B.y > p.y) && p.x < (B.x - A.x) * (p.y - A.y) / (B.y - A.y) + A.x) inside = !inside;
    }
    if (inside) inPoly++;
  }
  // 完整 selectVisibleSplats（正确身份，脸颊中心）
  let ok = true, selected = 0, err = '';
  try {
    const res = selectVisibleSplats({ data, polygon, target, cameraPosition: camPos, project, width, height, editableIndices: Uint32Array.from(editableLoaded) });
    selected = res.selected;
  } catch (e) { ok = false; err = e.message; }
  console.log(`中心圆半径${r}px: 选择=${ok ? selected : '失败:' + err}`);
  // 脸颊密集簇圆（真实用户行为）：找正面可编辑点投影最密集处
  const front = editableLoaded.filter(i => {
    const dx=x[i]-target[0],dy=y[i]-target[1],dz=z[i]-target[2];
    return dx*dx+dy*dy+dz*dz <= (dist*.32)**2;
  });
  if (r === 140 && front.length) {
    const pts = front.map(i => project(x[i], y[i], z[i])).filter(p => p.x>=0&&p.x<width&&p.y>=0&&p.y<height);
    // 网格找最密 40px 格
    const grid = new Map();
    for (const p of pts) { const k = `${Math.floor(p.x/40)},${Math.floor(p.y/40)}`; grid.set(k, (grid.get(k)||0)+1); }
    let best='', n=0; for (const [k,v] of grid) if (v>n){n=v;best=k;}
    const [gx,gy]=best.split(',').map(Number);
    const cx=gx*40+20, cy=gy*40+20;
    for (const rr of [60, 100, 140]) {
      const poly = Array.from({length:48},(_,i)=>{const t=i*Math.PI*2/48;return {x:cx+rr*Math.cos(t),y:cy+rr*Math.sin(t)};});
      let ok2=true,s2=0,e2='';
      try { s2 = selectVisibleSplats({data,polygon:poly,target,cameraPosition:camPos,project,width,height,editableIndices:Uint32Array.from(editableLoaded)}).selected; }
      catch(err2){ok2=false;e2=err2.message;}
      console.log(`  密集簇(${cx},${cy}) 半径${rr}px → ${ok2?'选择='+s2:'失败:'+e2}`);
    }
  }
  // 对照：旧前缀身份
  let oldOk = true, oldSelected = 0, oldErr = '';
  try {
    const res = selectVisibleSplats({ data, polygon, target, cameraPosition: camPos, project, width, height, editableCount: editableSplats });
    oldSelected = res.selected;
  } catch (e) { oldOk = false; oldErr = e.message; }
  console.log(`   旧前缀身份 → 选择=${oldOk ? oldSelected : '失败:' + oldErr}`);
}
