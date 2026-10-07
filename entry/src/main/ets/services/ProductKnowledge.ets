import { common } from '@kit.AbilityKit';
import { OlayResearchData,ResearchRecord,DossierRecord } from './OlayResearchData';

export interface IdentityIndexItem{productId:string;name:string;category:string;family:string;status:string;source:string;recommendable:boolean;}
export interface KeyedRecord{record:ResearchRecord;key:string;}
export interface ProductDetail{
 productId:string;name:string;category:string;market:string;specification:string;usageSummary:string;
 source:string;retrievedAt:string;evidenceType:string;recordKind:string;availability:string;
 inci:string|null;formulaRevision:string|null;physicalParameters:string|null;efficacyCalibration:string|null;
 canRenderProductEffect:boolean;facts:object[];claims:object[];ingredientHighlights:object[];
 offers:object[];sourceLinks:object[];fieldCoverage:object[];
}
/**
 * One identity/dossier join on the phone, mirroring the audited product_knowledge.py behaviour.
 * All 74 identities stay searchable; historical/search-only ones stay labelled and recommendable=false.
 */
export class ProductKnowledge {
 static normalize(value:string):string{return value.toLowerCase().replace(/[\p{P}\p{S}\s_]+/gu,'');}
 static async identityIndex(context:common.UIAbilityContext):Promise<IdentityIndexItem[]>{
  await OlayResearchData.ready(context);
  return OlayResearchData.researchRecords().map((p:ResearchRecord):IdentityIndexItem=>{
   return{productId:p.product_id,name:p.marketing_name,category:p.category_id,family:p.family,
    status:p.record_status,source:p.primary_url,
    recommendable:p.record_status==='brand_2026_observed'||p.record_status==='catalog_only'};});
 }
 static async productDetail(context:common.UIAbilityContext,productId:string):Promise<ProductDetail|undefined>{
  await OlayResearchData.ready(context);
  const p=OlayResearchData.researchRecords().find((r:ResearchRecord)=>r.product_id===productId);
  if(!p)return undefined;
  await OlayResearchData.dossiersReady(context);
  const found=OlayResearchData.dossier(productId);
  const fallback:DossierRecord={dossier_id:productId,facts:[],claims:[],ingredient_highlights:[],offers:[],source_links:[],field_coverage:[]};
  const d:DossierRecord=found??fallback;
  return{productId:p.product_id,name:p.marketing_name,category:p.category_id,
   market:'CN-mainland',specification:'具体规格以实物包装为准',
   usageSummary:'有来源的产品身份与品类资料；具体用法以实物包装为准',
   source:p.primary_url,retrievedAt:p.checked_on,evidenceType:p.record_status,recordKind:'research-identity',
   availability:'not-verified',inci:p.full_inci??null,formulaRevision:p.formula_version_id??null,
   physicalParameters:null,efficacyCalibration:null,canRenderProductEffect:false,
   facts:d.facts,claims:d.claims,ingredientHighlights:d.ingredient_highlights,
   offers:d.offers,sourceLinks:d.source_links,fieldCoverage:d.field_coverage};
 }
 /** Marketing names of length>=4 whose normalised form appears inside the normalised user text; longest first, max 3. */
 static async exactIdentities(context:common.UIAbilityContext,text:string):Promise<ProductDetail[]>{
  await OlayResearchData.ready(context);
  const query=ProductKnowledge.normalize(text);
  if(query.length<4)return[];
  const matched=OlayResearchData.researchRecords()
   .map((p:ResearchRecord):KeyedRecord=>{return{record:p,key:ProductKnowledge.normalize(p.marketing_name)};})
   .filter((entry:KeyedRecord)=>entry.key.length>=4&&query.includes(entry.key));
  matched.sort((a,b)=>b.key.length-a.key.length);
  const details:ProductDetail[]=[];
  for(const entry of matched.slice(0,3)){
   const detail=await ProductKnowledge.productDetail(context,entry.record.product_id);
   if(detail)details.push(detail);
  }
  return details;
 }
 static async contextualProducts(context:common.UIAbilityContext,ids:string[]):Promise<ProductDetail[]>{
  await OlayResearchData.ready(context);
  const details:ProductDetail[]=[];
  for(const id of ids){
   if(details.length>=3)break;
   const detail=await ProductKnowledge.productDetail(context,id);
   if(detail)details.push(detail);
  }
  return details;
 }
}
