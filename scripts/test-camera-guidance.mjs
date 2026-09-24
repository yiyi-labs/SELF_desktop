import assert from 'node:assert/strict';
import { build } from 'esbuild';

async function loadArkTs(file) {
  const result = await build({entryPoints:[file],bundle:true,write:false,platform:'node',format:'cjs',loader:{'.ets':'ts'},resolveExtensions:['.ets','.ts','.js'],logLevel:'silent'});
  const module = {exports:{}};
  new Function('module','exports',result.outputFiles[0].text)(module,module.exports);
  return module.exports;
}

const {FaceAnchorTracker} = await loadArkTs('entry/src/main/ets/services/FaceAnchorTracker.ets');
const {ViewCoverageGuide,VIEW_ANGLES} = await loadArkTs('entry/src/main/ets/services/ViewCoverageGuide.ets');
const {faceParticle} = await loadArkTs('entry/src/main/ets/services/FaceParticleField.ets');
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
const stable = new FaceAnchorTracker();
for (const at of [100,220,340]) stable.update([detected(.5,.5,at)],at,1.7);
const driftingNose=detected(.5,.5,460);
driftingNose.landmarks[2].x+=.025;
const suppressed=stable.update([driftingNose],460,1.7);
assert.ok(Math.abs(suppressed.x-.5)<.006,'nose-only landmark jitter should not drag the locked marker');
const translated=detected(.52,.5,580);
const followed=stable.update([translated],580,1.7);
assert.ok(followed.x>suppressed.x,'coherent eye-and-nose movement must still be followed');
const badInitial=new FaceAnchorTracker();
assert.equal(badInitial.update([detected(.5,.5,100)],100,1.7).locked,false);
const unstableFit=detected(.5,.5,220);
for(const index of [0,1,3,4])unstableFit.landmarks[index].x+=.12;
assert.equal(badInitial.update([unstableFit],220,1.7).locked,false);
assert.equal(badInitial.update([detected(.5,.5,340)],340,1.7).locked,false,
  'a stable nose alone must not complete the initial lock');
assert.equal(badInitial.update([detected(.5,.5,460)],460,1.7).locked,false);
assert.equal(badInitial.update([detected(.5,.5,580)],580,1.7).locked,true);

const guide = new ViewCoverageGuide();
assert.equal(VIEW_ANGLES.length,11);
const tracked = (yaw,at) => ({x:.5,y:.5,width:.3,height:.4,roll:0,yaw,locked:true,observed:true,confidence:.9,poseYaw:yaw,poseSampleAt:at});
assert.equal(guide.update({...tracked(0,80),x:.05},true,false).count,0,'cropped face cannot earn a view');
assert.equal(guide.update(tracked(0,100),false,false).count,0,'preview does not count as captured');
assert.equal(guide.state().active,5,'current-angle pointer moves during preview too');
assert.equal(guide.update(tracked(1,200),true,false).count,0);
assert.equal(guide.update(tracked(1,200),true,false).count,0,'cached pose cannot advance coverage');
assert.equal(guide.update(tracked(2,520),true,false).count,1);
assert.equal(guide.update(tracked(-35,900),true,false).count,1);
assert.equal(guide.update(tracked(-36,1250),true,false).count,1,'boundary sample does not earn a view');
assert.equal(guide.update(tracked(-39,1600),true,false).count,1);
assert.equal(guide.update(tracked(-40,1950),true,false).count,2);
const mirrored = guide.update(tracked(50,2300),true,true);
assert.equal(mirrored.active,0,'front mirroring flips the displayed side');
assert.equal(mirrored.count,2,'a previously covered side is not counted twice');
assert.equal(guide.update(tracked(50,2650),true,true).count,3,'a fresh stable pose lights a finer-angle cell');
assert.equal(guide.update(undefined,true,false).count,3,'brief loss retains earned coverage');
assert.ok(Math.abs(guide.state().angle)<=50);
assert.equal(faceParticle(0,0).opacity>0,true);
assert.equal(faceParticle(0,45).x!==faceParticle(0,0).x,true,'visual points project differently as yaw changes');
assert.ok(faceParticle(0,0).opacity<.5,'particle overlay stays translucent');

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
console.log('Camera guidance: lock, coherent motion, nose jitter, 11-view coverage, curved visual guide, portrait/landscape transforms passed.');
