import test from 'node:test';
import assert from 'node:assert/strict';
import {position,cameraPosition,placeLabels} from '../universe-layout.js';

test('memory route recedes from lower left to upper right in portrait and landscape',()=>{
  for(const aspect of [.46,2/3,1,1.6,2.2])for(let selected=0;selected<200;selected++){
    const eye=cameraPosition(selected,aspect),project=index=>{
      const p=position(index,aspect),depth=eye.z-p.z;
      return {x:.5+(p.x-eye.x)/depth/aspect,y:.5-(p.y-eye.y)/depth,size:1/depth};
    };
    const near=project(selected),far=project(selected+1);
    assert.ok(near.x<.5&&near.y>.5);
    assert.ok(far.x>near.x&&far.y<near.y&&far.size<near.size);
  }
});
test('irregular galaxy offsets never steer or reverse the steady camera path',()=>{
  for(const aspect of [.46,2/3,1.6,2.2])for(let index=0;index<199;index++){
    const a=cameraPosition(index,aspect),b=cameraPosition(index+1,aspect),c=cameraPosition(index+.5,aspect);
    const p=position(index,aspect),q=position(index+1,aspect);
    assert.ok(q.x>p.x&&q.y>p.y&&q.z<p.z);
    for(const axis of ['x','y','z'])assert.ok(Math.abs(c[axis]-(a[axis]+b[axis])/2)<1e-9);
    assert.ok(Math.abs((b.y-a.y)-3.45)<1e-9);
    assert.ok(Math.abs((b.z-a.z)+8.8)<1e-9);
  }
});
test('crowded, long and duplicate names never overlap and selected memory wins',()=>{
  const candidates=Array.from({length:200},(_,index)=>({id:String(index),x:180+index%5*24,y:310+index%6*21,
    width:240,depth:index+10,selected:index===17}));
  const placed=placeLabels(candidates,390,844);
  assert.ok(placed.length<=5);assert.equal(placed[0].id,'17');
  for(const a of placed){
    assert.ok(a.x>=18&&a.x+a.width<=372&&a.y+a.height<=844*.81);
    for(const b of placed)if(a!==b)assert.ok(a.x+a.width<=b.x||b.x+b.width<=a.x||a.y+a.height<=b.y||b.y+b.height<=a.y);
  }
});
