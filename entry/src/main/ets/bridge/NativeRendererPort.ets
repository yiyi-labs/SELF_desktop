import native, { NativeResult } from 'libself_native.so';
import { Envelope, MessagePayload } from './RendererBridge';
import { SceneView } from '../domain/EditPlan';
interface NativeEvent {type:string;message?:string;generation?:number;}
interface ReconstructionStatus {message:string;}
interface Dimensions {width:number;height:number;}
interface CaptureInfo {split:number;width:number;height:number;view:SceneView;}
export interface NativeCapture {images:ArrayBuffer[];view:SceneView;width:number;height:number;}
interface NativeCommand {
 type:string;kind?:string;id?:string;value?:boolean;tool?:string;width?:number;height?:number;
 yaw?:number;pitch?:number;distance?:number;panX?:number;panY?:number;points?:number[][];
 operations?:Object[];anchorOperations?:Object[];protectionId?:string;original?:boolean;
 protectionRuleId?:string;
 motion?:boolean;palette?:string;animate?:boolean;
}
/** Single production renderer. Ordered commands copy bytes before crossing to the GL thread. */
export class NativeRendererPort {
 sessionId:string='native-'+Date.now();assetId:string='sample-lee';assetVersion:string='lee-r186-self2';revision:number=0;ready:boolean=false;
 onMessage:(message:Envelope)=>void=()=>{};onBytes:(kind:string,bytes:ArrayBuffer)=>void=()=>{};
 onStroke:(points:number[][])=>void=()=>{};
 onOutline:(points:number[][])=>void=()=>{};
 onSelectionAnchor:(x:number,y:number,halfWidth:number)=>void=()=>{};onToolChanged:(tool:string)=>void=()=>{};
 private penStroke:boolean=false;
 private navigationPending:boolean=false;
 private queue:Promise<void>=Promise.resolve();private bound:boolean=false;private epoch:number=0;
 private view:SceneView={yaw:0,pitch:0,distance:16,panX:0,panY:0};private tool:string='NAVIGATE';private stroke:number[][]=[];
 private previousX:number=0;private previousY:number=0;private pinch:number=0;
 private photo:boolean=false;
 attach(node:Object):void{
  this.bound=true;
  try{native.bind(this.sessionId,node,(raw:string)=>{if(!this.bound)return;const event=JSON.parse(raw) as NativeEvent;
   if(event.type==='READY'){this.ready=true;this.emit('INITIALIZED',{});}
   if(event.type==='ERROR'){this.ready=false;this.emit('RENDER_FAILED',{message:event.message||'原生镜面暂不可用'});}
  });}catch(e){this.bound=false;this.emit('RENDER_FAILED',{message:String(e)});}
 }
 private emit(type:string,payload:MessagePayload,requestId:string='',revision:number=this.revision):void{
  this.onMessage({schemaVersion:1,sessionId:this.sessionId,assetId:this.assetId,assetVersion:this.assetVersion,requestId,revision,type,payload});
 }
 private enqueue(command:NativeCommand,bytes:ArrayBuffer|undefined,done:(result:NativeResult)=>void=()=>{}):void{
  const epoch=this.epoch;
  this.queue=this.queue.then(async()=>{if(!this.bound||epoch!==this.epoch)return;const result=bytes?await native.request(this.sessionId,JSON.stringify(command),bytes):await native.request(this.sessionId,JSON.stringify(command));if(epoch===this.epoch)done(result);}).catch((error:Error)=>{if(epoch===this.epoch)this.emit('RENDER_FAILED',{message:error.message});});
 }
 sendBytes(kind:string,bytes:Uint8Array):void{
  const data=bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength) as ArrayBuffer;
  if(kind==='echo'){this.enqueue({type:'ECHO'},data,(r:NativeResult)=>this.onBytes('echo',r.bytes));return;}
  if(kind.startsWith('mask:')){this.enqueue({type:'MASK',id:kind.substring(5)},data);return;}
  this.photo=kind!=='glb';this.enqueue({type:'LOAD',kind:kind==='glb'?'glb':'photo'},data,(result:NativeResult)=>{const dimensions=JSON.parse(result.json) as Dimensions;this.emit('ASSET_REGISTERED',{width:dimensions.width,height:dimensions.height});});
 }
 send(type:string,payload:MessagePayload,requestId:string=''):void{
  if(!this.ready)throw new Error('原生镜面尚未就绪');
  if(type==='INIT'){this.epoch++;this.cancelStroke();this.emit('INITIALIZED',{});return;}
  if(type==='RENDER_AUTHORIZED_PLAN'){const rev=this.revision;this.enqueue({type:'EDIT',operations:payload.operations||[],anchorOperations:payload.anchorOperations||[],protectionId:payload.protectionId||'',protectionRuleId:payload.protectionRuleId||'',animate:payload.animate||false},undefined,()=>this.emit('RENDER_SUCCEEDED',{},requestId,rev));return;}
  if(type==='VIEW_SET'&&payload.view){this.onOutline([]);this.view=payload.view;this.enqueue({type:'VIEW',yaw:this.view.yaw,pitch:this.view.pitch,distance:this.view.distance,panX:this.view.panX,panY:this.view.panY},undefined,()=>this.emit('VIEW_CHANGED',{view:this.view}));return;}
  if(type==='SET_TOOL'){this.cancelStroke();this.tool=payload.tool||'NAVIGATE';this.enqueue({type:'TOOL',tool:this.tool},undefined);return;}
  if(type==='VIEW_ORBIT'){this.enqueue({type:'ORBIT'},undefined);return;}
  if(type==='VIEW_RESET'){this.onOutline([]);this.view={yaw:0,pitch:0,distance:16,panX:0,panY:0};this.enqueue({type:'VIEW_RESET',motion:payload.motion},undefined,()=>this.emit('VIEW_CHANGED',{view:this.view}));return;}
  if(type==='EXPORT_REQUEST'){this.enqueue({type:'EXPORT',width:payload.width||768,height:payload.height||1024},undefined,(r:NativeResult)=>this.onBytes('png',r.bytes));return;}
  if(type==='SET_ATMOSPHERE'){this.enqueue({type:'ATMOSPHERE',motion:payload.motion,palette:payload.palette},undefined);return;}
  if(type==='ECHO')return;
  throw new Error('尚未实现的原生操作：'+type);
 }
 foreground(value:boolean):void{if(this.bound){this.enqueue({type:'FOREGROUND',value},undefined);if(!value)this.enqueue({type:'STATS'},undefined,(r:NativeResult)=>console.info('SELF_NATIVE_STATS '+r.json));}if(!value){this.cancelStroke();this.onOutline([]);}}
 private cancelStroke():void{this.stroke=[];this.pinch=0;this.onStroke([]);}
 touch(event:TouchEvent,width:number,height:number):void{
  if(!this.ready||this.tool==='DETAIL'||width<=0||height<=0)return;
  if(event.type===TouchType.Cancel){this.cancelStroke();this.penStroke=false;return;}
  if(event.type===TouchType.Down&&event.sourceTool===SourceTool.Pen){this.penStroke=true;this.send('SET_TOOL',{tool:'LASSO'});this.onToolChanged('LASSO');}
  const points=event.touches;
  if(this.penStroke&&event.sourceTool!==SourceTool.Pen)return;
  if(points.length>=2){this.stroke=[];this.onStroke([]);const distance=Math.hypot(points[0].x-points[1].x,points[0].y-points[1].y);if(this.pinch>0&&this.tool==='NAVIGATE'){this.view.distance=Math.max(10,Math.min(25,this.view.distance*this.pinch/distance));this.send('VIEW_SET',{view:this.view});}this.pinch=distance;return;}
  if(event.type===TouchType.Up){if(this.stroke.length>=3&&this.tool==='LASSO'){const polygon=this.stroke.slice();const xs=polygon.map((p:number[])=>p[0]),ys=polygon.map((p:number[])=>p[1]);this.onSelectionAnchor((Math.min(...xs)+Math.max(...xs))/2,(Math.min(...ys)+Math.max(...ys))/2,(Math.max(...xs)-Math.min(...xs))/2);this.enqueue({type:'SELECT',points:polygon},undefined,(r:NativeResult)=>{if(new Uint8Array(r.bytes).some((v:number)=>v>0))this.onOutline(polygon.concat([polygon[0]]));this.onBytes('selection',r.bytes);});}this.cancelStroke();this.penStroke=false;return;}
  if(points.length!==1)return;const p=points[0];
  if(event.type===TouchType.Down){this.onOutline([]);if(this.tool==='NAVIGATE'){this.navigationPending=true;this.currentView().finally(()=>this.navigationPending=false).catch(()=>{});}this.pinch=0;this.previousX=p.x;this.previousY=p.y;if(this.tool==='LASSO')this.stroke=[[p.x/width,p.y/height]];return;}
  if(this.pinch>0)return; // Remaining finger after a pinch waits for a new stroke.
  if(event.type===TouchType.Move){if(this.navigationPending){this.previousX=p.x;this.previousY=p.y;return;}if(this.tool==='LASSO'){if(this.stroke.length<2048)this.stroke.push([p.x/width,p.y/height]);this.onStroke(this.stroke.slice());}
   else if(this.tool==='NAVIGATE'){if(this.photo){const scale=2*this.view.distance*Math.tan(35*Math.PI/360)/height;this.view.panX=Math.max(-6,Math.min(6,this.view.panX+(p.x-this.previousX)*scale));this.view.panY=Math.max(-6,Math.min(6,this.view.panY-(p.y-this.previousY)*scale));this.view.yaw=0;this.view.pitch=0;}else{this.view.yaw=Math.max(-Math.PI,Math.min(Math.PI,this.view.yaw+(p.x-this.previousX)*.008));this.view.pitch=Math.max(-.6,Math.min(.6,this.view.pitch+(p.y-this.previousY)*.006));}this.send('VIEW_SET',{view:this.view});}
   this.previousX=p.x;this.previousY=p.y;
  }
 }
 async reconstructionSupport():Promise<string>{await this.queue;const r=await native.request(this.sessionId,JSON.stringify({type:'RECON_SUPPORT'}));console.info('SELF_RECON_SUPPORT '+r.json);return (JSON.parse(r.json) as ReconstructionStatus).message;}
 async snapshot(width:number=768,height:number=1024):Promise<ArrayBuffer>{await this.queue;const result=await native.request(this.sessionId,JSON.stringify({type:'EXPORT',width,height}));return result.bytes;}
 async currentView():Promise<SceneView>{await this.queue;const result=await native.request(this.sessionId,JSON.stringify({type:'GET_VIEW'}));this.view=JSON.parse(result.json) as SceneView;this.emit('VIEW_CHANGED',{view:this.view});return this.view;}
 async capture(regionId:string):Promise<NativeCapture>{await this.queue;const result=await native.request(this.sessionId,JSON.stringify({type:'SNAPSHOT',regionId,width:768,height:1024}));const info=JSON.parse(result.json) as CaptureInfo;const images:ArrayBuffer[]=[result.bytes.slice(0,info.split)];if(result.bytes.byteLength>info.split)images.push(result.bytes.slice(info.split));return {images,view:info.view,width:info.width,height:info.height};}
 dispose():void{this.epoch++;this.ready=false;this.cancelStroke();if(this.bound){native.unbind(this.sessionId);this.bound=false;}}
}
