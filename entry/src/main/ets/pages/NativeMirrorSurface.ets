import { NativeRendererPort } from '../bridge/NativeRendererPort';
@ComponentV2
export struct NativeMirrorSurface {
 @Param port:NativeRendererPort=new NativeRendererPort();
 @Param interactionEnabled:boolean=true;
 @Param motion:boolean=true;
 @Local stroke:number[][]=[];
 @Local selectionPath:number[][]=[];
 @Local selectionPathOpacity:number=1;
 private areaWidth:number=1;private areaHeight:number=1;
 private points(points:number[][]):number[][]{return points.map((p:number[])=>[p[0]*this.areaWidth,p[1]*this.areaHeight]);}
 aboutToDisappear():void{this.port.dispose();}
 build(){Stack(){
  XComponent({type:XComponentType.SURFACE}).id('self-native-mirror').width('100%').height('100%')
   .onAttach(()=>{const node=this.getUIContext().getAttachedFrameNodeById('self-native-mirror');if(node){this.port.onStroke=(points:number[][])=>{this.stroke=this.points(points);};this.port.onOutline=(points:number[][])=>{this.selectionPath=this.points(points);this.selectionPathOpacity=.35;this.getUIContext().animateTo({duration:this.motion?260:0,curve:Curve.EaseOut},()=>this.selectionPathOpacity=1);};this.port.attach(node);}})
   .onDetach(()=>this.port.dispose())
   .onAreaChange((_old:Area,area:Area)=>{this.areaWidth=Number(area.width);this.areaHeight=Number(area.height);this.selectionPath=[];})
   .onTouch((event:TouchEvent)=>{if(this.interactionEnabled)this.port.touch(event,this.areaWidth,this.areaHeight);})
  if(this.stroke.length>1){
   Polyline().points(this.stroke).stroke('#68FFFFFF').strokeWidth(10).fill(Color.Transparent).width('100%').height('100%').hitTestBehavior(HitTestMode.None)
   Polyline().points(this.stroke).stroke('#6650A0').strokeWidth(3).strokeLineCap(LineCapStyle.Round).fill(Color.Transparent).width('100%').height('100%').hitTestBehavior(HitTestMode.None)
   Circle().width(12).height(12).fill('#FFFFFF').stroke('#6650A0').strokeWidth(2).position({x:this.stroke[this.stroke.length-1][0]-6,y:this.stroke[this.stroke.length-1][1]-6}).hitTestBehavior(HitTestMode.None)
  }
  if(this.selectionPath.length>2){
   Polygon().points(this.selectionPath).fill('#16BDA9E5').stroke('#AFFFFFFF').strokeWidth(8).width('100%').height('100%').opacity(this.selectionPathOpacity).hitTestBehavior(HitTestMode.None)
   Polyline().id('selection-outline').points(this.selectionPath).stroke('#7157A6').strokeWidth(2.5).strokeDashArray([7,5]).fill(Color.Transparent).width('100%').height('100%').opacity(this.selectionPathOpacity).hitTestBehavior(HitTestMode.None)
  }
 }.width('100%').height('100%')}
}
