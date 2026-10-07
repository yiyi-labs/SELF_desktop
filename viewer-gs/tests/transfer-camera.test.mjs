import test from 'node:test';
import assert from 'node:assert/strict';
import { Quat, Vec3 } from 'playcanvas';
import { snapshotCamera, savedFrontCamera, applyTransferCamera } from '../transfer-camera.js';
import { lookAtBasis, fitOpeningDistance } from '../transfer-camera-math.js';
const approx=(a,b,eps=1e-6)=>a.forEach((v,i)=>assert.ok(Math.abs(v-b[i])<eps, `${a} != ${b}`));
test('live camera preserves actual quaternion orientation, pan, pitch, roll, zoom and FOV',()=>{
  for(const euler of [[0,0,0],[25,80,0],[-70,-120,23],[10,275,-15]]){
    const q=new Quat().setFromEulerAngles(...euler),pos=[3,-2,1],distance=2.7;
    const snap={frame:37,position:pos,rotation:[q.x,q.y,q.z,q.w],distance,fovDegrees:54,nearClip:.001,farClip:10000};
    const actual=snapshotCamera(snap),basis=lookAtBasis(actual.camera,actual.target,actual.up);
    const forward=q.transformVector(new Vec3(0,0,-1)),up=q.transformVector(new Vec3(0,1,0));
    approx(basis.forward,[forward.x,forward.y,forward.z]);approx(basis.upCam,[up.x,up.y,up.z]);
    assert.deepEqual(actual.camera,pos);assert.equal(actual.fovDegrees,54);assert.equal(actual.nearClip,.001);
  }
});
test('saved front uses production projected fit on both portrait and landscape screens without face analysis',()=>{
  const p={version:2,resolverVersion:2,verified:true,sourceKind:'self-transfer',assetHash:'hash',pivot:[.1,.2,.3],front:[0,0,1],up:[0,1,0],
    headHalf:{x:.3,u:.4,f:.15},fitDistance:2,fitFovY:60,fitAspect:.5,framingSource:'face-only'};
  const original={portraitView:p,assetSha256:'hash'};
  for(const [width,height] of [[600,1200],[1600,900],[900,1600]]){
    const v=savedFrontCamera(original,width,height);
    const fit=Math.abs(width/height-p.fitAspect)<=.001?p.fitDistance:fitOpeningDistance({pivot:p.pivot,front:p.front,up:p.up,half:p.headHalf,
      viewport:{width,height},fovY:p.fitFovY,heightFraction:.55,widthFraction:.82}).r;
    approx(v.camera,p.pivot.map((n,i)=>n+p.front[i]*fit));assert.equal(v.fovDegrees,60);
    assert.deepEqual(original.portraitView,p);
  }
});
test('applying arrival leaves durable front untouched; next open recovers saved front',()=>{
  const p={version:2,resolverVersion:2,verified:true,sourceKind:'self-transfer',assetHash:'hash',pivot:[0,0,0],front:[0,0,1],up:[0,1,0],
    headHalf:{x:.3,u:.4,f:.15},fitDistance:2,fitFovY:60,fitAspect:.5,framingSource:'face-only'};
  const saved={portraitView:p,assetSha256:'hash'},session=structuredClone(saved);
  const arrival={schema:'self.transfer.viewer',version:1,camera:[2,1,3],target:[0,0,0],up:[0,1,0],fovDegrees:48};
  assert.equal(applyTransferCamera(session,arrival),true);assert.deepEqual(session.camera,arrival.camera);
  assert.deepEqual(session.portraitView,p);assert.deepEqual(savedFrontCamera(saved,600,1200).camera,[0,0,2]);
  assert.equal(applyTransferCamera(session,{...arrival,up:[0,0,0]}),false);
  assert.equal(savedFrontCamera({...saved,assetSha256:'wrong-model'},600,1200),undefined);
});
