import { common } from '@kit.AbilityKit';
import { OlayResearchData,CatalogRecord } from './OlayResearchData';
import { ProductKnowledge,ProductDetail } from './ProductKnowledge';

interface ScoredRecord{record:CatalogRecord;score:number;}
/**
 * Reviewed mainland-channel lookup on the phone, equivalent to product_catalog.py:
 * keyword-scored matches only, never a silent promotion of whichever record is first.
 */
export class ProductCatalog {
 private static readonly CONTINUATION_WORDS:string[]=['这款','这个','它','试一下','试试','淡一点','参数','效果','怎么用','用法','成分','还有','为什么','this','it','use'];
 private static readonly EXPLICIT_WORDS:string[]=['olay','玉兰油','产品','护肤','小白瓶','超红瓶','黑管'];
 private static readonly BRAND_WORDS:string[]=['olay','玉兰油','小白瓶','超红瓶','黑管'];
 static async lookup(context:common.UIAbilityContext,userText:string,contextIds:string[]):Promise<ProductDetail[]>{
  await OlayResearchData.ready(context);
  const exact=await ProductKnowledge.exactIdentities(context,userText);
  if(exact.length)return exact;
  const value=userText.toLowerCase();
  const continuation=['1','2','3'].includes(value.trim())||ProductCatalog.CONTINUATION_WORDS.some((w:string)=>value.includes(w));
  const explicit=ProductCatalog.EXPLICIT_WORDS.some((w:string)=>value.includes(w));
  if(!explicit&&!(continuation&&contextIds.length>0))return[];
  if(continuation&&contextIds.length>0&&!explicit){
   const joined=await ProductKnowledge.contextualProducts(context,contextIds);
   if(joined.length)return joined;
  }
  const records=OlayResearchData.catalogRecords();
  const scored=records.map((p:CatalogRecord):ScoredRecord=>
   {return{record:p,score:p.keywords.filter((k:string)=>value.includes(k.toLowerCase())).length};});
  scored.sort((a,b)=>b.score-a.score);
  let matches=scored.filter((entry)=>entry.score>0);
  if(!matches.length&&continuation&&contextIds.length>0&&!explicit)
   matches=scored.filter((entry)=>contextIds.includes(entry.record.productId));
  const details:ProductDetail[]=[];
  for(const entry of matches.slice(0,3)){
   const direct=await ProductKnowledge.productDetail(context,entry.record.productId);
   details.push(direct??ProductCatalog.channelDetail(entry.record));
  }
  return details;
 }
 private static channelDetail(p:CatalogRecord):ProductDetail{
  return{productId:p.productId,name:p.name,category:'channel-information',market:p.market,
   specification:p.specification,usageSummary:p.usageSummary,source:p.source,retrievedAt:p.retrievedAt,
   evidenceType:p.evidenceType,recordKind:p.recordKind,availability:p.availability,inci:p.inci,
   formulaRevision:p.formulaRevision,physicalParameters:p.physicalParameters,efficacyCalibration:p.efficacyCalibration,
   canRenderProductEffect:false,facts:[],claims:[],ingredientHighlights:[],offers:[],sourceLinks:[],fieldCoverage:[]};
 }
 static async allowedRefs(context:common.UIAbilityContext,userText:string,contextIds:string[]):Promise<Set<string>>{
  const matches=await ProductCatalog.lookup(context,userText,contextIds);
  return new Set<string>(matches.map((p:ProductDetail)=>p.productId));
 }
 /** True when the utterance asks for a product's real effect, which no calibrated profile can authorise. */
 static async requestsProductEffect(context:common.UIAbilityContext,userText:string,contextIds:string[]):Promise<boolean>{
  const value=userText.toLowerCase();
  const separateCare=value.includes('通用数字试色')&&
   /(?:顺便|另外|同时|独立).{0,24}(?:olay|玉兰油).{0,16}(?:护理|养护|使用建议)/.test(value)&&
   !/(?:用|靠|按).{0,10}(?:olay|玉兰油).{0,16}(?:达到|做出|涂成|变成|还原)/.test(value);
  if(separateCare)return false;
  if(ProductCatalog.BRAND_WORDS.some((w:string)=>value.includes(w)))return true;
  if(value.includes('通用数字试色')&&/(?:不是|非|不按|不根据).{0,8}(?:产品|护肤)/.test(value))return false;
  if(value.includes('产品')||value.includes('护肤'))return true;
  return(await ProductCatalog.lookup(context,userText,contextIds)).length>0;
 }
}
