export const SELF_SCHEMA:string = 'self.transfer.package';
export const SELF_PROTOCOL:number = 1;
export const SELF_PLY_CONTRACT:string = 'self.gsplat.f32le.sh0-3.logscale.logit.wxyz.v1';
export const MODEL_ENTRY:string = 'model/model.ply';
export const VIEW_ENTRY:string = 'viewer/viewer_state.json';

export class ShareTransportError extends Error {
  constructor(message:string){super(message);this.name='ShareTransportError';}
}
export class PackageValidationError extends Error {
  constructor(message:string){super(message);this.name='PackageValidationError';}
}
export class ModelImportError extends Error {
  constructor(message:string){super(message);this.name='ModelImportError';}
}
export interface TransferAsset {role:string;path:string;required:boolean;byteLength:number;sha256:string;}
export interface TransferProducer {appFamily:string;variant:string;appVersion:string;bundleName:string;}
export interface TransferModel {kind:string;format:string;formatContract:string;entry:string;byteLength:number;sha256:string;}
export interface SelfTransferManifest {
  schema:string;protocolVersion:number;packageId:string;createdAt:string;producer:TransferProducer;
  model:TransferModel;assets:TransferAsset[];requiredFeatures:string[];optionalFeatures:string[];
  displayName?:string;
}
export interface SelfViewerState {schema:string;version:number;camera:number[];target:number[];up:number[];fovDegrees:number;}
export interface PreparedTransfer {path:string;packageId:string;modelId:string;revision:string;sourcePath:string;sourceSize:number;sourceMtime:number;}
export interface ImportedTransfer {modelId:string;name:string;packageId:string;duplicate:boolean;sha256:string;}
export interface PlyInfo {vertexCount:number;headerBytes:number;stride:number;properties:string[];min:number[];max:number[];}

export function safeEntry(path:string):boolean {
  if(typeof path!=='string'||path.length>512||path.includes('\\')||path.startsWith('/')||path.includes(':'))return false;
  const parts=path.split('/');
  if(parts.some((part:string,index:number)=>part==='.'||part==='..'||(!part&&index!==parts.length-1)||
    (part!==''&&!/^[A-Za-z0-9_.-]+$/.test(part))))return false;
  return path==='manifest.json'||['model/','preview/','viewer/','extensions/'].some((prefix:string)=>path.startsWith(prefix));
}
export function validViewer(view:SelfViewerState):boolean {
  const vector=(value:number[]):boolean=>Array.isArray(value)&&value.length===3&&value.every((n:number)=>typeof n==='number'&&Number.isFinite(n));
  return !!view&&view.schema==='self.transfer.viewer'&&view.version===1&&vector(view.camera)&&vector(view.target)&&vector(view.up)&&
    view.up.some((n:number)=>n!==0)&&view.camera.some((n:number,i:number)=>n!==view.target[i])&&
    typeof view.fovDegrees==='number'&&view.fovDegrees>=10&&view.fovDegrees<=90;
}
export function validateManifest(m:SelfTransferManifest):void {
  if(!m||m.schema!==SELF_SCHEMA)throw new PackageValidationError('这不是 SELF 模型包');
  if(m.protocolVersion!==SELF_PROTOCOL)throw new PackageValidationError('模型包版本不支持，请更新 SELF 后再导入');
  if(typeof m.packageId!=='string'||!/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(m.packageId)||
    typeof m.createdAt!=='string'||!Number.isFinite(Date.parse(m.createdAt)))throw new PackageValidationError('模型包身份信息损坏');
  if(!m.producer||m.producer.appFamily!=='SELF'||typeof m.producer.appVersion!=='string'||typeof m.producer.bundleName!=='string')
    throw new PackageValidationError('模型包来源信息不完整');
  if(!Array.isArray(m.requiredFeatures)||!Array.isArray(m.optionalFeatures)||
    !m.requiredFeatures.includes('model.ply')||m.requiredFeatures.some((name:string)=>name!=='model.ply'))
    throw new PackageValidationError('模型包需要当前 SELF 尚不支持的功能');
  if(!m.model||m.model.kind!=='gaussian-splatting'||m.model.format!=='ply'||m.model.entry!==MODEL_ENTRY||
    m.model.formatContract!==SELF_PLY_CONTRACT)throw new PackageValidationError('当前 SELF 不支持此模型格式');
  if(!Array.isArray(m.assets)||m.assets.length<1||m.assets.length>256)throw new PackageValidationError('模型包资产清单损坏');
  const seen:Set<string>=new Set<string>();
  for(const asset of m.assets){
    if(!asset||!safeEntry(asset.path)||asset.path.endsWith('/')||seen.has(asset.path)||asset.path==='manifest.json'||
      typeof asset.role!=='string'||typeof asset.required!=='boolean'||!Number.isSafeInteger(asset.byteLength)||asset.byteLength<=0||
      typeof asset.sha256!=='string'||!/^[0-9a-f]{64}$/.test(asset.sha256))throw new PackageValidationError('模型包资产信息损坏');
    if(asset.required&&asset.path!==MODEL_ENTRY)throw new PackageValidationError('模型包需要尚不支持的必要资产');
    seen.add(asset.path);
  }
  const model=m.assets.find((asset:TransferAsset)=>asset.path===MODEL_ENTRY);
  if(!model||model.role!=='model'||!model.required||model.byteLength!==m.model.byteLength||model.sha256!==m.model.sha256)
    throw new PackageValidationError('模型文件与清单不一致');
}
