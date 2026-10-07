import { common } from '@kit.AbilityKit';
import { CloudPlan,CloudSnapshot,CloudCareGuide,SelectionObservation } from './PlannerClient';
import { CareCatalog } from './CareCatalog';
import { ProductCatalog } from './ProductCatalog';
import { OlayResearchData } from './OlayResearchData';

/**
 * The rewriting half of the retired Python validate_plan: deterministic presentation
 * and care-guide normalisation performed on the phone before PlannerClient.validate()
 * applies the single rule set. It never authorises anything — only rewrites wording.
 */
export class PlannerPlanNormalizer {
 static listeningOnly(text:string):boolean{
  return/只想聊聊|不用修改|先不要.*编辑|不想.{0,12}(?:改成|变成).{0,8}别人|just (?:want to )?talk|no edits|do not (?:edit|change)|don.t (?:edit|change)/i.test(text);
 }
 /** Unicode-aware word replacement (JS \b is ASCII-only, unlike Python's). */
 static replaceWord(text:string,word:string,replacement:string):string{
  const lower=text.toLowerCase();let out='';let i=0;
  while(i<text.length){
   const found=lower.indexOf(word,i);
   if(found<0){out+=text.substring(i);break;}
   const before=found>0?text.charAt(found-1):'';
   const after=found+word.length<text.length?text.charAt(found+word.length):'';
   const isWordChar=(c:string):boolean=>c.length===1&&/[\p{L}\p{N}_]/u.test(c);
   if((!before||!isWordChar(before))&&(!after||!isWordChar(after))){
    out+=text.substring(i,found)+replacement;i=found+word.length;
   }else{out+=text.substring(i,found+word.length);i=found+word.length;}
  }
  return out;
 }
 static containsWord(text:string,word:string):boolean{
  const lower=text.toLowerCase();let i=0;
  while(i<text.length){
   const found=lower.indexOf(word,i);
   if(found<0)return false;
   const before=found>0?text.charAt(found-1):'';
   const after=found+word.length<text.length?text.charAt(found+word.length):'';
   const isWordChar=(c:string):boolean=>c.length===1&&/[\p{L}\p{N}_]/u.test(c);
   if((!before||!isWordChar(before))&&(!after||!isWordChar(after)))return true;
   i=found+word.length;
  }
  return false;
 }
 static display(text:string,language:string):string{
  let result=PlannerPlanNormalizer.replaceWord(text,'rose',language==='zh'?'柔玫瑰':'Muted pink');
  result=PlannerPlanNormalizer.replaceWord(result,'terracotta',language==='zh'?'暖陶棕':'Warm clay');
  return result;
 }
 static async normalize(context:common.UIAbilityContext,plan:CloudPlan,snapshot:CloudSnapshot):Promise<void>{
  const text=snapshot.userText;
  const language=snapshot.responseLanguage||'zh';
  const catalogLanguage=CareCatalog.catalogLanguage(language);
  if(plan.decision==='support'&&snapshot.careAdviceRequested&&CareCatalog.careIntent(text)&&
   !PlannerPlanNormalizer.listeningOnly(text)&&plan.operations.length===0)plan.decision='explain';
  plan.shortMessage=PlannerPlanNormalizer.display(plan.shortMessage,language);
  plan.question=PlannerPlanNormalizer.display(plan.question,language);
  const observations:SelectionObservation[]=plan.selectionObservations||[];
  const clear=observations.filter((o:SelectionObservation)=>o.confidence==='clear');
  const areas=new Set<string>(clear.map((o:SelectionObservation)=>o.area));
  const area=areas.size===1?Array.from(areas)[0]:'';
  const concern=clear.some((o:SelectionObservation)=>o.concern==='blemish')?'blemish':'';
  const previousProducts:string[]=(snapshot.productContextIds||[])
   .concat((snapshot.dialogue||[]).flatMap((turn)=>turn.productIds||[]));
  const explicitProduct=/olay|玉兰油|产品|推荐|眼霜|面霜|精华|怎么用|用法|ingredients|recommend|product/i.test(text);
  let declined=CareCatalog.productsDeclined(text)||CareCatalog.careFeedback(text)||
   (!!snapshot.dismissedProducts&&!explicitProduct);
  if(observations.length&&clear.length===0)declined=true;
  const alternative=/换|其他|别款|推荐|哪款|alternative|recommend/i.test(text);
  const lookedUp=await ProductCatalog.lookup(context,text,snapshot.productContextIds||[]);
  const newlyNamed=lookedUp.some((p)=>!previousProducts.includes(p.productId));
  const offer=!declined&&(previousProducts.length===0||alternative||newlyNamed);
  if(!offer)plan.careGuide=null;
  // Care questions still receive a source-linked routine when a colour edit
  // cannot honestly represent a product outcome.
  if(offer&&snapshot.careAdviceRequested&&CareCatalog.careIntent(text)&&
   !PlannerPlanNormalizer.listeningOnly(text)&&(plan.decision==='explain'||plan.decision==='clarify')&&!plan.careGuide){
   const options=await CareCatalog.careOptions(context,text,true,catalogLanguage,area,concern);
   if(options.length){
    const option=options[0];
    const guide:CloudCareGuide={productId:option.productId,
     whyHere:CareCatalog.careReason(option.category,catalogLanguage,text+(concern==='blemish'?' 痘':'')),
     howToUse:option.ordinaryUse};
    plan.careGuide=guide;
   }
  }
  if(plan.careGuide){
   await OlayResearchData.ready(context);
   const record=OlayResearchData.researchRecords().find((p)=>p.product_id===plan.careGuide?.productId);
   if(record){
    // Wording comes from reviewed category guidance, never the model's own claims.
    plan.careGuide.whyHere=CareCatalog.careReason(record.category_id,catalogLanguage,text+(concern==='blemish'?' 痘':''));
    plan.careGuide.howToUse=CareCatalog.routine(record.category_id,catalogLanguage);
   }
   if((plan.decision==='explain'||plan.decision==='clarify')&&
    /做不到|不能.*(?:做|改)|工具.*(?:不行|不支持)/.test(plan.shortMessage))
    plan.shortMessage=language==='zh'?'先把这处的日常护理放轻一些，下面是可以直接做的一步。'
     :'Begin with a gentle routine for this area; the care card below gives one practical step.';
  }
  if(PlannerPlanNormalizer.listeningOnly(text)&&
   /我(?:会|已经)?记(?:着|住)|已(?:经)?(?:保存|保护)|以后(?:一直|都会)/.test(plan.shortMessage)){
   // No preference-write tool exists here; keep the acknowledgement truthful.
   plan.shortMessage='这次先保留你现在的样子，我们慢慢聊。';
  }
  if(plan.decision==='clarify'&&plan.question){
   // The dedicated question renders once beside the choices.
   const statement=plan.shortMessage.replace(/[^。！？.!?]*[？?]/g,'').trim();
   if(statement)plan.shortMessage=statement;
  }
  if(plan.choices)plan.choices=plan.choices.map((choice:string)=>PlannerPlanNormalizer.display(choice,language));
 }
}
