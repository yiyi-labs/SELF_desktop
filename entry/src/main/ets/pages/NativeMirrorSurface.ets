import { NativeRendererPort } from '../bridge/NativeRendererPort';
@ComponentV2
export struct NativeMirrorSurface {
 @Param port:NativeRendererPort=new NativeRendererPort();
 @Param interactionEnabled:boolean=true;
 @Local stroke:number[][]=[];
 private areaWidth:number=1;private areaHeight:number=1;
 aboutToDisappear():void{this.port.dispose();}
 build(){Stack(){
  XComponent({type:XComponentType.SURFACE}).id('self-native-mirror').width('100%').height('100%')
   .onAttach(()=>{const node=this.getUIContext().getAttachedFrameNodeById('self-native-mirror');if(node){this.port.onStroke=(points:number[][])=>{this.stroke=points.map((p:number[])=>[p[0]*this.areaWidth,p[1]*this.areaHeight]);};this.port.attach(node);}})
   .onDetach(()=>this.port.dispose())
   .onAreaChange((_old:Area,area:Area)=>{this.areaWidth=Number(area.width);this.areaHeight=Number(area.height);})
   .onTouch((event:TouchEvent)=>{if(this.interactionEnabled)this.port.touch(event,this.areaWidth,this.areaHeight);})
  if(this.stroke.length>1){Polyline().points(this.stroke).stroke('#8D6FAD').strokeWidth(2).fill(Color.Transparent).width('100%').height('100%').hitTestBehavior(HitTestMode.None)}
 }.width('100%').height('100%')}
}

