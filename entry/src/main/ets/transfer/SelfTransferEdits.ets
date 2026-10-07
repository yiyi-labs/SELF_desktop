import { fileIo as fs } from '@kit.CoreFileKit';
import { util } from '@kit.ArkTS';
import { PackageValidationError } from './SelfTransferContract';
import { boundedText } from './TransferFiles';

export const EDIT_ENTRY:string='extensions/saved_edits.json';
export const EDIT_FEATURE:string='viewer.edits.v1';
export interface SavedLayer {layerId:string;regionId:string;preset:string;strength:number;maskChecksum:string;maskBase64:string;}
export interface SavedGroup {groupId:string;label:string;createdAt:number;layers:SavedLayer[];}
export interface LocalSavedEdits {schemaVersion:number;assetId:string;assetBytes:number;splatCount:number;groups:SavedGroup[];}
export interface TransferEdits {schema:string;version:number;plySha256:string;assetBytes:number;splatCount:number;groups:SavedGroup[];}
interface LegacyEdit {schemaVersion:number;assetId:string;assetBytes:number;splatCount:number;maskChecksum:string;preset:string;strength:number;}

function checksum(bytes:Uint8Array):string {
  let value=2166136261;
  for(let i=0;i<bytes.length;i++)value=Math.imul(value^bytes[i],16777619)>>>0;
  return value.toString(16);
}
function fail():never {throw new PackageValidationError('保存的试色记录不完整或与模型不一致');}
function text(value:string,limit:number):boolean{return typeof value==='string'&&value.length>0&&value.length<=limit&&!/[\u0000-\u001f\u007f]/.test(value);}

/** Both viewers use the same persisted SET_HISTORY layers. Copy only reloadable appearance, never planner/account data. */
export function validateEdits(value:TransferEdits,bytes:number,sha256:string,points:number):TransferEdits {
  if(!value||value.schema!=='self.transfer.edits'||value.version!==1||value.plySha256!==sha256||
    value.assetBytes!==bytes||value.splatCount!==points||!Array.isArray(value.groups)||value.groups.length>12)fail();
  const groups:SavedGroup[]=[],ids:Set<string>=new Set<string>();let total=0;
  const decoder=new util.Base64Helper();
  for(const group of value.groups){
    if(!group||!text(group.groupId,80)||ids.has(group.groupId)||!text(group.label,100)||
      !Number.isFinite(group.createdAt)||group.createdAt<0||!Array.isArray(group.layers)||group.layers.length<1||group.layers.length>4)fail();
    ids.add(group.groupId);const layers:SavedLayer[]=[];
    for(const layer of group.layers){
      if(!layer||!text(layer.layerId,100)||!text(layer.regionId,100)||!['rose','terracotta'].includes(layer.preset)||
        ![.18,.32,.5].includes(layer.strength)||typeof layer.maskBase64!=='string'||
        layer.maskBase64.length!==4*Math.ceil(points/3)||! /^[A-Za-z0-9+/]*={0,2}$/.test(layer.maskBase64)||
        typeof layer.maskChecksum!=='string')fail();
      let mask:Uint8Array;
      try{mask=decoder.decodeSync(layer.maskBase64);}catch(_){fail();}
      if(mask.length!==points||checksum(mask)!==layer.maskChecksum)fail();
      layers.push({layerId:layer.layerId,regionId:layer.regionId,preset:layer.preset,strength:layer.strength,
        maskChecksum:layer.maskChecksum,maskBase64:layer.maskBase64});
    }
    total+=layers.length;if(total>16)fail();
    groups.push({groupId:group.groupId,label:group.label,createdAt:group.createdAt,layers});
  }
  return {schema:'self.transfer.edits',version:1,plySha256:sha256,assetBytes:bytes,splatCount:points,groups};
}
export function savedEditRevision(directory:string):string {
  return ['portrait.edit.v2.json','portrait.edit.json','portrait.edit.mask'].map((name:string)=>{
    const path=directory+'/'+name;if(!fs.accessSync(path))return '';
    const stat=fs.statSync(path);return name+':'+stat.size+':'+stat.mtime;
  }).join('|');
}
export function exportSavedEdits(directory:string,modelId:string,bytes:number,sha256:string,points:number):TransferEdits|undefined {
  let local:LocalSavedEdits;
  if(fs.accessSync(directory+'/portrait.edit.v2.json')){
    local=JSON.parse(boundedText(directory+'/portrait.edit.v2.json',4*1024*1024)) as LocalSavedEdits;
    if(!local||local.schemaVersion!==2||local.assetId!==modelId||local.assetBytes!==bytes||!Array.isArray(local.groups))fail();
    if(local.groups.length===0)return undefined;
  }else if(fs.accessSync(directory+'/portrait.edit.json')){
    const legacy=JSON.parse(boundedText(directory+'/portrait.edit.json')) as LegacyEdit;
    const maskPath=directory+'/portrait.edit.mask';
    if(!legacy||legacy.schemaVersion!==1||legacy.assetId!==modelId||legacy.assetBytes!==bytes||legacy.splatCount!==points||
      !fs.accessSync(maskPath)||fs.statSync(maskPath).size!==points||points>3*1024*1024)fail();
    const file=fs.openSync(maskPath,fs.OpenMode.READ_ONLY),buffer=new ArrayBuffer(points);
    try{if(fs.readSync(file.fd,buffer)!==points)fail();}finally{fs.closeSync(file);}
    const layer:SavedLayer={layerId:'legacy-1',regionId:'gs-selected-1',preset:legacy.preset,strength:legacy.strength,
      maskChecksum:legacy.maskChecksum,maskBase64:new util.Base64Helper().encodeToStringSync(new Uint8Array(buffer))};
    local={schemaVersion:2,assetId:modelId,assetBytes:bytes,splatCount:points,
      groups:[{groupId:'legacy',label:'原有试色',createdAt:0,layers:[layer]}]};
  }else return undefined;
  const portable:TransferEdits={schema:'self.transfer.edits',version:1,plySha256:sha256,assetBytes:bytes,splatCount:local.splatCount,groups:local.groups};
  return validateEdits(portable,bytes,sha256,points);
}
