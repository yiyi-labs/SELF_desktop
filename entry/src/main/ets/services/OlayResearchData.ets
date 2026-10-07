import { common } from '@kit.AbilityKit';
import { util } from '@kit.ArkTS';

/** Snapshot of the audited shared/product datasets, loaded from rawfile on first AI use and cached. */
export interface ResearchRecord{
 product_id:string;marketing_name:string;category_id:string;family:string;record_status:string;
 primary_url:string;checked_on:string;full_inci?:string|null;formula_version_id?:string|null;
}
export interface DossierRecord{
 dossier_id:string;facts:object[];claims:object[];ingredient_highlights:object[];offers:object[];
 source_links:object[];field_coverage:object[];
}
export interface CatalogRecord{
 productId:string;name:string;market:string;specification:string;usageSummary:string;source:string;
 retrievedAt:string;evidenceType:string;recordKind:string;availability:string;inci:string|null;
 formulaRevision:string|null;physicalParameters:string|null;efficacyCalibration:string|null;keywords:string[];
}
/**
 * The 754KB dossier file is only parsed when a specific product is actually matched,
 * keeping ordinary requests to the two small files and the context minimal.
 */
export class OlayResearchData {
 private static records:ResearchRecord[]=[];
 private static catalog:CatalogRecord[]=[];
 private static dossiers:Map<string,DossierRecord>|undefined=undefined;
 private static readyPromise:Promise<void>|undefined=undefined;
 private static dossierPromise:Promise<void>|undefined=undefined;
 static ready(context:common.UIAbilityContext):Promise<void>{
  if(!OlayResearchData.readyPromise){
   OlayResearchData.readyPromise=new Promise<void>((resolve,reject)=>{
    try{
     const decoder=new util.TextDecoder('utf-8');
     const productBytes=context.resourceManager.getRawFileContentSync('products/research/products_cn.json');
     OlayResearchData.records=JSON.parse(decoder.decodeWithStream(productBytes,{stream:false})) as ResearchRecord[];
     const catalogBytes=context.resourceManager.getRawFileContentSync('products/research/olay-cn-catalog.json');
     OlayResearchData.catalog=(JSON.parse(decoder.decodeWithStream(catalogBytes,{stream:false})) as CatalogSource).records;
     resolve();
    }catch(e){OlayResearchData.readyPromise=undefined;reject(new Error('product data unavailable'));}});
  }
  return OlayResearchData.readyPromise;
 }
 static dossiersReady(context:common.UIAbilityContext):Promise<void>{
  if(!OlayResearchData.dossierPromise){
   OlayResearchData.dossierPromise=new Promise<void>((resolve,reject)=>{
    try{
     const decoder=new util.TextDecoder('utf-8');
     const bytes=context.resourceManager.getRawFileContentSync('products/research/product_dossiers_cn.json');
     const parsed=JSON.parse(decoder.decodeWithStream(bytes,{stream:false})) as DossierRecord[];
     const map=new Map<string,DossierRecord>();
     for(const item of parsed)map.set(item.dossier_id,item);
     OlayResearchData.dossiers=map;resolve();
    }catch(e){OlayResearchData.dossierPromise=undefined;reject(new Error('dossier data unavailable'));}});
  }
  return OlayResearchData.dossierPromise;
 }
 static researchRecords():ResearchRecord[]{return OlayResearchData.records;}
 static catalogRecords():CatalogRecord[]{return OlayResearchData.catalog;}
 static dossier(id:string):DossierRecord|undefined{return OlayResearchData.dossiers?.get(id);}
}
interface CatalogSource{records:CatalogRecord[];}
