import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {transformSync} from 'esbuild';

const editorSource=fs.readFileSync('entry/src/main/ets/pages/PersonalPortraitEditor.ets','utf8');
const demoSource=fs.readFileSync('entry/src/main/ets/domain/FreckleDemo.ets','utf8');
const methods=editorSource.slice(editorSource.indexOf('  private submit('),editorSource.indexOf('  private capture('));
const code=transformSync(demoSource.replace(/^export /gm,'')+`\nclass Editor {${methods}}\nglobalThis.Editor=Editor;`,{loader:'ts'}).code;
function fixture(deviceType,assetId='a'.repeat(32)){
  let captures=0,stops=0;const commands=[],timers=[];
  const context=vm.createContext({deviceInfo:{deviceType},setTimeout:(fn,delay)=>timers.push({fn,delay})});vm.runInContext(code,context);
  const editor=new context.Editor();
  Object.assign(editor,{assetId,revision:0,demoReplyToken:0,bubble:true,selected:true,ready:true,waiting:false,choices:[],careWeek:0,carePreviewToken:0,
    cloudEnabled:false,cloudConsentDecision:'denied',planner:{cancel(){}},selectionInputController:{stopEditing(){stops++;}},
    onInteraction(){},tr:value=>value,capture(){captures++;},command:(...args)=>commands.push(args)});
  return {editor,commands,timers,finish:()=>timers.splice(0).forEach(timer=>timer.fn()),get captures(){return captures;},get stops(){return stops;}};
}
test('all tablet assets and questions use one local standard before any cloud consent or capture',()=>{
  for(const assetId of ['a'.repeat(32),'b'.repeat(32),'sample-lee'])for(const question of ['这处雀斑让我无法见人了','想看看这里','自然一点']){
    const f=fixture('tablet',assetId);f.editor.submit(question);
    assert.equal(f.editor.freckleDemo,false);assert.equal(f.editor.requestText,question);
    assert.equal(f.editor.responseText,'我陪你看看这些地方…');assert.equal(f.editor.waiting,true);
    assert.equal(f.timers[0].delay,2400);f.finish();
    assert.equal(f.editor.freckleDemo,true);assert.equal(f.editor.waiting,false);
    assert.ok(f.editor.responseText.startsWith('✧ 听起来'));assert.equal(f.captures,0);assert.equal(f.commands.length,0);
    assert.equal(f.editor.consentOffer,false);assert.equal(f.editor.candidateReady,false);assert.equal(f.stops,1);
    f.editor.tryFreckleLook('warm');assert.equal(f.commands.length,0);assert.equal(f.editor.demoLook,'warm');
    assert.equal(f.captures,0);assert.ok(f.editor.demoNotice.includes('稍后开放'));
  }
});
test('phone and other devices retain the normal cloud path, and no selection cannot trigger a demo',()=>{
  for(const type of ['phone','2in1','unknown']){
    const f=fixture(type);f.editor.submit('这处雀斑让我无法见人了');assert.equal(f.editor.freckleDemo,false);
    f.editor.cloudEnabled=true;f.editor.submit('自然一点');assert.equal(f.captures,1);
    f.editor.tryFreckleLook('warm');assert.equal(f.commands.length,0);
  }
  const f=fixture('tablet');f.editor.selected=false;f.editor.submit('想看看');assert.notEqual(f.editor.freckleDemo,true);
});
test('try-on requires a click, a valid look, current selection and a ready model; ignores stale history writes',()=>{
  const f=fixture('tablet');f.editor.submit('这处雀斑让我无法见人了');f.finish();
  for(const invalid of ['erase','rose',''])f.editor.tryFreckleLook(invalid);
  assert.equal(f.commands.length,0);
  for(const [field,value] of [['selected',false],['ready',false],['waiting',true],['pendingHistory',{}]]){
    const previous=f.editor[field];f.editor[field]=value;f.editor.tryFreckleLook('warm');
    assert.equal(f.commands.length,0);f.editor[field]=previous;
  }
});
test('a product opt-out is respected by the fixed tablet reply',()=>{
  const f=fixture('tablet');f.editor.submit('不用推荐产品');f.finish();assert.equal(f.editor.productsDismissed,true);
  f.editor.submit('推荐护理');assert.equal(f.editor.productsDismissed,false);
});

test('a cancelled, replaced or hidden selection cannot receive the delayed answer',()=>{
  for(const update of [e=>e.demoReplyToken++,e=>e.revision++,e=>e.assetId='other',e=>e.selected=false,e=>e.bubble=false,e=>e.waiting=false]){
    const f=fixture('tablet');f.editor.submit('这处雀斑让我无法见人了');update(f.editor);f.finish();
    assert.equal(f.editor.freckleDemo,false);assert.equal(f.editor.responseText,'我陪你看看这些地方…');
  }
});

