// Execute the button's actual interaction/timer code against a virtual canvas and clock.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {transformSync} from 'esbuild';

const folder=new URL('../../entry/src/main/ets/pages/',import.meta.url);
const trailSource=fs.readFileSync(new URL('PortraitFindTrail.ets',folder),'utf8').replace(/^export /gm,'');
const buttonSource=fs.readFileSync(new URL('PortraitFindButton.ets',folder),'utf8');
const methods=buttonSource.slice(buttonSource.indexOf('  private buttonWidth('),buttonSource.indexOf('  build(){'));
assert.ok(methods.includes('private launch('));
const compiled=transformSync(trailSource+'\nclass FindButton {'+methods+'}\nglobalThis.Trail=PortraitFindTrail;globalThis.Button=FindButton;',
  {loader:'ts',target:'es2020'}).code;
function fixture(motion=true){
  let now=10000,key=0;const scheduled=new Map(),opened=[],painted=[];
  const set=(fn,delay,interval=false)=>{const id=++key;scheduled.set(id,{fn,at:now+delay,delay,interval});return id;};
  const context=vm.createContext({Date:{now:()=>now},TouchType:{Down:0,Move:1,Up:2,Cancel:3},
    setTimeout:(fn,delay)=>set(fn,delay),setInterval:(fn,delay)=>set(fn,delay,true),
    clearTimeout:id=>scheduled.delete(id),clearInterval:id=>scheduled.delete(id)});
  vm.runInContext(compiled,context);const button=new context.Button();
  Object.assign(button,{motion,english:false,active:true,pressed:false,launching:false,prepared:true,
    frameTimer:-1,launchTimer:-1,lastFrame:0,trail:new context.Trail(),onFind:event=>opened.push(event),
    drawing:{clearRect:()=>{},createLinearGradient:()=>({addColorStop:()=>{}}),createRadialGradient:()=>({addColorStop:()=>{}}),beginPath:()=>{},moveTo:()=>{},
      lineTo:(x,y)=>painted.push([x,y]),stroke:()=>{},arc:()=>{},fill:()=>{}}});
  const advance=duration=>{
    const end=now+duration;let ticks=0;
    while(true){
      const next=[...scheduled.entries()].filter(([,entry])=>entry.at<=end).sort((a,b)=>a[1].at-b[1].at)[0];
      if(!next)break;assert.ok(++ticks<10000,'runaway particle timer');now=next[1].at;
      if(next[1].interval)next[1].at+=next[1].delay;else scheduled.delete(next[0]);next[1].fn();
    }now=end;
  };
  return {button,advance,scheduled,opened,painted};
}
test('a ten-second hold emits bounded starlight and every existing particle travels right',()=>{
  const f=fixture(),p=f.button;p.touch({type:0});
  for(let frame=0;frame<625;frame++){
    const before=p.trail.particles.map(light=>({light,x:light.x}));f.advance(16);
    for(const entry of before)assert.ok(entry.light.x>entry.x);
    assert.ok(p.trail.particles.length<=36);
    for(const light of p.trail.particles){
      assert.ok([light.x,light.y,light.speed,light.age,light.life].every(Number.isFinite));
      assert.ok(light.speed>=95&&light.speed<=175,'starlight should drift rather than race');
      assert.ok(light.length<=15,'tails should remain short');
      assert.ok(light.x-light.length>=0&&light.x+light.radius<172&&light.y-light.radius>0&&light.y+light.radius<54,
        'particles must remain inside the button');
    }
  }
  assert.equal(p.pressed,true);assert.equal(f.scheduled.size,1);assert.equal(f.opened.length,0);assert.ok(f.painted.length>1000);
  p.touch({type:2});p.launch({kind:'release'});f.advance(279);assert.equal(f.opened.length,0);
  f.advance(1);assert.equal(f.opened.length,1);assert.equal(f.scheduled.size,0);assert.equal(p.launching,false);
});
test('short taps and keyboard clicks open once after the visible tail, with no timer left behind',()=>{
  for(const useTouch of [true,false]){
    const f=fixture(),p=f.button,event={kind:'click'};
    if(useTouch){p.touch({type:0});f.advance(40);p.touch({type:2});}
    p.launch(event);p.launch({kind:'duplicate'});f.advance(1000);
    assert.deepEqual(f.opened,[event]);assert.equal(f.scheduled.size,0);assert.equal(p.trail.particles.length,0);
  }
});
test('cancelled touch fades out and never starts the camera',()=>{
  const f=fixture(),p=f.button;p.touch({type:0});f.advance(200);p.touch({type:3});
  assert.equal(p.pressed,false);assert.equal(p.immersed(),false);assert.ok(p.trail.particles.length>0);f.advance(1400);
  assert.equal(f.opened.length,0);assert.equal(f.scheduled.size,0);assert.equal(p.trail.particles.length,0);
});
test('press enters the dark star field immediately and stays immersed until opening',()=>{
  const f=fixture(),p=f.button;assert.equal(p.immersed(),false);
  p.touch({type:0});assert.equal(p.immersed(),true);f.advance(2000);
  assert.equal(p.immersed(),true);assert.ok(p.trail.particles.length>0);assert.equal(f.opened.length,0);
  p.touch({type:2});p.launch({kind:'release'});assert.equal(p.immersed(),true);
  f.advance(280);assert.equal(f.opened.length,1);assert.equal(p.immersed(),false);
});
test('leaving the page or going into the background cancels a pending camera launch',()=>{
  for(const disappear of [true,false]){
    const f=fixture(),p=f.button;p.launch({kind:'click'});f.advance(120);
    if(disappear)p.aboutToDisappear();else{p.active=false;p.activeChanged();}
    f.advance(1000);assert.equal(f.opened.length,0);assert.equal(f.scheduled.size,0);
    assert.equal(p.pressed,false);assert.equal(p.launching,false);assert.equal(p.trail.particles.length,0);
  }
});
test('reduced motion opens immediately and never starts particle frames',()=>{
  const f=fixture(false),p=f.button;p.touch({type:0});f.advance(3000);
  assert.equal(f.scheduled.size,0);assert.equal(p.trail.particles.length,0);p.touch({type:2});p.launch({kind:'click'});
  assert.equal(f.opened.length,1);assert.equal(p.launching,false);assert.equal(f.scheduled.size,0);
});
test('returning from the camera leaves the same button usable again',()=>{
  const f=fixture(),p=f.button;p.launch({kind:'first'});f.advance(280);p.active=false;p.activeChanged();
  p.active=true;p.touch({type:0});f.advance(160);p.touch({type:2});p.launch({kind:'second'});f.advance(1000);
  assert.equal(f.opened.length,2);assert.equal(p.launching,false);assert.equal(f.scheduled.size,0);
});
test('idle buttons draw no frames and a motion preference change clears a running effect',()=>{
  const f=fixture(),p=f.button;f.advance(10000);assert.equal(f.painted.length,0);assert.equal(f.scheduled.size,0);
  p.touch({type:0});f.advance(160);assert.ok(f.painted.length>0);p.motion=false;p.optionsChanged();
  assert.equal(f.scheduled.size,0);assert.equal(p.trail.particles.length,0);p.touch({type:2});p.launch({kind:'click'});
  assert.equal(f.opened.length,1);
});
