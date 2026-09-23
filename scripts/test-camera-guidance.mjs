import assert from 'node:assert/strict';
import { build } from 'esbuild';

async function loadArkTs(file) {
  const result = await build({entryPoints:[file],bundle:true,write:false,platform:'node',format:'cjs',loader:{'.ets':'ts'},resolveExtensions:['.ets','.ts','.js'],logLevel:'silent'});
  const module = {exports:{}};
  new Function('module','exports',result.outputFiles[0].text)(module,module.exports);
  return module.exports;
}

const {FaceAnchorTracker} = await loadArkTs('entry/src/main/ets/services/FaceAnchorTracker.ets');
const {ViewCoverageGuide} = await loadArkTs('entry/src/main/ets/services/ViewCoverageGuide.ets');
const {previewGeometry,previewPoint} = await loadArkTs('entry/src/main/ets/services/CameraPreviewTransform.ets');

function detected(x=.5,y=.5,at=0) {
  return {confidence:.9,x:x-.15,y:y-.2,width:.3,height:.4,sampleAt:at,
    landmarks:[{x:x-.07,y:y-.08},{x:x+.07,y:y-.08},{x,y},{x:x-.05,y:y+.09},{x:x+.05,y:y+.09}]};
}
const tracker = new FaceAnchorTracker();
const invalid = detected(.5,.5,25);
invalid.landmarks[3].y = .25;
assert.equal(tracker.update([invalid],25,1.7),undefined,'bad facial geometry cannot establish a lock');
assert.equal(tracker.update([detected(.4,.5,50),detected(.6,.5,50)],50,1.7),undefined,'two faces cannot establish a new target');
assert.equal(tracker.update([detected(.5,.5,100)],100,1.7).locked,false);
assert.equal(tracker.update([detected(.501,.5,220)],220,1.7).locked,false);
assert.equal(tracker.update([detected(.5,.501,340)],340,1.7).locked,true);
const held = tracker.update([],440,1.7);
assert.equal(held.locked,true);
assert.equal(held.observed,false);
assert.ok(Math.abs(held.x-.5)<.02);
const outlier = tracker.update([detected(.81,.5,550)],550,1.7);
assert.equal(outlier.observed,false);
assert.ok(Math.abs(outlier.x-.5)<.02);
const moved = tracker.update([detected(.53,.5,620)],620,1.7);
assert.equal(moved.observed,true);
assert.ok(Math.abs(moved.x-held.x)<.04,'locked marker should be step-limited');
assert.equal(tracker.update([],1400,1.7),undefined,'long loss must reacquire instead of freezing');
assert.equal(tracker.update([detected(.76,.5,1500)],1500,1.7).locked,false,'a new face after a gap must not inherit the old lock');

const guide = new ViewCoverageGuide();
const tracked = (yaw,at) => ({x:.5,y:.5,width:.3,height:.4,roll:0,yaw,locked:true,observed:true,confidence:.9,poseYaw:yaw,poseSampleAt:at});
assert.equal(guide.update({...tracked(0,80),x:.05},true,false).count,0,'cropped face cannot earn a view');
assert.equal(guide.update(tracked(0,100),false,false).count,0,'preview does not count as captured');
assert.equal(guide.update(tracked(1,200),true,false).count,0);
assert.equal(guide.update(tracked(1,200),true,false).count,0,'cached pose cannot advance coverage');
assert.equal(guide.update(tracked(2,520),true,false).count,1);
assert.equal(guide.update(tracked(-35,900),true,false).count,1);
assert.equal(guide.update(tracked(-34,1250),true,false).count,2);
const mirrored = guide.update(tracked(35,1600),true,true);
assert.equal(mirrored.active,0,'front mirroring flips the displayed side');
assert.equal(mirrored.count,2,'a previously covered side is not counted twice');
assert.equal(guide.update(tracked(34,1940),true,true).count,2,'mirrored right view was already visited as left');
assert.equal(guide.update(undefined,true,false).count,2,'brief loss retains earned coverage');

const portrait = previewGeometry(1920,1080,90,800,1200,true);
assert.equal(portrait.streamWidth,1080);
assert.equal(portrait.streamHeight,1920);
assert.ok(Math.abs(previewPoint(.5,.5,portrait).x)<1e-8);
assert.ok(previewPoint(.2,.5,portrait).x>0,'mirrored front preview maps left analysis to right display');
assert.ok(previewPoint(.2,.5,previewGeometry(1920,1080,90,800,1200,false)).x<0);
assert.ok(previewGeometry(1920,1080,0,1200,800,false).contentWidth>=1200);
for (const rotation of [0,90,180,270]) {
  const geometry = previewGeometry(1920,1080,rotation,800,1200,false);
  assert.deepEqual(previewPoint(.5,.5,geometry),{x:0,y:0},'center stays centered at every rotation');
}
console.log('Camera guidance: lock, dropout, outlier, view coverage, portrait/landscape transforms passed.');
