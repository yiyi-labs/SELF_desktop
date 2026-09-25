// A lasso becomes weights on immutable Gaussian IDs. The weights stay on the
// same 3D points when the camera moves; no screen-space tint is composited.
const SH_C0 = 0.28209479177387814;
const clamp = (v, low, high) => Math.max(low, Math.min(high, v));
// Keep these digital preview colors identical to backend/contracts.py PRESETS
// and the existing native PolicyEngine. They are not OLAY product profiles.
export const DIGITAL_PRESETS = Object.freeze({rose:[.66,.12,.30],terracotta:[.65,.25,.18]});

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

export function selectVisibleSplats({data, polygon, target, cameraPosition, project, width, height}) {
  if (polygon.length < 5 || polygon.length > 512 || !polygon.every(p => Number.isFinite(p.x) && Number.isFinite(p.y))) throw Error('圈选轨迹不完整');
  const count = data.numSplats;
  const x = data.getProp('x'), y = data.getProp('y'), z = data.getProp('z'), opacity = data.getProp('opacity');
  if (!x || !y || !z || !opacity || count > 2000000) throw Error('模型缺少可编辑的立体点');
  const direction = target.map((v, i) => v - cameraPosition[i]);
  const distance = Math.hypot(...direction);
  if (!Number.isFinite(distance) || distance < .01) throw Error('模型视角不完整');
  const forward = direction.map(v => v / distance);
  const radius = distance * .32;
  const candidates = [];
  const bins = new Map();
  for (let i = 0; i < count; i++) {
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
  if (selected < 80 || selected > count * .6) throw Error('这里的立体范围还不够明确，请圈小一点再试');
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
