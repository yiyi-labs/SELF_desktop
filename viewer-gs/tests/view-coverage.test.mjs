import test from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';

const bundle=await build({entryPoints:['entry/src/main/ets/services/ViewCoverageGuide.ets'],
  bundle:true,write:false,format:'esm',platform:'node',loader:{'.ets':'ts'},resolveExtensions:['.ets','.ts','.js']});
const {ViewCoverageGuide,VIEW_ANGLES}=await import('data:text/javascript;base64,'+
  Buffer.from(bundle.outputFiles[0].text).toString('base64'));

const face=(yaw,at)=>({x:.5,y:.5,width:.3,height:.4,roll:0,yaw,locked:true,
  observed:true,confidence:.9,poseYaw:yaw,poseSampleAt:at});

test('optional side sectors need fresh, reliable face pose',()=>{
  assert.deepEqual(VIEW_ANGLES,[-60,-50,-40,-30,-20,-10,0,10,20,30,40,50,60]);
  const guide=new ViewCoverageGuide();
  assert.equal(guide.update(face(60,1000),true,false).count,0);
  assert.equal(guide.update(face(60,1300),true,false).covered[12],true);
  const count=guide.state().count;
  assert.equal(guide.update({...face(60,1600),observed:false},true,false).count,count);
  assert.equal(guide.update(face(70,1900),true,false).count,count);
  assert.equal(guide.update(face(-60,2200),true,false).covered[0],false);
  assert.equal(guide.update(face(-60,2500),true,false).covered[0],true);
});
