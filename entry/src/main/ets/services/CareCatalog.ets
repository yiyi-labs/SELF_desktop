import { common } from '@kit.AbilityKit';
import { OlayResearchData,ResearchRecord } from './OlayResearchData';
import { ProductKnowledge } from './ProductKnowledge';

export interface CareOption{productId:string;name:string;category:string;source:string;ordinaryUse:string;}
interface RankedId{id:string;rank:number;}
/**
 * Source-linked care choices, equivalent to care_catalog.py: a routine step is never
 * a calibrated appearance effect, and wording comes only from these reviewed lines.
 */
export class CareCatalog {
 private static readonly ROUTINES_ZH:Record<string,string>={
  'cream':'清洁后轻轻铺开；具体用量和使用频率看实物包装。',
  'serum':'清洁后按实物包装说明使用，之后可按习惯叠加面霜。',
  'eye':'在眼周轻轻点开，避开眼内；具体用量看实物包装。',
  'sunscreen':'日间按实物包装说明均匀涂抹，户外留意补涂。',
  'cleanser':'清洁时轻柔带过，随后充分冲净。',
  'toner':'清洁后轻轻涂开，具体用法和频率看实物包装。',
  'emulsion':'清洁后轻轻铺开，具体用量和顺序看实物包装。',
  'mask':'按实物包装说明使用，留意使用时长与是否需要冲洗。',
  'set':'按套装内各单品的实物说明分别使用，不把套装视为单一配方。',
  'body_lotion':'在身体皮肤上轻轻涂开，具体用量看实物包装。',
  'body_scrub':'仅按实物包装说明用于身体，避免用在眼周或已破损的皮肤上。',
  'body_cleanser':'按实物包装说明清洁身体，随后充分冲净。',
  'body_tint':'按实物包装说明用于身体，先在小范围查看色彩。'};
 private static readonly ROUTINES_EN:Record<string,string>={
  'cream':'Smooth on gently after cleansing; follow the package for amount and frequency.',
  'serum':'Use after cleansing as directed on the package, then add cream if that suits your routine.',
  'eye':'Pat gently around the eyes, avoiding the eyes themselves; follow the package for amount.',
  'sunscreen':'Apply evenly by day as directed on the package and reapply outdoors.',
  'cleanser':'Cleanse gently, then rinse thoroughly.',
  'toner':'Apply gently after cleansing; follow the package for method and frequency.',
  'emulsion':'Smooth on gently after cleansing; follow the package for amount and order.',
  'mask':'Follow the package for duration and whether to rinse off.',
  'set':'Follow each item’s own instructions; a set is not a single formula.',
  'body_lotion':'Smooth onto body skin as directed on the package.',
  'body_scrub':'Use on the body as directed; avoid the eye area and broken skin.',
  'body_cleanser':'Cleanse the body as directed, then rinse thoroughly.',
  'body_tint':'Use on the body as directed; check the colour on a small area first.'};
 private static readonly SKIN_CONCERNS:string[]=['痘','痘印','疤','泛红','敏感','干燥','粗糙','暗沉','acne','pimple','blemish','scar','redness'];
 /** Reviewed catalog wording exists in zh/en; ja/ko presentations read the English source. */
 static catalogLanguage(language:string):string{return language==='zh'||language==='en'?language:'en';}
 static careIntent(text:string):boolean{
  const value=text.toLowerCase();
  const words:string[]=['保养','养护','护理','怎么用','如何用','护肤','眼霜','olay','玉兰油','care','routine','保湿','防晒','洁面','洗脸','清洁'];
  return words.some((w:string)=>value.includes(w))||CareCatalog.SKIN_CONCERNS.some((w:string)=>value.includes(w));
 }
 static productsDeclined(text:string):boolean{
  return /(?:不要|不用|不想|别|不买).{0,8}(?:推荐|产品|商品|买|olay|玉兰油)|no products|no recommendations|don.t recommend/i.test(text);
 }
 static careFeedback(text:string):boolean{
  return /刺痛|过敏|不舒服|太贵|已经有|已有|买过|sting|irritat|already (?:have|use)|too expensive/i.test(text);
 }
 static routine(category:string,language:string):string{
  return CareCatalog.catalogLanguage(language)==='en'?(CareCatalog.ROUTINES_EN[category]||''):(CareCatalog.ROUTINES_ZH[category]||'');
 }
 static async careOptions(context:common.UIAbilityContext,text:string,enabled:boolean,language:string,area:string='',concern:string=''):Promise<CareOption[]>{
  await OlayResearchData.ready(context);
  if(!enabled||CareCatalog.productsDeclined(text)||CareCatalog.careFeedback(text))return[];
  const value=text.toLowerCase();
  if(area==='eye'&&concern==='blemish')return[];
  // The reviewed face-care entries are not lip or eye makeup colours.
  const makeupWords:string[]=['唇','口红','唇色','lip','眼影','眼线','睫毛','眉'];
  if(makeupWords.some((w:string)=>value.includes(w)))return[];
  if(['1','2','3','试一下','试试','这个','这款','它'].includes(value.trim()))return[];
  const faceWords:string[]=['脸','面部','皮肤','肤','额头','鼻','眼','保养','保湿','护肤','护理','养护','olay','玉兰油','face','cheek','skin','forehead','nose','care','moistur'];
  if(!area&&(await ProductKnowledge.exactIdentities(context,text)).length===0&&
   !faceWords.some((w:string)=>value.includes(w))&&!CareCatalog.SKIN_CONCERNS.some((w:string)=>value.includes(w)))return[];
  const blemish=value.includes('痘')||value.includes('acne')||value.includes('pimple')||value.includes('blemish')||concern==='blemish';
  let categories:Set<string>;
  if(blemish){
   // A cleanser is a routine step, never a claimed acne treatment.
   categories=new Set<string>(['cleanser','cream']);
  }else if(value.includes('防晒')||value.includes('紫外线')||value.includes('sun')){
   categories=new Set<string>(['sunscreen']);
  }else if(value.includes('眼')||value.includes('eye')||area==='eye'){
   categories=new Set<string>(['eye']);
  }else if(value.includes('洁面')||value.includes('洗脸')||value.includes('清洁')||value.includes('cleanse')){
   categories=new Set<string>(['cleanser']);
  }else if(area==='body'||value.includes('身体')||value.includes('身体乳')||value.includes('沐浴')||value.includes('body')){
   categories=new Set<string>(['body_lotion','body_cleanser','body_scrub','body_tint']);
  }else if(area==='lips'||area==='brow'){
   return[];
  }else{
   // Before vision analysis, every facial category is available, including eyes.
   categories=new Set<string>(['cream','serum','toner','emulsion','mask','sunscreen','cleanser']);
   if(!area||area==='unknown')categories.add('eye');
  }
  const exact=new Set<string>((await ProductKnowledge.exactIdentities(context,text)).map((p)=>p.productId));
  let ids=OlayResearchData.researchRecords()
   .filter((p:ResearchRecord)=>(p.record_status==='brand_2026_observed'||p.record_status==='catalog_only')&&
    categories.has(p.category_id)&&(exact.size===0||exact.has(p.product_id)))
   .map((p:ResearchRecord)=>p.product_id);
  if(blemish)ids=ids
   .map((id:string):RankedId=>{return{id,rank:OlayResearchData.researchRecords().find((p:ResearchRecord)=>p.product_id===id)?.category_id==='cleanser'?0:1};})
   .sort((a,b)=>a.rank-b.rank).map((entry:RankedId)=>entry.id);
  const options:CareOption[]=[];
  for(const id of ids){
   const p=OlayResearchData.researchRecords().find((r:ResearchRecord)=>r.product_id===id);
   if(!p)continue;
   options.push({productId:p.product_id,name:p.marketing_name,category:p.category_id,
    source:p.primary_url,ordinaryUse:CareCatalog.routine(p.category_id,language)});
  }
  return options;
 }
 static async allowedCareIds(context:common.UIAbilityContext,text:string,enabled:boolean,area:string='',concern:string=''):Promise<Set<string>>{
  const options=await CareCatalog.careOptions(context,text,enabled,CareCatalog.catalogLanguage('zh'),area,concern);
  return new Set<string>(options.map((o:CareOption)=>o.productId));
 }
 static careUsage(context:common.UIAbilityContext,productCategory:string,language:string):string{
  return CareCatalog.routine(productCategory,language);
 }
 static careReason(productCategory:string,language:string,requestText:string):string{
  const value=requestText.toLowerCase();
  if(['痘','acne','pimple','blemish'].some((w:string)=>value.includes(w))){
   if(productCategory==='cream')return language==='en'?'A gentle moisturizing step is daily care, not an acne treatment.':'轻轻做日常保湿，不揉搓这处；面霜不是祛痘治疗。';
   return language==='en'?'Start with a gentle cleansing step; this cleanser is not an acne treatment.':'先轻柔清洁这处，不揉搓；洁面不是祛痘治疗。';
  }
  if(language==='en'){
   const en:Record<string,string>={'eye':'Give the eye area a gentle place in your daily routine.',
    'sunscreen':'Daytime care can include a simple sun-protection step.',
    'cleanser':'A gentle cleanse can be one small part of your daily routine.'};
   return en[productCategory]||'Make room for a calm daily-care step and notice how your skin feels.';
  }
  const zh:Record<string,string>={'eye':'眼周也可以有轻柔的日常节奏，留意自己喜欢的舒适感。',
   'sunscreen':'白天可以把防晒放进日常节奏里，慢慢找到适合自己的方式。',
   'cleanser':'清洁这一步放轻一些，留意自己喜欢的肤感。'};
  return zh[productCategory]||'这处也可以有自己的日常护理节奏，留意自己喜欢的肤感。';
 }
}
