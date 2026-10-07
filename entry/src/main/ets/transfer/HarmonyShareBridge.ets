import { harmonyShare, systemShare } from '@kit.ShareKit';
import { Want } from '@kit.AbilityKit';
import { deviceInfo, BusinessError } from '@kit.BasicServicesKit';
import { fileIo as fs, fileUri } from '@kit.CoreFileKit';
import { uniformTypeDescriptor as utd } from '@kit.ArkData';
import { util } from '@kit.ArkTS';
import { PreparedTransfer, ShareTransportError } from './SelfTransferContract';
import { TransferTransport } from './TransferState';
import { makeDir, ensureSpace, removeTransferTree } from './TransferFiles';
import { savedEditRevision } from './SelfTransferEdits';

export interface ShareDiagnostic {api:number;deviceType:string;supported:boolean;automaticReceive:boolean;windowId:number;
  sendRegistered:boolean;receiveRegistered:boolean;knockCallbacks:number;receiveCallbacks:number;lastSendError?:string;}

/** Sole Share Kit boundary. Signatures audited against the installed API 26 SDK and Huawei's current guide. */
export class HarmonyShareBridge implements TransferTransport {
  private sendCapability:harmonyShare.SendCapabilityRegistry;
  private receiveCapability:harmonyShare.RecvCapabilityRegistry;
  private sendRegistered:boolean=false;
  private receiveRegistered:boolean=false;
  private knockCallbacks:number=0;
  private receiveCallbacks:number=0;
  private lastSendError:string='';
  private prepared:PreparedTransfer|undefined=undefined;
  private sendBegin:()=>boolean=()=>false;
  private sendSubmitted:()=>void=()=>{};
  private sendFailure:(error:Error)=>void=()=>{};
  private receiveBegin:()=>boolean=()=>false;
  private receivedFile:(path:string)=>void=()=>{};
  private receiveFailure:(error:Error)=>void=()=>{};
  private root:string;
  constructor(root:string,windowId:number){
    this.root=root;
    this.sendCapability={windowId,sendOnly:true};
    this.receiveCapability={windowId,capabilities:[{utd:'general.file',maxSupportedCount:1}]};
  }
  prepareSend:((prepared:PreparedTransfer)=>Promise<PreparedTransfer>)|undefined=undefined;
  supported():boolean{return deviceInfo.sdkApiVersion>=20&&canIUse('SystemCapability.Collaboration.HarmonyShare');}
  diagnostic():ShareDiagnostic{return {api:deviceInfo.sdkApiVersion,deviceType:deviceInfo.deviceType,supported:this.supported(),
    automaticReceive:this.automaticReceive(),windowId:this.sendCapability.windowId,sendRegistered:this.sendRegistered,
    receiveRegistered:this.receiveRegistered,knockCallbacks:this.knockCallbacks,receiveCallbacks:this.receiveCallbacks,lastSendError:this.lastSendError};}
  automaticReceive():boolean{
    // This checks official API availability, NEVER the user's SEND/RECEIVE intent.
    return this.supported()&&(deviceInfo.deviceType==='2in1'||deviceInfo.deviceType==='tablet'&&deviceInfo.sdkApiVersion>=23);
  }
  clear():void{
    if(deviceInfo.sdkApiVersion<20)return;
    if(this.sendRegistered){
      try{harmonyShare.off('knockShare',this.sendCapability,this.onKnockShare);this.sendRegistered=false;}
      catch(error){console.error('SELF_SHARE_UNREGISTER_SEND '+String(error));}
    }
    if(this.receiveRegistered){
      try{harmonyShare.off('dataReceive',this.receiveCapability,this.onDataReceive);this.receiveRegistered=false;}
      catch(error){console.error('SELF_SHARE_UNREGISTER_RECEIVE '+String(error));}
    }
    this.prepared=undefined;
  }
  listenSend(prepared:PreparedTransfer,onBegin:()=>boolean,onSubmitted:()=>void,onError:(error:Error)=>void):void{
    this.clear();if(!this.supported())return;
    if(this.sendRegistered||this.receiveRegistered)throw new ShareTransportError('系统分享暂时无法切换，请重新打开此页面');
    this.prepared=prepared;this.sendBegin=onBegin;this.sendSubmitted=onSubmitted;this.sendFailure=onError;
    if(deviceInfo.sdkApiVersion>=20){harmonyShare.on('knockShare',this.sendCapability,this.onKnockShare);this.sendRegistered=true;
      console.info('SELF_SHARE_SEND_REGISTERED windowId='+this.sendCapability.windowId);}
  }
  listenReceive(onBegin:()=>boolean,onFile:(path:string)=>void,onError:(error:Error)=>void):void{
    this.clear();if(!this.supported())return;
    if(this.sendRegistered||this.receiveRegistered)throw new ShareTransportError('系统分享暂时无法切换，请重新打开此页面');
    this.receiveBegin=onBegin;this.receivedFile=onFile;this.receiveFailure=onError;
    if(deviceInfo.sdkApiVersion>=20&&this.automaticReceive()){
      harmonyShare.on('dataReceive',this.receiveCapability,this.onDataReceive);this.receiveRegistered=true;
      console.info('SELF_SHARE_RECEIVE_REGISTERED windowId='+this.receiveCapability.windowId);
    }
  }
  private onKnockShare=(target:harmonyShare.SharableTarget):void=>{
    this.knockCallbacks++;console.info('SELF_SHARE_KNOCK_CALLBACK '+this.knockCallbacks);
    if(deviceInfo.sdkApiVersion<20)return;
    const prepared=this.prepared,onSubmitted=this.sendSubmitted,onError=this.sendFailure;
    if(!prepared||!this.sendRegistered){target.reject(harmonyShare.SharableErrorCode.NO_CONTENT_ERROR).catch(()=>{});return;}
    try{
      const stat=fs.statSync(prepared.sourcePath);
      if(stat.size!==prepared.sourceSize||stat.mtime!==prepared.sourceMtime||!fs.accessSync(prepared.path))
        throw new ShareTransportError('当前模型已改变，请重新打开模型后发送');
      const directory=prepared.sourcePath.substring(0,prepared.sourcePath.lastIndexOf('/'));
      if(savedEditRevision(directory)!==prepared.editsRevision)throw new ShareTransportError('试色记录已改变，请重新打开模型后发送');
      if(!this.sendBegin()){target.reject(harmonyShare.SharableErrorCode.NO_CONTENT_ERROR).catch(()=>{});return;}
      this.lastSendError='';
      const operation=this.prepareSend?this.prepareSend(prepared):Promise.resolve(prepared);
      operation.then((outgoing:PreparedTransfer)=>{
      if(!this.sendRegistered||this.prepared!==prepared)throw new ShareTransportError('模型页面已离开，请重新碰一碰');
      const data=new systemShare.SharedData({utd:'general.file',uri:fileUri.getUriFromPath(outgoing.path),title:outgoing.displayName||'SELF 3D Model',
        description:'SELF local 3D model transfer',extraData:{selfProtocol:'self.transfer.package',protocolVersion:1,packageId:outgoing.packageId,modelKind:'gaussian-splatting'}});
      return target.share(data);
      }).then(()=>onSubmitted()).catch((error:BusinessError)=>{
        target.reject(harmonyShare.SharableErrorCode.NO_CONTENT_ERROR).catch(()=>{});
        this.lastSendError=error.name+': '+error.message;
        console.error('SELF_SHARE_SEND '+error.code+' '+this.lastSendError);
        onError(error.name==='PackageValidationError'?error as Error:new ShareTransportError('系统未能发起发送，请重新碰一碰') as Error);});
    }catch(error){target.reject(harmonyShare.SharableErrorCode.NO_CONTENT_ERROR).catch(()=>{});onError(error as Error);}
  };
  private onDataReceive=(target:harmonyShare.ReceivableTarget):void=>{
    this.receiveCallbacks++;console.info('SELF_SHARE_RECEIVE_CALLBACK '+this.receiveCallbacks);
    if(deviceInfo.sdkApiVersion<20)return;
    const onFile=this.receivedFile,onError=this.receiveFailure;
    if(!this.receiveRegistered||!this.receiveBegin()){
      console.warn('SELF_SHARE_RECEIVE_REJECTED_NOT_READY');
      target.reject(harmonyShare.ReceivableErrorCode.NO_RECEIVABLE_ERROR).catch(()=>{});return;
    }
    const session=this.root+'/incoming/'+util.generateRandomUUID(true);
    try{makeDir(session);}catch(error){
      target.reject(harmonyShare.ReceivableErrorCode.NO_RECEIVABLE_ERROR).catch(()=>{});
      onError(new ShareTransportError('无法创建接收目录，请检查存储空间后重试') as Error);return;
    }
    let terminal=false,success=false,data:systemShare.SharedData|undefined=undefined;
    const fail=(message:string):void=>{
      if(terminal)return;terminal=true;removeTransferTree(session,this.root);onError(new ShareTransportError(message) as Error);
    };
    const complete=():void=>{
      if(terminal||!success||!data)return;
      try{
        // The sandbox callback already represents files matched by the native capability.
        // Its URI can be a local sandbox path and its UTD may be normalized by the OS.
        // Trust neither for publication: require the isolated session and validate ZIP/manifest/SHA below.
        const records=data.getRecords();
        if(records.length!==1||!records[0].uri)throw new ShareTransportError('一次只能接收一个完整 SELF 模型包');
        const uri=records[0].uri as string;
        console.info('SELF_SHARE_SANDBOX_RECORD utd='+records[0].utd+' localPath='+uri.startsWith('/'));
        const path=uri.startsWith('file://')?new fileUri.FileUri(uri).path:uri;
        if(!path.startsWith(session+'/')||path.substring(0,path.lastIndexOf('/'))!==session||fs.lstatSync(path).isSymbolicLink()||!fs.statSync(path).isFile())
          throw new ShareTransportError('系统返回的模型文件不在接收目录');
        terminal=true;console.info('SELF_PACKAGE_RECEIVED '+fs.statSync(path).size);onFile(path);
      }catch(error){fail((error as Error).message);}
    };
    // The system does not expose the total byte length before receipt. Reserve a floor here;
    // extraction is separately budgeted using the inspected archive's actual uncompressed size.
    ensureSpace(session,16*1024*1024).then(()=>{
      if(deviceInfo.sdkApiVersion>=20){
        console.info('SELF_SHARE_SANDBOX_RECEIVE_REQUESTED');
        return target.receive(fileUri.getUriFromPath(session),{
        onDataReceived:(received:systemShare.SharedData)=>{console.info('SELF_SHARE_SANDBOX_DATA');data=received;complete();},
        onResult:(result:harmonyShare.ShareResultCode)=>{
          console.info('SELF_SHARE_SANDBOX_RESULT '+result);
          if(result===harmonyShare.ShareResultCode.SHARE_SUCCESS){success=true;complete();}
          else fail(result===harmonyShare.ShareResultCode.SEND_FAILED?'模型接收失败，请检查存储空间后重试':'接收已取消');
        }
      });}
      return Promise.resolve();
    }).catch((error:Error)=>{
      target.reject(harmonyShare.ReceivableErrorCode.NO_RECEIVABLE_ERROR).catch(()=>{});
      console.error('SELF_SHARE_RECEIVE '+String(error));fail(error.message==='存储空间不足，请清理空间后重试'?error.message:'系统未能接收模型，请重试');
    });
  };
  private singleRecord(data:systemShare.SharedData):systemShare.SharedRecord{
    const records=data.getRecords();if(records.length!==1)throw new ShareTransportError('一次只能接收一个完整 SELF 模型包');
    const record=records[0];
    if(!record.uri||!record.uri.startsWith('file://')||record.utd!=='general.file'&&!utd.getTypeDescriptor(record.utd).belongsTo('general.file'))
      throw new ShareTransportError('收到的数据不是模型文件');return record;
  }
  async copyExternalUri(uri:string):Promise<string>{
    if(!uri.startsWith('file://'))throw new ShareTransportError('请从系统文件管理选择模型包');
    const session=this.root+'/incoming/'+util.generateRandomUUID(true);makeDir(session);
    let file:fs.File|undefined=undefined;
    try{
      file=fs.openSync(uri,fs.OpenMode.READ_ONLY);const stat=fs.statSync(file.fd);
      if(!stat.isFile()||stat.size<=0)throw new ShareTransportError('模型包文件为空或无法读取');
      await ensureSpace(session,stat.size);const local=session+'/received.self3d.zip';
      await fs.copyFile(file.fd,local);console.info('SELF_PACKAGE_RECEIVED '+stat.size);return local;
    }catch(error){removeTransferTree(session,this.root);console.error('SELF_SHARE_EXTERNAL_URI '+String(error));
      if(error instanceof ShareTransportError||error instanceof Error&&error.name==='PackageValidationError')throw error;
      throw new ShareTransportError('无法打开模型文件，请从系统文件管理重新选择');
    }finally{if(file)fs.closeSync(file);}
  }
  async copyWant(want:Want):Promise<string>{
    if(deviceInfo.sdkApiVersion<20)throw new ShareTransportError('此系统版本尚不支持模型交接');
    if(want.action==='ohos.want.action.sendData'){
      const data=await systemShare.getSharedData(want);return this.copyExternalUri(this.singleRecord(data).uri as string);
    }
    if(want.action==='ohos.want.action.viewData'&&want.uri)return this.copyExternalUri(want.uri);
    throw new ShareTransportError('请选择一个 SELF 模型包');
  }
}
