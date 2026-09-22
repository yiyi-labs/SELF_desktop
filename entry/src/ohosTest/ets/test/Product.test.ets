import { describe,it,expect } from '@ohos/hypium';
import { Driver,ON } from '@ohos.UiTest';
import { abilityDelegatorRegistry } from '@kit.TestKit';
import { fileIo as fs } from '@kit.CoreFileKit';

export default function productSuite(){
 describe('SELFNativeProductUI',()=>{
  it('productLidRotationFactsAndClosingPreserveFaceSurface',0,async()=>{
   const app=abilityDelegatorRegistry.getAbilityDelegator();await app.startAbility({bundleName:'com.self.mirror',abilityName:'EntryAbility'});
   const driver=Driver.create();await driver.delayMs(2200);const path=(await app.getCurrentTopAbility()).context.filesDir;
   // Explicit paid integration on the public sample. No default/ad product card.
   await driver.assertComponentExist(ON.text('示例面容 · 数字表达'));
   expect(!!(await driver.findComponent(ON.id('product-card')))).assertFalse();
   await (await driver.findComponent(ON.id('conversation-input'))).inputText('请只介绍OLAY水光小白瓶50ml的已核实资料，不修改面容。');await driver.delayMs(700);
   await (await driver.findComponent(ON.text('发送'))).click();
   await (await driver.waitForComponent(ON.text('仅本次发送图像并理解'),5000)).click();
   await driver.waitForComponent(ON.id('product-lid').enabled(true),55000);
   await driver.assertComponentExist(ON.text('水光小白瓶'));
   for(let round=0;round<2;round++){
    if(round>0)await (await driver.findComponent(ON.text('看看这款'))).click();
    const lid=await driver.waitForComponent(ON.id('product-lid').enabled(true),8000);
    expect(!!lid).assertTrue();await driver.delayMs(700);
    if(round===0){
     await driver.screenCapture(path+'/product-ui-closed.png');
     const box=await (await driver.findComponent(ON.id('self-product-view'))).getBounds();
     const file=fs.openSync(path+'/product-ui-bounds.json',fs.OpenMode.CREATE|fs.OpenMode.READ_WRITE|fs.OpenMode.TRUNC);
     try{fs.writeSync(file.fd,JSON.stringify({left:box.left,right:box.right,top:box.top,bottom:box.bottom}));}finally{fs.closeSync(file);}
    }
    await lid.click();await driver.delayMs(1000);await driver.assertComponentExist(ON.text('合上'));
    if(round===0)await driver.screenCapture(path+'/product-ui-open.png');
    const r=await (await driver.findComponent(ON.id('self-product-view'))).getBounds();
    await driver.swipe(Math.round(r.left+(r.right-r.left)*.3),Math.round((r.top+r.bottom)*.5),Math.round(r.left+(r.right-r.left)*.7),Math.round((r.top+r.bottom)*.5),500);
    await (await driver.findComponent(ON.id('product-fact-1'))).click();await driver.delayMs(350);
    await driver.assertComponentExist(ON.text('等待核对\n实物成分表'));
    if(round===0)await driver.screenCapture(path+'/product-ui-facts.png');
    await (await driver.findComponent(ON.id('product-close'))).click();await driver.delayMs(600);
    await driver.assertComponentExist(ON.id('self-native-mirror'));
    await (await driver.findComponent(ON.text('回正'))).click();
    const face=await (await driver.findComponent(ON.id('self-native-mirror'))).getBounds();
    await driver.swipe(Math.round(face.left+(face.right-face.left)*.4),Math.round((face.top+face.bottom)*.4),Math.round(face.left+(face.right-face.left)*.6),Math.round((face.top+face.bottom)*.4),500);
   }
   await driver.screenCapture(path+'/face-after-product-ui.png');
   await (await driver.findComponent(ON.text('看看这款'))).click();await driver.waitForComponent(ON.id('product-lid').enabled(true),8000);
   await (await driver.findComponent(ON.id('conversation-input'))).inputText('取消');await driver.delayMs(700);
   await (await driver.findComponent(ON.text('发送'))).click();await driver.delayMs(700);
   expect(!!(await driver.findComponent(ON.id('product-card')))).assertFalse();
   expect(!!(await driver.findComponent(ON.text('看看这款')))).assertFalse();
   console.info('SELF_PRODUCT_UI '+JSON.stringify({onlyModelReferencedProduct:true,product:'olay-cn-waterglow-50ml',twoSurfaceReopens:true,lidAndRotation:true,stackedFormulaCard:true}));
  });
 });
}
