import { ProductRepository,ProductRecord } from './ProductRepository';
import { http } from '@kit.NetworkKit';
import { util } from '@kit.ArkTS';
import { SessionStore } from '../domain/SessionStore';
import { SceneView, EditOperation, RegionRecord } from '../domain/EditPlan';
export interface CloudOperation {operation:string;regionId:string;presetId:string;intensityLevel:string;layerId:string;productProfileId:string;}
export interface CloudPlan {decision:string;shortMessage:string;operations:CloudOperation[];explanationRefs:string[];question:string;}
interface CloudRegion {regionId:string;description:string;semantic:string;}
interface CloudLayer {layerId:string;regionId:string;presetId:string;intensityLevel:string;}
export interface CloudSnapshot {
 schemaVersion:number;requestId:string;snapshotId:string;assetId:string;assetVersion:string;textureVersion:string;
 sceneRevision:number;regionVersion:number;viewRevision:number;view:SceneView;userText:string;
 regions:CloudRegion[];layers:CloudLayer[];protectedRegionIds:string[];productContextIds?:string[];uploadAuthorized:boolean;
 imageWidth:number;imageHeight:number;annotatedRegionId:string;
}
interface ModelEvidence {requestedModel:string;returnedModel:string;systemFingerprint:string|null;elapsedMs:number;}
export interface CloudResponse {schemaVersion:number;requestId:string;snapshotId:string;assetId:string;assetVersion:string;textureVersion:string;sceneRevision:number;regionVersion:number;plan:CloudPlan;modelEvidence:ModelEvidence;}
interface WireRequest {snapshot:CloudSnapshot;images:string[];}
export class PlannerClient {
 private active:http.HttpRequest|undefined=undefined;private generation:number=0;
 endpoint:string='http://127.0.0.1:8787';token:string='';
 static level(strength:number):string{return strength===0?'none':strength<=.22?'light':strength<=.4?'medium':'strong';}
 static strength(level:string):number{if(level==='none')return 0;if(level==='light')return .18;if(level==='medium')return .32;if(level==='strong')return .5;throw new Error('模型强度超出支持范围');}
 snapshot(session:SessionStore,text:string):CloudSnapshot{
  const id='request-'+Date.now()+'-'+Math.floor(Math.random()*1000000);
  return {schemaVersion:1,requestId:id,snapshotId:'snapshot-'+id,assetId:session.assetId,assetVersion:session.assetVersion,textureVersion:session.textureVersion,
   sceneRevision:session.sceneRevision,regionVersion:session.regionVersion,viewRevision:session.viewRevision,view:JSON.parse(JSON.stringify(session.view)) as SceneView,userText:text,
   regions:session.regions.filter((r:RegionRecord)=>r.regionId!=='editable'&&r.regionId!=='protectionTest').map((r:RegionRecord)=>({regionId:r.regionId,description:r.semantic==='confirmed-lips'?'示例资产已确认的保守唇区':'用户手工确认的区域',semantic:r.semantic==='confirmed-lips'?'confirmed-lips':'manual'} as CloudRegion)),
   layers:session.operations.map((op:EditOperation)=>({layerId:op.operationId,regionId:op.regionId,presetId:op.presetId,intensityLevel:PlannerClient.level(op.absoluteStrength)} as CloudLayer)),
   protectedRegionIds:session.protection?[session.protection.regionId]:[],uploadAuthorized:true,imageWidth:768,imageHeight:1024,annotatedRegionId:''};
 }
 cancel():void{this.generation++;if(this.active){this.active.destroy();this.active=undefined;}}
 async propose(snapshot:CloudSnapshot,images:ArrayBuffer[]):Promise<CloudResponse>{
  this.cancel();const generation=this.generation;
  if(!this.endpoint.startsWith('https://')&&this.endpoint!=='http://127.0.0.1:8787')throw new Error('后端须使用 HTTPS；本机调试仅限明确的回环端口');
  const request=http.createHttp();this.active=request;
  try{const encoder=new util.Base64Helper();const body:WireRequest={snapshot,images:images.map((bytes:ArrayBuffer)=>encoder.encodeToStringSync(new Uint8Array(bytes)))};
   const response=await request.request(this.endpoint+'/v1/edit-plans',{method:http.RequestMethod.POST,header:{'Content-Type':'application/json','Authorization':this.token?'Bearer '+this.token:''},extraData:JSON.stringify(body),expectDataType:http.HttpDataType.STRING,connectTimeout:10000,readTimeout:55000,usingCache:false});
   if(generation!==this.generation)throw new Error('这次请求已取消');
   if(response.responseCode!==200)throw new Error('云端暂未完成（'+response.responseCode+'），当前作品未改动');
   const result=JSON.parse(response.result as string) as CloudResponse;
   if(result.schemaVersion!==1||result.requestId!==snapshot.requestId||result.snapshotId!==snapshot.snapshotId||result.assetId!==snapshot.assetId||result.assetVersion!==snapshot.assetVersion||result.textureVersion!==snapshot.textureVersion||result.sceneRevision!==snapshot.sceneRevision||result.regionVersion!==snapshot.regionVersion)throw new Error('模型回复与当前快照不一致');
   this.validate(result.plan,snapshot);return result;
  }finally{request.destroy();if(this.active===request)this.active=undefined;}
 }
  validate(plan:CloudPlan,snapshot:CloudSnapshot):void{
  const productFollowup=(snapshot.productContextIds?.length||0)>0&&/这款|这个|它|试一下|试试|淡一点|参数|效果/.test(snapshot.userText);
  if(plan.decision==='edit'&&(/olay|玉兰油|产品|护肤|小白瓶|超红瓶|黑管/i.test(snapshot.userText)||productFollowup||plan.explanationRefs.length>0))throw new Error('这款产品还没有可核验的效果参数，不能用通用试色代替它');
  if(Object.keys(plan).some((key:string)=>!['decision','shortMessage','operations','explanationRefs','question'].includes(key)))throw new Error('候选包含未知字段');
  if(!['edit','explain','clarify','support'].includes(plan.decision)||!plan.shortMessage||plan.shortMessage.length>400||plan.operations.length>1||plan.explanationRefs.length>3||plan.explanationRefs.some((id:string)=>!ProductRepository.records().some((p:ProductRecord)=>p.productId===id)))throw new Error('候选计划不符合协议');
  if(plan.question.length>200||(plan.decision!=='clarify'&&plan.question))throw new Error('候选提问不符合协议');
  if(plan.decision!=='edit'&&plan.operations.length)throw new Error('交流不能夹带编辑');
  if(plan.decision==='edit'&&plan.operations.length!==1)throw new Error('需要一个完整的候选操作');
  for(const op of plan.operations){if(Object.keys(op).some((key:string)=>!['operation','regionId','presetId','intensityLevel','layerId','productProfileId'].includes(key)))throw new Error('操作包含未知字段');if(!['set_digital_tint','set_effect_level','remove_effect'].includes(op.operation)||!['rose','terracotta'].includes(op.presetId)||op.productProfileId||!snapshot.regions.some((r:CloudRegion)=>r.regionId===op.regionId))throw new Error('模型引用了未登记的能力或区域');PlannerClient.strength(op.intensityLevel);
   if(op.operation!=='set_digital_tint'){const layer=snapshot.layers.find((l:CloudLayer)=>l.layerId===op.layerId);if(!layer||layer.regionId!==op.regionId||layer.presetId!==op.presetId||(op.operation==='remove_effect'&&op.intensityLevel!=='none'))throw new Error('目标编辑层已改变');}
   else if(op.layerId||op.intensityLevel==='none'||(snapshot.annotatedRegionId&&op.regionId!==snapshot.annotatedRegionId))throw new Error('新建编辑层必须对应本次圈选范围');
  }
 }
}
