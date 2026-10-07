import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {transformSync} from 'esbuild';

const layoutSource=fs.readFileSync(new URL('../../entry/src/main/ets/domain/SelectionConversationLayout.ets',import.meta.url),'utf8');
const editorSource=fs.readFileSync(new URL('../../entry/src/main/ets/pages/PersonalPortraitEditor.ets',import.meta.url),'utf8');
// Run the production selection and focus handlers, so a later keyboard reposition is caught.
const focusMethods=editorSource.slice(editorSource.indexOf('  private focusSelectionInput('),editorSource.indexOf('  private directory('));
const selectionMethods=editorSource.slice(editorSource.indexOf('  private selectedRegion('),editorSource.indexOf('  private syncCaptionSuppression('));
const clearMethod=editorSource.slice(editorSource.indexOf('  private clearSelection('),editorSource.indexOf('  aboutToDisappear('));
const code=transformSync(layoutSource.replace(/^export /gm,'')+`\nclass Editor {${focusMethods}${selectionMethods}${clearMethod}}\nglobalThis.Editor=Editor;globalThis.place=selectionConversationFrame;`,{loader:'ts',target:'es2020'}).code;

function fixture(width=1280,height=800){
  const modes=[],commands=[];let stops=0;
  const ui={setKeyboardAvoidMode:mode=>modes.push(mode),animateTo:(_options,fn)=>fn()};
  const context=vm.createContext({console:{info:()=>{}},KeyboardAvoidMode:{NONE:0,OFFSET:1},Curve:{EaseOut:0}});
  vm.runInContext(code,context);
  const editor=new context.Editor();
  Object.assign(editor,{viewportWidth:width,viewportHeight:height,selections:[],careWeek:0,carePreviewToken:0,
    planner:{cancel:()=>{}},ready:true,waiting:false,revision:0,history:undefined,
    previousKeyboardAvoidMode:1,selectionInputController:{stopEditing:()=>{stops++;editor.blurSelectionInput();}},
    getUIContext:()=>ui,tr:value=>value,revealStoryHint:()=>{},onInteraction:()=>{},command:(...args)=>commands.push(args)});
  return {editor,place:context.place,modes,commands,get stops(){return stops;}};
}
const selection=(bounds,id='gs-selected-1')=>({regionId:id,count:100,total:1000,x:(bounds.left+bounds.right)/2,y:(bounds.top+bounds.bottom)/2,bounds});
const frameValue=editor=>JSON.stringify(editor.conversationFrame);

test('opening uses the right edge of the lasso and clamps only at the screen boundary',()=>{
  const {place}=fixture();
  for(const [width,height] of [[1280,800],[800,1280],[1100,700]]){
    for(const bounds of [
      {left:.35,top:.32,right:.45,bottom:.44},
      {left:.75,top:.32,right:.9,bottom:.45},
      {left:.04,top:.4,right:.16,bottom:.6},
      {left:.42,top:.78,right:.56,bottom:.91},
      {left:.35,top:.1,right:.6,bottom:.22},
      {left:.1,top:.25,right:.9,bottom:.55}
    ]){
      const f=place(width,height,bounds),rect={left:bounds.left*width,top:bounds.top*height,right:bounds.right*width,bottom:bounds.bottom*height};
      assert.ok(f.x>=18&&f.y>=58&&f.x+f.width<=width-18&&f.y+f.maxHeight<=height-20);
      assert.equal(f.x,Math.min(rect.right+18,width-18-240),'always anchor to the right, with viewport clamping');
      assert.ok(f.width>=240&&f.width<=330);
      if(width-18-rect.right-18>=240)assert.equal(f.x-rect.right,18,'leave a gap when there is room to the right');
    }
  }
});

test('focus, typing, keyboard bounds, viewport changes and replies keep the same frame',()=>{
  const f=fixture(),e=f.editor;
  e.selectedRegion(selection({left:.28,top:.35,right:.4,bottom:.5}),new ArrayBuffer(1000));
  const before=frameValue(e);
  e.focusSelectionInput();assert.equal(e.keyboardOpen,true);assert.equal(f.modes.at(-1),0);
  for(const input of ['想','想试试','想试试自然一点']){
    e.input=input;e.keyboardTopVp=420;e.viewportHeight=420;e.viewportWidth=820;
    e.responseText='更长的回复'.repeat(50);e.replyLines=Array(20).fill('回复');e.careExpanded=true;
    assert.equal(frameValue(e),before);
  }
  e.blurSelectionInput();assert.equal(e.keyboardOpen,false);assert.equal(f.modes.at(-1),1);
  assert.equal(frameValue(e),before);
  assert.ok(editorSource.includes('.position({x:this.conversationFrame.x,y:this.conversationFrame.y})'));
  assert.ok(editorSource.includes('.onFocus(()=>this.focusSelectionInput()).onBlur(()=>this.blurSelectionInput())'));
});

test('redrawing or adding another lasso updates the anchor, while cancellation still clears it',()=>{
  const f=fixture(),e=f.editor;
  e.selectedRegion(selection({left:.15,top:.25,right:.25,bottom:.4}),new ArrayBuffer(1000));
  const first=frameValue(e);
  e.selectedRegion(selection({left:.7,top:.25,right:.8,bottom:.4}),new ArrayBuffer(1000));
  assert.notEqual(frameValue(e),first);assert.equal(e.selectionCount,1);
  e.focusSelectionInput();e.appendSelection();assert.equal(e.bubble,false);assert.equal(f.stops,1);
  assert.equal(f.commands.at(-1)[0],'ARM_APPEND');
  e.selectedRegion(selection({left:.45,top:.6,right:.5,bottom:.7},'gs-selected-2'),new ArrayBuffer(1000));
  assert.equal(e.selectionCount,2);assert.equal(e.bubble,true);
  e.clearSelection();assert.equal(e.selectionCount,0);assert.equal(e.selected,false);assert.equal(e.bubble,false);
  assert.equal(f.commands.at(-1)[0],'CLEAR_SELECTION');assert.equal(f.stops,2);
});

test('conversation can grow beyond the old 320vp cap while staying inside available space',()=>{
  const {place}=fixture();
  const bounds={left:.45,top:.20,right:.55,bottom:.34};
  const frame=place(1280,900,bounds);
  assert.ok(frame.maxHeight>320);assert.ok(frame.y+frame.maxHeight<=880);
  const revealMethods=editorSource.slice(editorSource.indexOf('  private responseChanged('),editorSource.indexOf('  private careProduct('));
  const runtime=vm.createContext({Curve:{EaseOut:0},setTimeout:()=>{}});
  vm.runInContext(transformSync(`class Reply {${revealMethods}}\nglobalThis.Reply=Reply`,{loader:'ts'}).code,runtime);
  const reply=new runtime.Reply();
  Object.assign(reply,{conversationContentHeight:168,getUIContext:()=>({animateTo:(_opts,fn)=>fn()})});
  reply.resizeConversation(680);assert.equal(reply.conversationContentHeight,680);
  reply.resizeConversation(230);assert.equal(reply.conversationContentHeight,230);
  reply.resizeConversation(NaN);assert.equal(reply.conversationContentHeight,230);
});
