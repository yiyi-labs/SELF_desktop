import { fileIo as fs } from '@kit.CoreFileKit';
import { SelfViewerState, PackageValidationError, validViewer } from './SelfTransferContract';
import { boundedText } from './TransferFiles';

export const FRONT_ENTRY:string='viewer/front_view.json';
export const ARRIVAL_ENTRY:string='viewer/arrival_view.json';
export const CAMERA_FEATURE:string='viewer.camera-pair.v1';
export const PORTRAIT_CONFIG:string='source-first-v2-level-face-only-20261006';
export interface HeadHalf {x:number;u:number;f:number;}
export interface TransferPortrait {
  version:number;resolverVersion:number;verified:boolean;configHash:string;modelTransformHash:string;
  renderContractId:string;assetHash:string;sourceKind:string;framingSource:string;
  pivot:number[];front:number[];up:number[];headHalf:HeadHalf;
  fitDistance:number;fitFovY:number;fitAspect:number;sceneR:number;pitchLimited?:boolean;confidence?:string;attemptVersion?:string;
}
export interface TransferFrontView {schema:string;version:number;plySha256:string;portraitView:TransferPortrait;}
export function validPortrait(p:TransferPortrait,hash:string):boolean {
  const vector=(v:number[]):boolean=>Array.isArray(v)&&v.length===3&&v.every((n:number)=>Number.isFinite(n)&&Math.abs(n)<1e9);
  if(!p||p.version!==2||p.resolverVersion!==2||
    !(p.verified===true||p.verified===false&&p.pitchLimited===true&&p.confidence==='visible-face-pitch-limited'&&p.attemptVersion==='source-reference-r4-pitch-fallback-20261006')||p.assetHash!==hash||
    p.configHash!==PORTRAIT_CONFIG||p.modelTransformHash!=='identity-ply-v1'||
    typeof p.renderContractId!=='string'||!p.renderContractId||p.renderContractId.length>160||
    !vector(p.pivot)||!vector(p.front)||!vector(p.up)||!p.headHalf)return false;
  const fl=Math.hypot(...p.front),ul=Math.hypot(...p.up);
  if(fl<1e-9||ul<1e-9||Math.abs(p.front.reduce((sum:number,n:number,i:number)=>sum+n*p.up[i],0))/(fl*ul)>.1)return false;
  return [p.headHalf.x,p.headHalf.u,p.headHalf.f,p.fitDistance,p.fitAspect,p.sceneR].every((n:number)=>Number.isFinite(n)&&n>1e-7&&n<1e9)&&
    Number.isFinite(p.fitFovY)&&p.fitFovY>=10&&p.fitFovY<=90;
}
/** Whitelist geometry only: source image references, paths and analysis inputs never travel. */
export function portablePortrait(p:TransferPortrait):TransferPortrait {
  return {version:2,resolverVersion:2,verified:p.verified===true,pitchLimited:p.verified===false,confidence:p.verified===false?'visible-face-pitch-limited':'verified',
    attemptVersion:p.verified===false?p.attemptVersion:'',configHash:p.configHash,modelTransformHash:p.modelTransformHash,
    renderContractId:p.renderContractId,assetHash:p.assetHash,sourceKind:'self-transfer',framingSource:p.framingSource==='face-only'?'face-only':'head',
    pivot:p.pivot.slice(),front:p.front.map((n:number)=>n/Math.hypot(...p.front)),up:p.up.map((n:number)=>n/Math.hypot(...p.up)),headHalf:{x:p.headHalf.x,u:p.headHalf.u,f:p.headHalf.f},
    fitDistance:p.fitDistance,fitFovY:p.fitFovY,fitAspect:p.fitAspect,sceneR:p.sceneR};
}
export function exportFrontView(directory:string,hash:string):TransferFrontView|undefined {
  const view=JSON.parse(boundedText(directory+'/portrait.view.json')) as Record<string,Object>;
  let portrait=view['portraitView'] as TransferPortrait|undefined;
  const sidecar=directory+'/portrait.profile.json';
  if((!portrait||portrait.verified!==true)&&fs.accessSync(sidecar))portrait=(JSON.parse(boundedText(sidecar)) as Record<string,Object>)['portraitView'] as TransferPortrait;
  if(!portrait||portrait.verified!==true){
    const fallbackPath=directory+'/portrait.fallback.json';
    const fallback=fs.accessSync(fallbackPath)?JSON.parse(boundedText(fallbackPath)) as TransferPortrait:view['portraitFallback'] as TransferPortrait|undefined;
    if(fallback)portrait=fallback;
    else return undefined; // Legacy unverified profiles are not recorded front views.
  }
  if(!validPortrait(portrait,hash))throw new PackageValidationError('正脸记录与模型不匹配，请重新打开模型后发送');
  return {schema:'self.transfer.front-view',version:1,plySha256:hash,portraitView:portablePortrait(portrait)};
}
export function validateFrontView(view:TransferFrontView,hash:string):TransferFrontView {
  if(!view||view.schema!=='self.transfer.front-view'||view.version!==1||view.plySha256!==hash||!validPortrait(view.portraitView,hash))
    throw new PackageValidationError('模型包正脸视角损坏或不匹配');
  return {schema:view.schema,version:1,plySha256:hash,portraitView:portablePortrait(view.portraitView)};
}
export function cameraFileRevision(directory:string):string {
  return ['portrait.view.json','portrait.profile.json','portrait.fallback.json'].map((name:string)=>{
    const path=directory+'/'+name;if(!fs.accessSync(path))return name+':none';
    const stat=fs.statSync(path);return name+':'+stat.size+':'+stat.mtime;
  }).join('|');
}
export interface CameraReadDiagnostic {encoding:string;resultBytes:number;valid:boolean;}
let cameraRead:CameraReadDiagnostic={encoding:'not-read',resultBytes:0,valid:false};
export function cameraReadDiagnostic():CameraReadDiagnostic{return cameraRead;}
/** ArkWeb serializes string return values as JSON strings; also support an object result. */
export function parseWebCameraResult(text:string):SelfViewerState {
  cameraRead={encoding:'invalid',resultBytes:typeof text==='string'?text.length:0,valid:false};
  if(typeof text!=='string'||!text||text.length>32768)throw new PackageValidationError('当前视角读取失败，请重新碰一碰');
  let value=JSON.parse(text) as Object;
  const stringResult=typeof value==='string';
  cameraRead.encoding=stringResult?'json-string':'json-object';
  if(stringResult)value=JSON.parse(value as string) as Object;
  const view=value as SelfViewerState;
  if(!validViewer(view))throw new PackageValidationError('当前视角尚未绘制完成，请稍后碰一碰');
  cameraRead.valid=true;return view;
}
/** Process-local only: an arrival view is consumed once and never overwrites the saved front view. */
export class SelfTransferCameraSession {
  private static providers:Map<string,()=>Promise<SelfViewerState>>=new Map<string,()=>Promise<SelfViewerState>>();
  private static arrivals:Map<string,SelfViewerState>=new Map<string,SelfViewerState>();
  static register(modelId:string,provider:()=>Promise<SelfViewerState>):void{SelfTransferCameraSession.providers.set(modelId,provider);}
  static unregister(modelId:string,provider:()=>Promise<SelfViewerState>):void{if(SelfTransferCameraSession.providers.get(modelId)===provider)SelfTransferCameraSession.providers.delete(modelId);}
  static async capture(modelId:string):Promise<SelfViewerState>{
    const provider=SelfTransferCameraSession.providers.get(modelId);if(!provider)throw new PackageValidationError('当前视角尚未就绪，请等模型显示后重试');
    const view=await provider();
    if(SelfTransferCameraSession.providers.get(modelId)!==provider||!validViewer(view))throw new PackageValidationError('模型页面已改变，请重新碰一碰');
    return view;
  }
  static arrive(modelId:string,view:SelfViewerState|undefined):void{SelfTransferCameraSession.arrivals.clear();if(view)SelfTransferCameraSession.arrivals.set(modelId,view);}
  static take(modelId:string):SelfViewerState|undefined{const view=SelfTransferCameraSession.arrivals.get(modelId);SelfTransferCameraSession.arrivals.delete(modelId);return view;}
}

