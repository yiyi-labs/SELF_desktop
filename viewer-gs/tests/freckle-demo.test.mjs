import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {transformSync} from 'esbuild';

const editorSource=fs.readFileSync('entry/src/main/ets/pages/PersonalPortraitEditor.ets','utf8');
const demoSource=fs.readFileSync('entry/src/main/ets/domain/FreckleDemo.ets','utf8');
const methods=editorSource.slice(editorSource.indexOf('  private sendStory('),editorSource.indexOf('  private acceptCloudIntroduction('))+
  editorSource.slice(editorSource.indexOf('  private submit('),editorSource.indexOf('  private capture('));
const code=transformSync(demoSource.replace(/^export /gm,'')+`\nclass Editor {${methods}}\nglobalThis.Editor=Editor;`,{loader:'ts'}).code;
function fixture(deviceType,assetId='a'.repeat(32)){
  let captures=0,stops=0;const commands=[],timers=[],storyRequests=[];
  const context=vm.createContext({deviceInfo:{deviceType},setTimeout:(fn,delay)=>timers.push({fn,delay})});vm.runInContext(code,context);
  const editor=new context.Editor();
  Object.assign(editor,{assetId,revision:0,demoReplyToken:0,bubble:true,selected:true,ready:true,waiting:false,choices:[],careWeek:0,carePreviewToken:0,
    cloudEnabled:false,cloudConsentDecision:'denied',storyWaiting:false,planner:{cancel(){}},selectionInputController:{stopEditing(){stops++;}},
    askStory:text=>storyRequests.push(text),enterExistingEdit(){},
    onInteraction(){},tr:value=>value,capture(){captures++;},command:(...args)=>commands.push(args)});
  return {editor,commands,timers,storyRequests,finish:()=>timers.splice(0).forEach(timer=>timer.fn()),get captures(){return captures;},get stops(){return stops;}};
}
test('only the specified question triggers the local tablet demo on every asset',()=>{
  for(const assetId of ['a'.repeat(32),'b'.repeat(32),'sample-lee'])for(const question of ['这处雀斑让我无法见人了','  这处雀斑让我无法见人了  ']){
    const f=fixture('tablet',assetId);f.editor.submit(question);
    assert.equal(f.editor.freckleDemo,false);assert.equal(f.editor.requestText,question.trim());
    assert.equal(f.editor.responseText,'我陪你看看这些地方…');assert.equal(f.editor.waiting,true);
    assert.equal(f.timers[0].delay,2400);f.finish();
    assert.equal(f.editor.freckleDemo,true);assert.equal(f.editor.waiting,false);
    assert.ok(f.editor.responseText.startsWith('✧ 听起来'));assert.equal(f.captures,0);assert.equal(f.commands.length,0);
    assert.equal(f.editor.consentOffer,false);assert.equal(f.editor.candidateReady,false);assert.equal(f.stops,1);
    f.editor.tryFreckleLook('warm');assert.equal(f.commands.length,0);assert.equal(f.editor.demoLook,'warm');
    assert.equal(f.captures,0);assert.ok(f.editor.demoNotice.includes('稍后开放'));
  }
});
test('other tablet selection questions retain the normal AI capture and consent paths',()=>{
  for(const question of ['想看看这里','自然一点','这处雀斑让我无法见人了。','为什么这处雀斑让我无法见人了','这处雀斑让我无法见人了，请帮帮我']){
    const f=fixture('tablet');f.editor.cloudEnabled=true;f.editor.submit(question);
    assert.equal(f.captures,1);assert.equal(f.editor.freckleDemo,false);assert.equal(f.timers.length,0);
    const denied=fixture('tablet');denied.editor.submit(question);
    assert.equal(denied.captures,0);assert.equal(denied.editor.freckleDemo,false);
    assert.equal(denied.editor.responseText,'云端对话已关闭。想再继续时，可以在设置里开启。');
    const undecided=fixture('tablet');undecided.editor.cloudConsentDecision='unknown';undecided.editor.submit(question);
    assert.equal(undecided.editor.consentOffer,true);assert.equal(undecided.editor.consentIntent,'edit');
    assert.equal(undecided.captures,0);assert.equal(undecided.timers.length,0);
  }
});
test('the story entry only redirects the specified demo question and preserves ordinary routing',()=>{
  const demo=fixture('tablet');demo.editor.sendStory('这处雀斑让我无法见人了');demo.finish();
  assert.equal(demo.editor.freckleDemo,true);assert.equal(demo.storyRequests.length,0);assert.equal(demo.captures,0);
  const edit=fixture('tablet');edit.editor.cloudEnabled=true;edit.editor.sendStory('想看看这里');
  assert.equal(edit.captures,1);assert.equal(edit.storyRequests.length,0);assert.equal(edit.timers.length,0);
  const story=fixture('tablet');story.editor.cloudEnabled=true;story.editor.sendStory('自然一点');
  assert.deepEqual(story.storyRequests,['自然一点']);assert.equal(story.captures,0);assert.equal(story.timers.length,0);
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
test('product preferences are retained across normal questions and the tablet demo',()=>{
  const f=fixture('tablet');f.editor.submit('不用推荐产品');assert.equal(f.editor.productsDismissed,true);
  f.editor.submit('这处雀斑让我无法见人了');f.finish();assert.equal(f.editor.productsDismissed,true);
  f.editor.submit('推荐护理');assert.equal(f.editor.productsDismissed,false);
});

test('a cancelled, replaced or hidden selection cannot receive the delayed answer',()=>{
  for(const update of [e=>e.demoReplyToken++,e=>e.revision++,e=>e.assetId='other',e=>e.selected=false,e=>e.bubble=false,e=>e.waiting=false]){
    const f=fixture('tablet');f.editor.submit('这处雀斑让我无法见人了');update(f.editor);f.finish();
    assert.equal(f.editor.freckleDemo,false);assert.equal(f.editor.responseText,'我陪你看看这些地方…');
  }
});

