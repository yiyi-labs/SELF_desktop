// A lasso becomes weights on immutable Gaussian IDs. The weights stay on the
// same 3D points when the camera moves; no screen-space tint is composited.
const SH_C0 = 0.28209479177387814;
const clamp = (v, low, high) => Math.max(low, Math.min(high, v));
// Keep these digital preview colors identical to backend/contracts.py PRESETS
// and the existing native PolicyEngine. They are not OLAY product profiles.
export const DIGITAL_PRESETS = Object.freeze({rose:[.66,.12,.30],terracotta:[.65,.25,.18]});

// Exact port of the PlayCanvas engine GSplatData.calcMortonOrder (2.22.x):
// the gsplat loader reorders every property of an UNCOMPRESSED ply with
// storage[l] = fileStorage[order[l]] unless the caller disables it. Our app
// loads raw portrait.gaussian.ply, so the loaded-domain order IS this
// permutation. Any "first N file rows" contract must go through it.
export function mortonOrderOf(data) {
  const part = w => { w &= 1023; w = (w ^ w << 16) & 4278190335; w = (w ^ w << 8) & 50393103; w = (w ^ w << 4) & 51130563; w = (w ^ w << 2) & 153391689; return w; };
  const code = (x, y, z) => (part(z) << 2) + (part(y) << 1) + part(x);
  const s = data.getProp('x'), i = data.getProp('y'), r = data.getProp('z');
  const extent = a => { let min = a[0], max = a[0]; for (let k = 1; k < a.length; k++) { if (a[k] < min) min = a[k]; if (a[k] > max) max = a[k]; } return { min, max }; };
  const { min: x0, max: x1 } = extent(s), { min: y0, max: y1 } = extent(i), { min: z0, max: z1 } = extent(r);
  const ux = x0 === x1 ? 0 : 1024 / (x1 - x0), uy = y0 === y1 ? 0 : 1024 / (y1 - y0), uz = z0 === z1 ? 0 : 1024 / (z1 - z0);
  const buckets = new Map();
  for (let n = 0; n < data.numSplats; n++) {
    const cx = Math.min(1023, Math.floor((s[n] - x0) * ux));
    const cy = Math.min(1023, Math.floor((i[n] - y0) * uy));
    const cz = Math.min(1023, Math.floor((r[n] - z0) * uz));
    const c = code(cx, cy, cz);
    const b = buckets.get(c); if (b) b.push(n); else buckets.set(c, [n]);
  }
  const keys = Array.from(buckets.keys()).sort((a, b) => a - b);
  const order = new Uint32Array(data.numSplats); let v = 0;
  for (const k of keys) for (const idx of buckets.get(k)) order[v++] = idx;
  return order;
}

// The editable set for the app: given the Morton order P that the engine
// WILL apply while loading the raw file (storageLoaded[l]=storageFile[P[l]],
// validated element-identical against playcanvas 2.22.4 calcMortonOrder),
// the editable loaded indices are exactly {l : P[l] < editableSplats}.
// P must be computed from FILE-ORDER properties (pre-fetch the PLY), never
// from the already-reordered resource: Morton-sorting the reordered data
// yields the identity, not the inverse.
export function editableSetFromOrder(order, editableSplats) {
  if (!(order instanceof Uint32Array) || !Number.isInteger(editableSplats) || editableSplats < 1)
    throw Error('面容与场景范围不匹配');
  const hits = [];
  for (let l = 0; l < order.length; l++) if (order[l] < editableSplats) hits.push(l);
  return Uint32Array.from(hits);
}

// Loaded-domain indices whose FILE row is inside the editable prefix
// (view.json editableSplats). ONLY valid when `data` is still in FILE order
// (e.g. the loader was told reorder:false); see editableSetFromOrder for the
// default-reorder path.
export function editableLoadedIndices(data, editableSplats) {
  if (!Number.isInteger(editableSplats) || editableSplats < 1 || editableSplats > data.numSplats)
    throw Error('面容与场景范围不匹配');
  return editableSetFromOrder(mortonOrderOf(data), editableSplats);
}

// A new stroke normally replaces the most recent unsent region. The user must
// explicitly arm another slot to keep multiple regions in one request.
export function selectionSlot(length,append,max=4) {
  if(!Number.isInteger(length)||length<0||length>max)throw Error('圈选数量不正确');
  if(append&&length>=max)throw Error('一次最多圈选四处；可以先完成这一组');
  return append?length:Math.max(0,length-1);
}

export function shouldRecordLassoPoint(previous,point,spacing=3) {
  return !!previous&&Number.isFinite(point.x)&&Number.isFinite(point.y)&&
    Math.hypot(point.x-previous.x,point.y-previous.y)>spacing;
}

export function insidePolygon(x, y, points) {
  let inside = false;
  for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
    const a = points[i], b = points[j];
    if ((a.y > y) !== (b.y > y) && x < (b.x - a.x) * (y - a.y) / (b.y - a.y) + a.x) inside = !inside;
  }
  return inside;
}

// A short diagonal touch drag is a quick oval selection; an actual closed pen
// stroke keeps its freely drawn contour. This also avoids tiny accidental
// triangles when touch sampling is sparse.
export function normalizeLasso(points) {
  if (points.length < 2) return points;
  const xs = points.map(p => p.x), ys = points.map(p => p.y);
  const left = Math.min(...xs), right = Math.max(...xs), top = Math.min(...ys), bottom = Math.max(...ys);
  const box = (right - left) * (bottom - top);
  if (box < 60 * 60) return points;
  let twiceArea = 0;
  for (let i = 0; i < points.length; i++) {
    const a = points[i], b = points[(i + 1) % points.length];
    twiceArea += a.x * b.y - b.x * a.y;
  }
  if (Math.abs(twiceArea) / 2 > box * .1) return points;
  return Array.from({length:48}, (_,i) => {
    const t = i * Math.PI * 2 / 48;
    return {x:(left + right) / 2 + (right - left) * .5 * Math.cos(t),
      y:(top + bottom) / 2 + (bottom - top) * .5 * Math.sin(t)};
  });
}

function edgeDistance(x, y, points) {
  let nearest = Infinity;
  for (let i = 0; i < points.length; i++) {
    const a = points[i], b = points[(i + 1) % points.length];
    const dx = b.x - a.x, dy = b.y - a.y;
    const t = clamp(((x - a.x) * dx + (y - a.y) * dy) / Math.max(1e-8, dx * dx + dy * dy), 0, 1);
    nearest = Math.min(nearest, Math.hypot(x - (a.x + t * dx), y - (a.y + t * dy)));
  }
  return nearest;
}

export function selectVisibleSplats({data, polygon, target, cameraPosition, project, width, height, editableIndices, editableCount=data.numSplats}) {
  if (polygon.length < 5 || polygon.length > 512 || !polygon.every(p => Number.isFinite(p.x) && Number.isFinite(p.y))) throw Error('圈选轨迹不完整');
  const count = data.numSplats;
  // editableIndices is the real editable set in loaded order (see
  // editableLoadedIndices). editableCount remains as the legacy prefix
  // contract for callers that have not adopted identity mapping.
  const scan = editableIndices instanceof Uint32Array ? editableIndices : null;
  if (!scan) {
    if(!Number.isInteger(editableCount)||editableCount<1||editableCount>count)
      throw Error('面容与场景范围不匹配');
  } else if (scan.length > count || scan.some(v => v >= count)) {
    throw Error('面容与场景范围不匹配');
  }
  const x = data.getProp('x'), y = data.getProp('y'), z = data.getProp('z'), opacity = data.getProp('opacity');
  if (!x || !y || !z || !opacity || count > 2000000) throw Error('模型缺少可编辑的立体点');
  const direction = target.map((v, i) => v - cameraPosition[i]);
  const distance = Math.hypot(...direction);
  if (!Number.isFinite(distance) || distance < .01) throw Error('模型视角不完整');
  const forward = direction.map(v => v / distance);
  const radius = distance * .32;
  const candidates = [];
  const bins = new Map();
  const total = scan ? scan.length : editableCount;
  for (let k = 0; k < total; k++) {
    const i = scan ? scan[k] : k;
    const dx = x[i] - target[0], dy = y[i] - target[1], dz = z[i] - target[2];
    if (dx * dx + dy * dy + dz * dz > radius * radius) continue;
    const a = data.activated ? opacity[i] : 1 / (1 + Math.exp(-opacity[i]));
    if (a < .12) continue;
    const depth = (x[i] - cameraPosition[0]) * forward[0] + (y[i] - cameraPosition[1]) * forward[1] + (z[i] - cameraPosition[2]) * forward[2];
    if (depth < .02) continue;
    const p = project(x[i], y[i], z[i]);
    if (!Number.isFinite(p.x) || !Number.isFinite(p.y) || p.x < 0 || p.x >= width || p.y < 0 || p.y >= height) continue;
    // Estimate the front shell from nearby high-opacity points before looking
    // at the lasso. This excludes occluded room splats and the back of a head.
    const key = `${Math.floor(p.x / 18)},${Math.floor(p.y / 18)}`;
    if (!bins.has(key)) bins.set(key, []);
    bins.get(key).push(depth);
    if (insidePolygon(p.x, p.y, polygon)) candidates.push({i, x:p.x, y:p.y, depth, key});
  }
  for (const values of bins.values()) values.sort((a, b) => a - b);
  const mask = new Uint8Array(count);
  let selected = 0;
  for (const p of candidates) {
    const depths = bins.get(p.key);
    const front = depths[Math.min(depths.length - 1, Math.floor(depths.length * .18))];
    if (p.depth > front + distance * .075) continue;
    const feather = clamp(edgeDistance(p.x, p.y, polygon) / Math.max(8, Math.min(width, height) * .018), 0, 1);
    const weight = Math.round(255 * feather);
    if (weight > 0) { mask[p.i] = weight; selected++; }
  }
  const editableTotal = scan ? scan.length : editableCount;
  if (selected < 28) throw Error('这里的立体细节较少，稍稍圈大一点再试');
  if (selected > editableTotal * .6) throw Error('范围太宽了，缩小一点再试');
  return {mask, selected};
}

export function makeOriginalColors(data) {
  return ['f_dc_0', 'f_dc_1', 'f_dc_2'].map(name => Float32Array.from(data.getProp(name)));
}

export function applyDigitalTint(resource, original, mask, preset, strength) {
  const data = resource.gsplatData;
  if (mask.length !== data.numSplats || original.some(channel => channel.length !== mask.length)) throw Error('圈选和模型不匹配');
  if (!Number.isFinite(strength) || strength < 0 || strength > .5 || !Array.isArray(preset) || preset.length !== 3) throw Error('颜色参数不正确');
  const channels = ['f_dc_0', 'f_dc_1', 'f_dc_2'].map(name => data.getProp(name));
  for (let c = 0; c < 3; c++) channels[c].set(original[c]);
  for (let i = 0; i < mask.length; i++) {
    if (!mask[i]) continue;
    // The previous .54 mapping made even a medium preview almost invisible
    // once translucent splats overlapped. Keep the three planner levels
    // perceptible while capping the blend so source shading remains visible.
    const amount = (mask[i] / 255) * Math.min(.74, strength * 1.5);
    for (let c = 0; c < 3; c++) {
      const base = clamp(.5 + original[c][i] * SH_C0, 0, 1);
      // Preserve much of the source's shading/texture instead of painting a
      // flat brand-colour patch. SH and opacity are left untouched.
      const destination = clamp(base + (preset[c] - base) * amount, 0, 1);
      channels[c][i] = original[c][i] + (destination - base) / SH_C0;
    }
  }
  resource.updateColorData(data);
}

/** Replays committed layers in order from immutable source colours. Never tint a
 * previously tinted buffer in place: a removed layer must leave no residue. */
export function applyDigitalLayers(resource, original, layers) {
  const data=resource.gsplatData, count=data.numSplats;
  if (!Array.isArray(layers) || layers.length>16 || original.some(channel=>channel.length!==count)) throw Error('编辑记录与模型不匹配');
  const channels=['f_dc_0','f_dc_1','f_dc_2'].map(name=>data.getProp(name));
  for(let c=0;c<3;c++)channels[c].set(original[c]);
  for(const layer of layers){
    const {mask,preset,strength}=layer;
    if(!(mask instanceof Uint8Array)||mask.length!==count||!Object.hasOwn(DIGITAL_PRESETS,preset)||
      ![.18,.32,.5].includes(strength))throw Error('编辑层参数不正确');
    const color=DIGITAL_PRESETS[preset];
    for(let i=0;i<count;i++){
      if(!mask[i])continue;
      const amount=(mask[i]/255)*Math.min(.74,strength*1.5);
      for(let c=0;c<3;c++){
        const base=clamp(.5+channels[c][i]*SH_C0,0,1);
        channels[c][i]+=(clamp(base+(color[c]-base)*amount,0,1)-base)/SH_C0;
      }
    }
  }
  resource.updateColorData(data);
}

/** A reversible, clearly labelled visual scenario on the selected 3D points.
 * It is deliberately independent of product claims: no OLAY calibration or
 * therapeutic acne response is inferred from this colour illustration. */
export function applyCareScenario(resource, original, layers, masks, progress) {
  applyDigitalLayers(resource, original, layers);
  if (!Number.isFinite(progress) || progress < 0 || progress > 1) throw Error('观察进度不正确');
  if (progress === 0) return;
  const data=resource.gsplatData, count=data.numSplats;
  if (!Array.isArray(masks) || masks.length < 1 || masks.length > 4 ||
      masks.some(mask=>!(mask instanceof Uint8Array)||mask.length!==count)) throw Error('观察范围与模型不匹配');
  const channels=['f_dc_0','f_dc_1','f_dc_2'].map(name=>data.getProp(name));
  for(let i=0;i<count;i++){
    let weight=0;for(const mask of masks)weight=Math.max(weight,mask[i]);
    if(weight===0)continue;
    const amount=progress*weight/255;
    const rgb=channels.map(channel=>clamp(.5+channel[i]*SH_C0,0,1));
    // Retain shading and freckles. Only temper excess red slightly and add a
    // restrained overall lift; coordinates, opacity, SH detail stay intact.
    const redExcess=Math.max(0,rgb[0]-(rgb[1]+rgb[2])*.5-.04);
    const next=[rgb[0]+amount*(.012-Math.min(.07,redExcess*.35)),
      rgb[1]+amount*.012,rgb[2]+amount*.012];
    for(let c=0;c<3;c++)channels[c][i]+=(clamp(next[c],0,1)-rgb[c])/SH_C0;
  }
  resource.updateColorData(data);
}
