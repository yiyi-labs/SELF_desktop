import native from 'libself_native.so';
import { common } from '@kit.AbilityKit';
import { fileIo as fs } from '@kit.CoreFileKit';
import { RenderOperation } from '../bridge/RendererBridge';
import { http } from '@kit.NetworkKit';
import { PlannerClient } from '../services/PlannerClient';
import { SessionStore } from '../domain/SessionStore';
interface NativeEvent {type:string;message?:string;}
interface CaptureSplit {split:number;}
interface ProbeView {yaw:number;pitch:number;panX:number;}
interface BackendHealth {modelConfigured:boolean;}
interface ProbeImageSize {width:number;height:number;}
interface ProductStats {ready:boolean;lidProgress:number;animationFrames:number;}
@Entry
@Component
struct NativeEsProbe {
 @State message:string='原生探针初始化中';
 @State showSurface:boolean=true;
 @State probeRunning:boolean=true;
 private cycles:number=0;
 private sessionKey:string='es-probe';
 private context:common.UIAbilityContext=this.getUIContext().getHostContext() as common.UIAbilityContext;
 private bound:boolean=false;
 private async run():Promise<void>{this.probeRunning=true;try{
  const feather=await native.request(this.sessionKey,JSON.stringify({type:'FEATHER_PROBE'}));console.info('SELF_FEATHER_PROBE '+feather.json);
  const capability=await native.request(this.sessionKey,JSON.stringify({type:'RECON_SUPPORT'}));console.info('SELF_RECON_SUPPORT '+capability.json);
  const probe=await native.request(this.sessionKey,JSON.stringify({type:'PROBE'}));this.save('native-probe.png',probe.bytes);console.info('SELF_ES_PROBE '+probe.json);
  for(let i=1;i<=8;i++){const fixture=await this.context.resourceManager.getRawFileContent('native-fixtures/orientation-'+i+'.jpg');const normalized=await native.request(this.sessionKey,JSON.stringify({type:'NORMALIZE'}),fixture.buffer as ArrayBuffer);this.save('orientation-'+i+'.png',normalized.bytes);console.info('SELF_EXIF '+i+' '+normalized.json);}
  const odd=await this.context.resourceManager.getRawFileContent('native-fixtures/odd-stride.png');const normalizedOdd=await native.request(this.sessionKey,JSON.stringify({type:'NORMALIZE'}),odd.buffer as ArrayBuffer);this.save('odd-stride.png',normalizedOdd.bytes);
  const glb=await this.context.resourceManager.getRawFileContent('assets/sample-head.glb');
  const loaded=await native.request(this.sessionKey,JSON.stringify({type:'LOAD',kind:'glb'}),glb.buffer as ArrayBuffer);console.info('SELF_ES_GLB '+loaded.json);
  for(const name of ['lip','editable','protectionTest']){const mask=await this.context.resourceManager.getRawFileContent('assets/'+name+'.mask');await native.request(this.sessionKey,JSON.stringify({type:'MASK',id:name}),mask.buffer as ArrayBuffer);}
  const exported=await native.request(this.sessionKey,JSON.stringify({type:'EXPORT',width:768,height:1024}));this.save('native-face.png',exported.bytes);
  const selection=await native.request(this.sessionKey,JSON.stringify({type:'SELECT',points:[[.35,.32],[.66,.32],[.66,.55],[.35,.55]]}));this.save('native-selection.mask',selection.bytes);await native.request(this.sessionKey,JSON.stringify({type:'MASK',id:'probe-region'}),selection.bytes);
  const selectedPixels=new Uint8Array(selection.bytes).filter((v:number)=>v>0).length;console.info('SELF_ES_SELECTION '+selectedPixels);
  const operations:RenderOperation[]=[{operationId:'probe-op',regionId:'lip',color:[.66,.12,.30],absoluteStrength:.32}];
  const edited=await native.request(this.sessionKey,JSON.stringify({type:'EDIT',operations,anchorOperations:[],protectionId:'protectionTest'}));console.info('SELF_ES_EDIT '+edited.json);
  const editPNG=await native.request(this.sessionKey,JSON.stringify({type:'EXPORT',width:768,height:1024}));this.save('native-edit.png',editPNG.bytes);
  const repeat=await native.request(this.sessionKey,JSON.stringify({type:'EDIT',operations,anchorOperations:[],protectionId:'protectionTest'}));
  const repeatPNG=await native.request(this.sessionKey,JSON.stringify({type:'EXPORT',width:768,height:1024}));this.save('native-repeat.png',repeatPNG.bytes);
  const captured=await native.request(this.sessionKey,JSON.stringify({type:'SNAPSHOT',regionId:'lip',width:768,height:1024}));const split=(JSON.parse(captured.json) as CaptureSplit).split;
  this.save('snapshot-clean.png',captured.bytes.slice(0,split));this.save('snapshot-marked.png',captured.bytes.slice(split));console.info('SELF_ES_SNAPSHOT '+captured.json);
  await native.request(this.sessionKey,JSON.stringify({type:'EDIT',operations,anchorOperations:[],protectionId:'lip',protectionRuleId:'probe-rule'}));
  const blocked=await native.request(this.sessionKey,JSON.stringify({type:'EXPORT',width:768,height:1024}));this.save('protected-blocked.png',blocked.bytes);
  operations[0].protectionException='probe-rule';
  const exception=await native.request(this.sessionKey,JSON.stringify({type:'EDIT',operations,anchorOperations:[],protectionId:'lip',protectionRuleId:'probe-rule'}));console.info('SELF_ES_EXCEPTION '+exception.json);
  const allowed=await native.request(this.sessionKey,JSON.stringify({type:'EXPORT',width:768,height:1024}));this.save('protected-exception.png',allowed.bytes);
  operations.push({operationId:'not-authorized-in-protection',regionId:'lip',color:[.65,.25,.18],absoluteStrength:.5});
  await native.request(this.sessionKey,JSON.stringify({type:'EDIT',operations,anchorOperations:[],protectionId:'lip',protectionRuleId:'probe-rule'}));
  const later=await native.request(this.sessionKey,JSON.stringify({type:'EXPORT',width:768,height:1024}));this.save('protected-later.png',later.bytes);
  await native.request(this.sessionKey,JSON.stringify({type:'EDIT',operations:[],anchorOperations:[],protectionId:''}));
  const modern:RenderOperation[]=[{operationId:'modern',regionId:'lip',color:[.66,.12,.30],absoluteStrength:.32,compositingVersion:'perceptual-v2'}];
  const modernResult=await native.request(this.sessionKey,JSON.stringify({type:'EDIT',operations:modern,anchorOperations:[],protectionId:'protectionTest',animate:true}));console.info('SELF_V2_CHECK '+modernResult.json);
  await new Promise<void>((resolve:()=>void)=>{setTimeout(resolve,1200);});
  this.save('v2-edit.png',(await native.request(this.sessionKey,JSON.stringify({type:'EXPORT',width:768,height:1024}))).bytes);
  await native.request(this.sessionKey,JSON.stringify({type:'EDIT',operations:modern,anchorOperations:[],protectionId:'protectionTest'}));
  this.save('v2-repeat.png',(await native.request(this.sessionKey,JSON.stringify({type:'EXPORT',width:768,height:1024}))).bytes);
  await native.request(this.sessionKey,JSON.stringify({type:'EDIT',operations:modern,anchorOperations:[],protectionId:'lip'}));
  this.save('v2-blocked.png',(await native.request(this.sessionKey,JSON.stringify({type:'EXPORT',width:768,height:1024}))).bytes);
  await native.request(this.sessionKey,JSON.stringify({type:'EDIT',operations:[],anchorOperations:[],protectionId:''}));
  await native.request(this.sessionKey,JSON.stringify({type:'VIEW',yaw:.65}));const side=await native.request(this.sessionKey,JSON.stringify({type:'EXPORT',width:768,height:1024}));this.save('native-side.png',side.bytes);await native.request(this.sessionKey,JSON.stringify({type:'VIEW',yaw:0}));
  let malformedRejected=false;try{await native.request(this.sessionKey,JSON.stringify({type:'LOAD',kind:'glb'}),new Uint8Array([0,1,2,3]).buffer as ArrayBuffer);}catch(e){malformedRejected=true;}
  if(!malformedRejected)throw new Error('Malformed GLB accepted');const afterReject=await native.request(this.sessionKey,JSON.stringify({type:'EXPORT',width:768,height:1024}));this.save('after-invalid-glb.png',afterReject.bytes);
  const photoLoaded=await native.request(this.sessionKey,JSON.stringify({type:'LOAD',kind:'photo'}),odd.buffer as ArrayBuffer);
  this.save('legacy-photo-base.png',(await native.request(this.sessionKey,JSON.stringify({type:'EXPORT',width:768,height:1024}))).bytes);
  const photoSize=JSON.parse(photoLoaded.json) as ProbeImageSize;
  const fullMask=new Uint8Array(photoSize.width*photoSize.height);fullMask.fill(255);
  await native.request(this.sessionKey,JSON.stringify({type:'MASK',id:'legacy-full'}),fullMask.buffer as ArrayBuffer);
  const legacyLayers:RenderOperation[]=[{operationId:'legacy-first',regionId:'legacy-full',color:[.66,.12,.30],absoluteStrength:.5},{operationId:'legacy-second',regionId:'legacy-full',color:[.65,.25,.18],absoluteStrength:.5}];
  await native.request(this.sessionKey,JSON.stringify({type:'EDIT',operations:legacyLayers,anchorOperations:[],protectionId:''}));
  this.save('legacy-photo-layers.png',(await native.request(this.sessionKey,JSON.stringify({type:'EXPORT',width:768,height:1024}))).bytes);
  await native.request(this.sessionKey,JSON.stringify({type:'EDIT',operations:[],anchorOperations:[],protectionId:''}));
  const photoSelection=await native.request(this.sessionKey,JSON.stringify({type:'SELECT',points:[[.42,.42],[.58,.42],[.58,.58],[.42,.58]]}));
  const photoPixels=new Uint8Array(photoSelection.bytes).filter((v:number)=>v>0).length;if(photoPixels===0)throw new Error('Photo lasso is empty');this.save('photo-selection.mask',photoSelection.bytes);
  await native.request(this.sessionKey,JSON.stringify({type:'VIEW',yaw:.6,pitch:.3,panX:.4}));const actualView=await native.request(this.sessionKey,JSON.stringify({type:'GET_VIEW'}));const view=JSON.parse(actualView.json) as ProbeView;if(view.yaw!==0||view.pitch!==0||Math.abs(view.panX-.4)>.00001)throw new Error('Photo view is not flat');
  const photoPNG=await native.request(this.sessionKey,JSON.stringify({type:'EXPORT',width:768,height:1024}));this.save('native-photo.png',photoPNG.bytes);console.info('SELF_ES_PHOTO '+JSON.stringify({selectedPixels:photoPixels,view,malformedRejected}));
  await native.request(this.sessionKey,JSON.stringify({type:'LOAD',kind:'glb'}),glb.buffer as ArrayBuffer);await native.request(this.sessionKey,JSON.stringify({type:'VIEW'}));
  await this.productProbe();
  const stats=await native.request(this.sessionKey,JSON.stringify({type:'STATS'}));console.info('SELF_ES_STATS '+stats.json);console.info('SELF_ES_PROBE_FINISHED');
  this.message='原生 GLB 已加载 · 示例资产';await this.networkProbe(odd.buffer as ArrayBuffer);
 }catch(e){this.message=String(e);console.error('SELF_ES_FAIL '+String(e));}finally{this.probeRunning=false;}}
 private async productProbe():Promise<void>{
  for(const style of ['red-jar','black-jar','white-pump','black-tube','white-set','white-ampoule']){
   for(const lid of [false,true]){const bytes=await this.context.resourceManager.getRawFileContent('products/3d/'+style+(lid?'-lid.glb':'-body.glb'));await native.request(this.sessionKey,JSON.stringify({type:'PRODUCT_LOAD',lid}),bytes.buffer as ArrayBuffer);}
   this.save('product-'+style+'-closed.png',(await native.request(this.sessionKey,JSON.stringify({type:'EXPORT',width:400,height:400}))).bytes);
   await native.request(this.sessionKey,JSON.stringify({type:'PRODUCT_LID',open:true,motion:true,direction:style==='black-tube'?-1:1}));
   await new Promise<void>((resolve:()=>void)=>{setTimeout(resolve,300);});
   this.save('product-'+style+'-moving.png',(await native.request(this.sessionKey,JSON.stringify({type:'EXPORT',width:400,height:400}))).bytes);
   await new Promise<void>((resolve:()=>void)=>{setTimeout(resolve,750);});
   this.save('product-'+style+'-open.png',(await native.request(this.sessionKey,JSON.stringify({type:'EXPORT',width:400,height:400}))).bytes);
   const stats=JSON.parse((await native.request(this.sessionKey,JSON.stringify({type:'PRODUCT_STATS'}))).json) as ProductStats;
   if(!stats.ready||stats.lidProgress!==1||stats.animationFrames===0)throw new Error('Product animation did not finish');
   await native.request(this.sessionKey,JSON.stringify({type:'PRODUCT_VIEW',yaw:.6,pitch:-.22}));
   this.save('product-'+style+'-side.png',(await native.request(this.sessionKey,JSON.stringify({type:'EXPORT',width:400,height:400}))).bytes);
   await native.request(this.sessionKey,JSON.stringify({type:'PRODUCT_LID',open:false,motion:false}));
   const stopped=JSON.parse((await native.request(this.sessionKey,JSON.stringify({type:'PRODUCT_STATS'}))).json) as ProductStats;
   if(stopped.lidProgress!==0)throw new Error('Product reduce-motion failed');
   console.info('SELF_PRODUCT_PROBE '+JSON.stringify({style,stats,reducedMotionClosed:true}));
  }
  let editRejected=false;try{await native.request(this.sessionKey,JSON.stringify({type:'EDIT',operations:[]}));}catch(e){editRejected=true;}if(!editRejected)throw new Error('Product accepted face edit');
  await native.request(this.sessionKey,JSON.stringify({type:'PRODUCT_END'}));
  this.save('face-after-products.png',(await native.request(this.sessionKey,JSON.stringify({type:'EXPORT',width:768,height:1024}))).bytes);
 }
 private async networkProbe(fixture:ArrayBuffer):Promise<void>{
  const request=http.createHttp();
  try{const response=await request.request('http://127.0.0.1:8787/health',{expectDataType:http.HttpDataType.STRING,connectTimeout:3000,readTimeout:3000,usingCache:false});
   if(response.responseCode!==200)throw new Error('Backend health not ready');const health=JSON.parse(response.result as string) as BackendHealth;
   // This automatic connectivity probe sends only the original color-block fixture and never sends a face.
   // Paid vision capability tests remain the separately invoked two-image backend test.
   if(health.modelConfigured){console.info('SELF_NETWORKKIT '+JSON.stringify({healthStatus:200,modelConfigured:true,paidCall:'not attempted in connectivity probe'}));return;}
   const session=new SessionStore(),client=new PlannerClient();let failedSafely=false;
   try{await client.propose(client.snapshot(session,'原创彩色块网络探针，无个人图像。'),[fixture]);}catch(e){failedSafely=String(e).includes('502');}
   if(!failedSafely)throw new Error('Missing-key response was not rejected');
   console.info('SELF_NETWORKKIT '+JSON.stringify({healthStatus:200,modelConfigured:false,missingKeyRejected:true,operationsAfterFailure:session.operations.length,paidCall:'not sent'}));
  }catch(e){console.info('SELF_NETWORKKIT_UNVERIFIED '+String(e));}finally{request.destroy();}
 }
 private save(name:string,data:ArrayBuffer):void{const file=fs.openSync(this.context.filesDir+'/'+name,fs.OpenMode.CREATE|fs.OpenMode.READ_WRITE|fs.OpenMode.TRUNC);try{fs.writeSync(file.fd,data);}finally{fs.closeSync(file);}}
 private unbind():void{if(this.bound){native.unbind(this.sessionKey);this.bound=false;}}
 aboutToDisappear():void{this.unbind();}
 build(){Column(){
  Text(this.message).fontSize(18).padding(16)
  if(this.showSurface){XComponent({type:XComponentType.SURFACE}).id('self-es-probe').width('100%').layoutWeight(1)
   .onAttach(()=>{const node=this.getUIContext().getAttachedFrameNodeById('self-es-probe');if(node){this.bound=true;native.bind(this.sessionKey,node,(text:string)=>{if(!this.bound)return;console.info('SELF_ES_EVENT '+text);const event=JSON.parse(text) as NativeEvent;if(event.type==='READY'){this.cycles++;console.info('SELF_SURFACE_CYCLE '+this.cycles);this.run();}else if(event.type==='ERROR')this.message=event.message||'原生失败';});}})
   .onDetach(()=>this.unbind())
  }else{Blank().layoutWeight(1)}
  Button('重建表面').enabled(!this.probeRunning).onClick(()=>{this.probeRunning=true;this.showSurface=false;setTimeout(()=>{this.showSurface=true;},250);})
  Row(){Button('左侧').onClick(()=>native.request(this.sessionKey,JSON.stringify({type:'VIEW',yaw:-.65})));Button('正面').onClick(()=>native.request(this.sessionKey,JSON.stringify({type:'VIEW',yaw:0})));Button('右侧').onClick(()=>native.request(this.sessionKey,JSON.stringify({type:'VIEW',yaw:.65})));}
 }.width('100%').height('100%').backgroundColor('#F0ECF0')}
}

