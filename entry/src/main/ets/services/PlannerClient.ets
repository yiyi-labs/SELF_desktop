import { common } from '@kit.AbilityKit';
import { util } from '@kit.ArkTS';
import { ProductRepository,ProductRecord } from './ProductRepository';
import { OlayDiscoveryRepository,OlayDiscoveryItem } from './OlayDiscoveryRepository';
import { SessionStore } from '../domain/SessionStore';
import { SceneView, EditOperation, RegionRecord } from '../domain/EditPlan';
import { DeepSeekConfig } from './DeepSeekConfig';
import { DeepSeekRequestBody,DeepSeekRawResponse,DeepSeekContentPart,DeepSeekImagePart,DeepSeekError,PLAN_TOOL_SCHEMA_JSON } from './DeepSeekTypes';
import { DeepSeekTransport } from './DeepSeekTransport';
import { DeepSeekRuntimeState } from './DeepSeekRuntimeState';
import { DeepSeekCredentialStore } from './DeepSeekCredentialStore';
import { PlannerPrompts } from './PlannerPrompts';
import { PlannerPlanNormalizer } from './PlannerPlanNormalizer';
import { CareCatalog,CareOption } from './CareCatalog';
import { ProductCatalog } from './ProductCatalog';
import { ProductKnowledge,IdentityIndexItem,ProductDetail } from './ProductKnowledge';
import { ResponseQuality } from './ResponseQuality';
export interface CloudOperation {operation:string;regionId:string;presetId:string;intensityLevel:string;layerId:string;productProfileId:string;}
export interface CloudCareGuide {productId:string;whyHere:string;howToUse:string;}
export interface SelectionObservation {regionId:string;area:string;concern:string;confidence:string;basis:string;}
export interface CloudPlan {decision:string;shortMessage:string;operations:CloudOperation[];explanationRefs:string[];question:string;choices?:string[];careGuide?:CloudCareGuide|null;selectionObservations?:SelectionObservation[];}
export interface DialogueTurn {userText:string;reply:string;choices:string[];productIds?:string[];}
export interface CloudRegion {regionId:string;description:string;semantic:string;}
interface CloudLayer {layerId:string;regionId:string;presetId:string;intensityLevel:string;}
export interface CloudSnapshot {
 schemaVersion:number;requestId:string;snapshotId:string;assetId:string;assetVersion:string;textureVersion:string;
 sceneRevision:number;regionVersion:number;viewRevision:number;view:SceneView;userText:string;
 regions:CloudRegion[];layers:CloudLayer[];protectedRegionIds:string[];productContextIds?:string[];uploadAuthorized:boolean;
 imageWidth:number;imageHeight:number;annotatedRegionId:string;
 annotatedRegionIds?:string[];
 dialogue?:DialogueTurn[];resolvedChoice?:string;responseLanguage?:string;
 careAdviceRequested?:boolean;
 dismissedProducts?:boolean;
}
interface ModelEvidence {requestedModel:string;returnedModel:string;systemFingerprint:string|null;elapsedMs:number;}
export interface CloudResponse {schemaVersion:number;requestId:string;snapshotId:string;assetId:string;assetVersion:string;textureVersion:string;sceneRevision:number;regionVersion:number;plan:CloudPlan;modelEvidence:ModelEvidence;}
interface PresetInfo{displayName:string;color:number[];}
interface ContextDialogueTurn{userText:string;reply:string;choices:string[];productIds:string[];}
interface PlannerContext{
 schemaVersion:number;requestId:string;snapshotId:string;assetId:string;assetVersion:string;textureVersion:string;
 sceneRevision:number;regionVersion:number;viewRevision:number;view:SceneView;userText:string;
 productContextIds:string[];dialogue:ContextDialogueTurn[];resolvedChoice:string;responseLanguage:string;
 careAdviceRequested:boolean;dismissedProducts:boolean;regions:CloudRegion[];layers:CloudLayer[];
 protectedRegionIds:string[];imageWidth:number;imageHeight:number;annotatedRegionId:string;annotatedRegionIds:string[];
 presets:Record<string,PresetInfo>;productInformation:ProductDetail[];careOptions:CareOption[];
 productIdentityIndex:IdentityIndexItem[];requestIntent:string;calibratedProductEffects:string[];
 imageMeaning:string;
}
export type PlannerResponder=(body:DeepSeekRequestBody,timeoutMs:number)=>Promise<DeepSeekRawResponse>;
/**
 * Phone-side Beauty Planner: assembles the same context the Python backend assembled, calls
 * DeepSeek HTTPS directly, then funnels the model's tool arguments through ONE validator —
 * this class's validate(). Nothing the model returns reaches the session unvalidated.
 */
export class PlannerClient {
 private context:common.UIAbilityContext;
 private generation:number=0;
 constructor(context:common.UIAbilityContext){this.context=context;}
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
 cancel():void{this.generation++;DeepSeekTransport.shared().cancelOwner('planner');}
 /** Direct HTTPS to the official DeepSeek API; the key is decrypted just for this call. */
 async propose(snapshot:CloudSnapshot,images:ArrayBuffer[]):Promise<CloudResponse>{
  const context=this.context;
  return this.proposeWith(snapshot,images,async(body:DeepSeekRequestBody,timeoutMs:number):Promise<DeepSeekRawResponse>=>{
   const key=await DeepSeekCredentialStore.loadForRequest(context);
   return DeepSeekTransport.shared().chat(body,key,timeoutMs,'planner');
  });
 }
 /** Same orchestration with an injected responder so repair behaviour is testable without network. */
 async proposeWith(snapshot:CloudSnapshot,images:ArrayBuffer[],responder:PlannerResponder):Promise<CloudResponse>{
  this.cancel();const generation=this.generation;
  if(!DeepSeekRuntimeState.allowRequests)throw new DeepSeekError('background','SELF 已进入后台，这次请求已停止。');
  if(images.length<1||images.length>2)throw new DeepSeekError('image_rejected','需要一张当前画面，最多两张。');
  const started=Date.now();
  const body=await this.buildRequestBody(this.context,snapshot,images);
  let plan:CloudPlan|undefined=undefined;let raw:DeepSeekRawResponse|undefined=undefined;
  // One repair within the same authorized snapshot; never show a loop.
  for(let attempt=0;attempt<2;attempt++){
   if(!DeepSeekRuntimeState.allowRequests)throw new DeepSeekError('background','SELF 已进入后台，这次请求已停止。');
   const remaining=DeepSeekConfig.PLANNER_BUDGET_MS-(Date.now()-started);
   if(remaining<=0)throw new DeepSeekError('timeout','DeepSeek 回复超时，请稍后再试。');
   raw=await responder(body,Math.min(remaining,DeepSeekConfig.PLANNER_READ_TIMEOUT_MS));
   if(generation!==this.generation)throw new DeepSeekError('cancelled','这次请求已取消。');
   let parsed:CloudPlan;
   try{parsed=await this.parseAndValidate(this.context,raw,snapshot);}
   catch(e){
    if(attempt===0){
     body.messages[0].content=(body.messages[0].content as string)+PlannerPrompts.PROTOCOL_REPAIR;
     continue;
    }
    throw new DeepSeekError('invalid_plan','DeepSeek 返回了无法验证的方案。');
   }
   const previous=(snapshot.dialogue||[]).map((turn:DialogueTurn)=>turn.reply);
   const duplicate=ResponseQuality.repeats(parsed.shortMessage,previous)||
    (!!parsed.question&&ResponseQuality.repeats(parsed.question,previous));
   const selected:string[]=snapshot.annotatedRegionIds&&snapshot.annotatedRegionIds.length?snapshot.annotatedRegionIds:(snapshot.annotatedRegionId?[snapshot.annotatedRegionId]:[]);
   const observed=new Set<string>((parsed.selectionObservations||[]).map((o:SelectionObservation)=>o.regionId));
   const missingAnalysis=selected.length>0&&CareCatalog.careIntent(snapshot.userText)&&!PlannerPlanNormalizer.listeningOnly(snapshot.userText)&&
    (observed.size!==selected.length||selected.some((id:string)=>!observed.has(id)));
   if(!duplicate&&!missingAnalysis){plan=parsed;break;}
   if(attempt===1)throw new DeepSeekError(duplicate?'repeated_response':'missing_selection_analysis',
    duplicate?'这次的回复和之前重复了，请换一种说法再试。':'这次没能完整识别圈选的部位，请再试一次。');
   body.messages[0].content=(body.messages[0].content as string)+PlannerPrompts.QUALITY_REPAIR;
  }
  if(!plan||!raw)throw new DeepSeekError('invalid_plan','DeepSeek 返回了无法验证的方案。');
  return{schemaVersion:1,requestId:snapshot.requestId,snapshotId:snapshot.snapshotId,
   assetId:snapshot.assetId,assetVersion:snapshot.assetVersion,textureVersion:snapshot.textureVersion,
   sceneRevision:snapshot.sceneRevision,regionVersion:snapshot.regionVersion,plan,
   modelEvidence:{requestedModel:DeepSeekConfig.MODEL,returnedModel:raw.model||'',
    systemFingerprint:raw.system_fingerprint??null,elapsedMs:Date.now()-started}};
 }
 private static imageMime(bytes:ArrayBuffer):string{
  const view=new Uint8Array(bytes);
  if(view.length>DeepSeekConfig.MAX_IMAGE_BYTES)throw new DeepSeekError('image_rejected','这张画面太大，请重新圈选后再试。');
  if(view.length>=4&&view[0]===137&&view[1]===80&&view[2]===78&&view[3]===71)return'image/png';
  if(view.length>=3&&view[0]===255&&view[1]===216&&view[2]===255)return'image/jpeg';
  throw new DeepSeekError('image_rejected','画面格式无法识别。');
 }
 private async buildRequestBody(context:common.UIAbilityContext,snapshot:CloudSnapshot,images:ArrayBuffer[]):Promise<DeepSeekRequestBody>{
  const language=snapshot.responseLanguage||'zh';
  const contextText=await PlannerClient.buildContext(context,snapshot);
  const content:DeepSeekContentPart[]=[{type:'text',text:contextText}];
  const encoder=new util.Base64Helper();
  for(const image of images){
   const mime=PlannerClient.imageMime(image);
   const encoded=encoder.encodeToStringSync(new Uint8Array(image));
   const part:DeepSeekImagePart={type:'image_url',image_url:{url:'data:'+mime+';base64,'+encoded}};
   content.push(part);
  }
  let system=PlannerPlanNormalizer.listeningOnly(snapshot.userText)?PlannerPrompts.LISTENING_SYSTEM:PlannerPrompts.PLANNER_SYSTEM;
  system=PlannerPrompts.applyLanguage(system,language)+PlannerPrompts.plannerDirective(language);
  return{model:DeepSeekConfig.MODEL,thinking:{type:'disabled'},stream:false,max_tokens:2000,
   messages:[{role:'system',content:system},{role:'user',content}],
   tools:[JSON.parse(PLAN_TOOL_SCHEMA_JSON) as object],
   tool_choice:{type:'function',function:{name:'propose_edit_plan'}}};
 }
 private static async buildContext(context:common.UIAbilityContext,snapshot:CloudSnapshot):Promise<string>{
  const presets:Record<string,PresetInfo>={
   'rose':{displayName:'柔玫瑰',color:[0.66,0.12,0.30]},
   'terracotta':{displayName:'暖陶棕',color:[0.65,0.25,0.18]}};
  const dialogue:ContextDialogueTurn[]=(snapshot.dialogue||[]).map((turn:DialogueTurn):ContextDialogueTurn=>{
   return{userText:turn.userText,reply:turn.reply,choices:turn.choices||[],productIds:turn.productIds||[]};});
  const plannerContext:PlannerContext={
   schemaVersion:snapshot.schemaVersion,requestId:snapshot.requestId,snapshotId:snapshot.snapshotId,
   assetId:snapshot.assetId,assetVersion:snapshot.assetVersion,textureVersion:snapshot.textureVersion,
   sceneRevision:snapshot.sceneRevision,regionVersion:snapshot.regionVersion,viewRevision:snapshot.viewRevision,
   view:snapshot.view,userText:snapshot.userText,
   productContextIds:snapshot.productContextIds||[],dialogue,resolvedChoice:snapshot.resolvedChoice||'',
   responseLanguage:snapshot.responseLanguage||'zh',careAdviceRequested:!!snapshot.careAdviceRequested,
   dismissedProducts:!!snapshot.dismissedProducts,regions:snapshot.regions,layers:snapshot.layers,
   protectedRegionIds:snapshot.protectedRegionIds,imageWidth:snapshot.imageWidth,imageHeight:snapshot.imageHeight,
   annotatedRegionId:snapshot.annotatedRegionId||'',annotatedRegionIds:snapshot.annotatedRegionIds||[],
   presets,
   productInformation:await ProductCatalog.lookup(context,snapshot.userText,snapshot.productContextIds||[]),
   careOptions:await CareCatalog.careOptions(context,snapshot.userText,!!snapshot.careAdviceRequested,CareCatalog.catalogLanguage(snapshot.responseLanguage||'zh')),
   productIdentityIndex:await ProductKnowledge.identityIndex(context),
   requestIntent:CareCatalog.careIntent(snapshot.userText)?'care':'edit_or_conversation',
   calibratedProductEffects:[],
   imageMeaning:'First: clean current view, without UI. Optional second: same snapshot with numbered region annotations; these are user selections, NOT skin features. Use only selected regionIds.'};
  return JSON.stringify(plannerContext);
 }
 /** Tool arguments are untrusted input: structure, normalise, then the single validator decides. */
 private async parseAndValidate(context:common.UIAbilityContext,raw:DeepSeekRawResponse,snapshot:CloudSnapshot):Promise<CloudPlan>{
  const invalid=():DeepSeekError=>new DeepSeekError('invalid_plan','DeepSeek 返回了无法验证的方案。');
  const choices=raw.choices;
  if(!choices||choices.length!==1||choices[0].finish_reason!=='tool_calls')throw invalid();
  const calls=choices[0].message.tool_calls;
  if(!calls||calls.length!==1||calls[0].type!=='function'||calls[0].function.name!=='propose_edit_plan')throw invalid();
  const args=calls[0].function.arguments;
  if(!args||args.length>DeepSeekConfig.MAX_TOOL_ARGUMENTS)throw invalid();
  let plan:CloudPlan;
  try{plan=JSON.parse(args) as CloudPlan;}catch(_){throw invalid();}
  if(typeof plan.decision!=='string'||typeof plan.shortMessage!=='string'||typeof plan.question!=='string'||
   !Array.isArray(plan.operations)||!Array.isArray(plan.explanationRefs))throw invalid();
  await PlannerPlanNormalizer.normalize(context,plan,snapshot);
  await this.validate(context,plan,snapshot);
  return plan;
 }
 /**
  * The one and only plan validator (the phone-side final gate, now also carrying the
  * checks validate_plan performed on the backend). Model output never skips it.
  */
 async validate(context:common.UIAbilityContext,plan:CloudPlan,snapshot:CloudSnapshot):Promise<void>{
  const text=snapshot.userText;
  if(PlannerPlanNormalizer.listeningOnly(text)&&plan.decision==='edit')throw new Error('这次只想聊聊，先不修改面容');
  if(plan.decision==='edit'&&(await ProductCatalog.requestsProductEffect(context,text,snapshot.productContextIds||[])||plan.explanationRefs.length>0))
   throw new Error('这款产品还没有可核验的效果参数，不能用通用试色代替它');
  if(Object.keys(plan).some((key:string)=>!['decision','shortMessage','operations','explanationRefs','question','choices','careGuide','selectionObservations'].includes(key)))throw new Error('候选包含未知字段');
  const observations:SelectionObservation[]=plan.selectionObservations||[];
  const clear=observations.filter((o:SelectionObservation)=>o.confidence==='clear');
  const areas=new Set<string>(clear.map((o:SelectionObservation)=>o.area));
  const area=areas.size===1?Array.from(areas)[0]:'';
  const concern=clear.some((o:SelectionObservation)=>o.concern==='blemish')?'blemish':'';
  if(plan.careGuide){
   const guide=plan.careGuide;
   if(plan.decision==='support'||!snapshot.careAdviceRequested||!guide.whyHere||guide.whyHere.length>100||!guide.howToUse||guide.howToUse.length>140)
    throw new Error('护理建议与本次修改不匹配');
   const careIds=await CareCatalog.allowedCareIds(context,text,true,area,concern);
   if(!careIds.has(guide.productId))throw new Error('护理建议与本次修改不匹配');
   if(/保证|必然|立刻|立即|永久|复刻|还原.*(?:试色|数字)|与.*(?:试色|数字).*相同/.test(guide.whyHere+guide.howToUse))
    throw new Error('护理建议包含未标定的效果声明');
  }
  if(plan.choices&&plan.choices.length&&(plan.decision!=='clarify'||!plan.question||plan.choices.length<2||plan.choices.length>3||
   new Set(plan.choices).size!==plan.choices.length||plan.choices.some((c:string)=>!c.trim()||c.length>60)))throw new Error('对话选项无效');
  if(/\brose\b|\bterracotta\b|regionId|presetId|layerId/.test(plan.shortMessage+plan.question+(plan.choices||[]).join(' ')))throw new Error('回复包含内部标识，请重新提出请求');
  if(plan.decision!=='clarify'&&/[？?]/.test(plan.shortMessage))throw new Error('回复不应夹带问题');
  if(snapshot.careAdviceRequested&&CareCatalog.careIntent(text)&&
   /米粒|豌豆|黄豆|\d+\s*(?:滴|泵|克|毫升|ml|g)|每日|每天|早晚各|rice.grain|pea.sized/i.test(plan.shortMessage))
   throw new Error('护理建议包含未核实的用量');
  if(CareCatalog.careIntent(text)&&!/试色|颜色|柔玫瑰|暖陶棕|tint|colou?r/i.test(text)&&
   /透一点颜色|轻轻晕开|数字试色|数字上色|边缘轻轻散开/.test(plan.shortMessage))
   throw new Error('护理建议不能用数字上色代替');
  if(CareCatalog.productsDeclined(text)&&
   /(?:可以|不妨|建议|想再).{0,15}(?:看看|考虑|选|试|用).{0,8}(?:眼霜|面霜|olay|玉兰油|产品)/i.test(plan.shortMessage))
   throw new Error('已表示不需要产品推荐');
  const lastDialogue=snapshot.dialogue&&snapshot.dialogue.length?snapshot.dialogue[snapshot.dialogue.length-1]:undefined;
  if(snapshot.resolvedChoice&&(!lastDialogue||!(lastDialogue.choices||[]).includes(snapshot.resolvedChoice)))
   throw new Error('这个选择已过期，请重新描述');
  if(/^[1-3]$/.test(text.trim())&&plan.decision==='edit'){
   const index=Number(text.trim())-1;
   if(!lastDialogue||!lastDialogue.choices||index>=lastDialogue.choices.length||snapshot.resolvedChoice!==lastDialogue.choices[index])
    throw new Error('请说明这个数字对应的选择');
  }
  if(plan.decision==='edit'&&/痘|痘印|疤|acne|pimple|scar/i.test(text))throw new Error('这里更适合先做温和的日常护理');
  if(!['edit','explain','clarify','support'].includes(plan.decision)||!plan.shortMessage||plan.shortMessage.length>140||plan.operations.length>4||plan.explanationRefs.length>3||plan.explanationRefs.some((id:string)=>!ProductRepository.records().some((p:ProductRecord)=>p.productId===id)&&!OlayDiscoveryRepository.allRecords().some((p:OlayDiscoveryItem)=>p.id===id)))throw new Error('候选计划不符合协议');
  const allowed=await ProductCatalog.allowedRefs(context,text,snapshot.productContextIds||[]);
  if(plan.careGuide)allowed.add(plan.careGuide.productId);
  if(plan.explanationRefs.some((id:string)=>!allowed.has(id)))throw new Error('引用的产品资料与本次请求不匹配');
  if(plan.question.length>200||(plan.decision!=='clarify'&&plan.question))throw new Error('候选提问不符合协议');
  if(plan.decision!=='edit'&&plan.operations.length)throw new Error('交流不能夹带编辑');
  if(plan.decision==='edit'&&plan.operations.length<1)throw new Error('需要完整的候选操作');
  const selected=snapshot.annotatedRegionIds&&snapshot.annotatedRegionIds.length?snapshot.annotatedRegionIds:(snapshot.annotatedRegionId?[snapshot.annotatedRegionId]:[]);
  if(selected.length>4||new Set(selected).size!==selected.length)throw new Error('圈选区域不完整');
  if(observations.length>4||new Set(observations.map((o:SelectionObservation)=>o.regionId)).size!==observations.length||
   observations.some((o:SelectionObservation)=>!selected.includes(o.regionId)||
    !['eye','cheek','forehead','nose','chin','lips','brow','face','body','unknown'].includes(o.area)||
    !['none','blemish','dryness','texture','unknown'].includes(o.concern)||
    !['clear','uncertain'].includes(o.confidence)||!['image','user'].includes(o.basis)||
    (o.confidence==='uncertain'&&o.area!=='unknown')))throw new Error('部位识别与本次圈选不匹配');
  const resolvedChoice=snapshot.resolvedChoice||'';
  const namedPresets=['rose','terracotta'].filter((key:string)=>
   resolvedChoice.includes(key==='rose'?'柔玫瑰':'暖陶棕')||
   resolvedChoice.toLowerCase().includes(key==='rose'?'muted pink':'warm clay')||
   PlannerPlanNormalizer.containsWord(resolvedChoice.toLowerCase(),key));
  const newRegions:string[]=[];
  for(const op of plan.operations){if(Object.keys(op).some((key:string)=>!['operation','regionId','presetId','intensityLevel','layerId','productProfileId'].includes(key)))throw new Error('操作包含未知字段');if(!['set_digital_tint','set_effect_level','remove_effect'].includes(op.operation)||!['rose','terracotta'].includes(op.presetId)||op.productProfileId||!snapshot.regions.some((r:CloudRegion)=>r.regionId===op.regionId))throw new Error('模型引用了未登记的能力或区域');PlannerClient.strength(op.intensityLevel);
   if(op.operation==='set_digital_tint'&&namedPresets.length===1&&op.presetId!==namedPresets[0])throw new Error('颜色与刚才的选择不一致');
   if(op.operation!=='set_digital_tint'){const layer=snapshot.layers.find((l:CloudLayer)=>l.layerId===op.layerId);if(!layer||layer.regionId!==op.regionId||layer.presetId!==op.presetId||(op.operation==='remove_effect'&&op.intensityLevel!=='none'))throw new Error('目标编辑层已改变');}
   else if(op.layerId||op.intensityLevel==='none'||(selected.length>0&&!selected.includes(op.regionId))||newRegions.includes(op.regionId))throw new Error('新建编辑层必须对应不同的本次圈选范围');
   if(op.operation==='set_digital_tint')newRegions.push(op.regionId);
  }
 }
}
