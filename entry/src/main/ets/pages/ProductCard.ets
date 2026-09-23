import { UiText } from '../services/UiText';
import native from 'libself_native.so';
import { common } from '@kit.AbilityKit';
import { ProductRecord,ProductRepository } from '../services/ProductRepository';
import { ProductFactsDeck } from './ProductFactsDeck';

interface ProductEvent {type:string;message?:string;}
@Extend(Button)
function productButton(){.height(38).padding({left:14,right:14}).fontSize(13).fontColor('#675772').backgroundColor('#C8FFFFFF').borderRadius(20).stateStyles({pressed:{.opacity(.72).scale({x:.96,y:.96})},normal:{.opacity(1).scale({x:1,y:1})}}).animation({duration:150,curve:Curve.EaseOut})}

@Component
export struct ProductCard {
 @StorageLink('selfLanguage') language:string='zh';
 private tr(value:string):string{return UiText.get(value,this.language);}
 @Prop @Watch('productChanged') product:ProductRecord=ProductRepository.records()[0];
 @Prop @Watch('motionChanged') motion:boolean=true;
 @Prop suggestionCount:number=1;
 @StorageLink('selfForeground') @Watch('visibilityChanged') foreground:boolean=true;
 onClose:()=>void=()=>{};
 onAsk:(id:string)=>void=()=>{};
 onChoose:(direction:number)=>void=()=>{};
 @State ready:boolean=false;
 @State opened:boolean=false;
 @State error:string='';
 private context:common.UIAbilityContext=this.getUIContext().getHostContext() as common.UIAbilityContext;
 private productSessionKey:string='product-'+Date.now()+'-'+Math.floor(Math.random()*100000);
 private bound:boolean=false;
 private queue:Promise<void>=Promise.resolve();
 private epoch:number=0;
 private yaw:number=0;
 private pitch:number=-.14;
 private lastX:number=0;
 private lastY:number=0;
 private dragging:boolean=false;
 private sendingView:boolean=false;

 private style():string{return this.product.illustration.replace('.svg','');}
 private productChanged():void{this.ready=false;this.opened=false;this.error='';this.yaw=0;this.pitch=-.14;this.epoch++;if(this.bound)this.load();}
 private load():void{
  const epoch=this.epoch,style=this.style(),id=this.product.productId;
  this.queue=this.queue.then(async()=>{
   if(!this.bound||epoch!==this.epoch)return;
   for(const lid of [false,true]){
    const bytes=await this.context.resourceManager.getRawFileContent('products/3d/'+style+(lid?'-lid.glb':'-body.glb'));
    if(!this.bound||epoch!==this.epoch)return;
    const result=await native.request(this.productSessionKey,JSON.stringify({type:'PRODUCT_LOAD',lid}),bytes.buffer as ArrayBuffer);
    if(lid&&this.bound&&epoch===this.epoch){this.ready=true;console.info('SELF_PRODUCT_READY '+id+' '+result.json);}
   }
  }).catch((e:Error)=>{if(this.bound&&epoch===this.epoch){this.ready=false;this.error='立体展示暂未加载，可继续了解产品资料。';console.error('SELF_PRODUCT_ERROR '+e.message);}});
 }
 private send(command:string):void{this.queue=this.queue.then(async()=>{if(this.bound)await native.request(this.productSessionKey,command);}).catch((e:Error)=>{if(this.bound)this.error='立体展示暂不可用。';console.error('SELF_PRODUCT_ERROR '+e.message);});}
 private motionChanged():void{if(this.bound&&!this.motion)this.send(JSON.stringify({type:'PRODUCT_LID',open:this.opened,motion:false,direction:this.style()==='black-tube'?-1:1}));}
 private visibilityChanged():void{if(this.bound)this.send(JSON.stringify({type:'FOREGROUND',value:this.foreground}));}
 private toggle():void{if(!this.ready)return;this.opened=!this.opened;this.send(JSON.stringify({type:'PRODUCT_LID',open:this.opened,motion:this.motion,direction:this.style()==='black-tube'?-1:1}));}
 private touch(event:TouchEvent):void{
  event.stopPropagation();if(!this.ready)return;
  if(event.type===TouchType.Up||event.type===TouchType.Cancel){this.dragging=false;return;}
  if(event.touches.length!==1){this.dragging=false;return;}const p=event.touches[0];
  if(event.type===TouchType.Down){this.lastX=p.x;this.lastY=p.y;this.dragging=true;return;}
  if(!this.dragging)return;this.yaw+=(p.x-this.lastX)*.012;this.pitch=Math.max(-.55,Math.min(.55,this.pitch+(p.y-this.lastY)*.009));this.lastX=p.x;this.lastY=p.y;
  if(this.sendingView)return;this.sendingView=true;
  this.queue=this.queue.then(async()=>{if(this.bound)await native.request(this.productSessionKey,JSON.stringify({type:'PRODUCT_VIEW',yaw:this.yaw,pitch:this.pitch}));}).catch(()=>{}).finally(()=>{this.sendingView=false;});
 }
 private detach():void{if(this.bound){this.bound=false;this.epoch++;native.unbind(this.productSessionKey);}}
 aboutToDisappear():void{this.detach();}
 build(){
  Column({space:10}){
   Row(){Text(this.tr('OLAY  /  本次提到')).fontSize(11).letterSpacing(1).fontColor('#9683A0');Blank();Button(this.tr('收起')).id('product-close').productButton().onClick(()=>this.onClose())}.width('100%')
   Row({space:10}){Stack({alignContent:Alignment.Bottom}){
    XComponent({type:XComponentType.SURFACE}).id('self-product-view').width('100%').height('100%').backgroundColor('#F9F7FA')
     .onAttach(()=>{const node=this.getUIContext().getAttachedFrameNodeById('self-product-view');if(node){this.bound=true;native.bind(this.productSessionKey,node,(value:string)=>{if(!this.bound)return;const e=JSON.parse(value) as ProductEvent;if(e.type==='READY')this.load();else if(e.type==='ERROR')this.error='立体展示暂不可用。';});}})
     .onDetach(()=>this.detach()).onTouch((e:TouchEvent)=>this.touch(e))
    Text(this.tr(this.error||(!this.ready?'正在呈现…':'拖动旋转 · 3D 外观示意'))).fontSize(10).fontColor('#94859F').padding(8).hitTestBehavior(HitTestMode.None)
   }.layoutWeight(1).height(210).borderRadius(24).clip(true)
   ProductFactsDeck({product:this.product,motion:this.motion})}.width('100%')
   Row(){Column({space:5}){Text(this.tr(this.product.name)).fontSize(18).fontWeight(FontWeight.Medium).fontColor('#493C55').maxLines(2);Text(this.tr(this.product.specification.startsWith('未核实')?'中国大陆资料':this.product.specification)).fontSize(12).fontColor('#95849E')}.alignItems(HorizontalAlign.Start).layoutWeight(1);Button(this.tr(this.opened?'合上':'打开看看')).id('product-lid').productButton().enabled(this.ready).onClick(()=>this.toggle())}.width('100%')
   Button(this.tr('聊聊这款')).productButton().width('100%').backgroundColor('#7C698F').fontColor(Color.White).onClick(()=>this.onAsk(this.product.productId))
   Row(){
    if(this.suggestionCount>1){Button(this.tr('上一项')).productButton().onClick(()=>this.onChoose(-1))}
    Blank()
    Text(this.tr('与本次对话相关')).fontSize(10).fontColor('#A194A8')
    Blank()
    if(this.suggestionCount>1){Button(this.tr('下一项')).productButton().onClick(()=>this.onChoose(1))}
   }.width('100%')
  }.id('product-card').padding(16).width('100%').backgroundColor('#F3FFFFFF').backgroundBlurStyle(BlurStyle.COMPONENT_REGULAR).borderRadius(32).border({width:1,color:'#EBFFFFFF'}).shadow({radius:28,color:'#23796789',offsetY:8})
 }
}
