import { common, Want } from '@kit.AbilityKit';
import { fileIo as fs, picker } from '@kit.CoreFileKit';
import { deviceInfo } from '@kit.BasicServicesKit';
import { HarmonyShareBridge } from './HarmonyShareBridge';
import { SelfTransferPackage } from './SelfTransferPackage';
import { TransferCoordinator } from './TransferCoordinator';
import { TransferSurface } from './TransferState';
import { removeTransferTree } from './TransferFiles';

/** A window-scoped facade; Ability and pages reuse the same instance. */
export class SelfTransferRuntime {
  private static windows:Map<number,SelfTransferRuntime>=new Map<number,SelfTransferRuntime>();
  readonly coordinator:TransferCoordinator;
  private bridge:HarmonyShareBridge;
  private packages:SelfTransferPackage;
  private pendingWant:Want|undefined=undefined;
  private surface:TransferSurface={kind:'NONE',modelId:'',revision:''};
  private foreground:boolean=false;
  private handling:boolean=false;
  private disposed:boolean=false;
  static bind(context:common.UIAbilityContext,windowId:number):SelfTransferRuntime{
    const existing=SelfTransferRuntime.windows.get(windowId);if(existing)return existing;
    const runtime=new SelfTransferRuntime(context,windowId);SelfTransferRuntime.windows.set(windowId,runtime);return runtime;
  }
  private context:common.UIAbilityContext;
  private windowId:number;
  private constructor(context:common.UIAbilityContext,windowId:number){
    this.context=context;this.windowId=windowId;
    this.packages=new SelfTransferPackage(context);this.bridge=new HarmonyShareBridge(this.packages.root,windowId);
    this.coordinator=new TransferCoordinator(this.bridge,this.packages);
  }
  supported():boolean{return this.bridge.supported();}
  setForeground(value:boolean):void{this.foreground=value;this.coordinator.setForeground(value);this.processWant();}
  setSurface(surface:TransferSurface):void{this.surface=surface;this.coordinator.setSurface(surface);this.processWant();}
  handleWant(want:Want):void{
    if(want.action!=='ohos.want.action.sendData'&&want.action!=='ohos.want.action.viewData')return;
    this.pendingWant=want;this.processWant();
  }
  private processWant():void{
    if(!this.pendingWant||!this.foreground||this.surface.kind==='NONE'||this.handling||this.disposed)return;
    const want=this.pendingWant;this.pendingWant=undefined;
    if(this.surface.kind==='BUSY'){this.context.getApplicationContext().eventHub.emit('selfTransferNotice','当前任务进行中，请回到主页后重新打开模型包');return;}
    if(!this.coordinator.reserveManualReceive()){this.context.getApplicationContext().eventHub.emit('selfTransferNotice','当前正在交接模型，请完成后重新打开');return;}
    this.handling=true;
    this.bridge.copyWant(want).then((path:string)=>this.coordinator.importFile(path,true).finally(()=>this.cleanupIncoming(path)))
      .catch((error:Error)=>{console.error('SELF_SHARE_WANT '+error.name+' '+error.message);this.context.getApplicationContext().eventHub.emit('selfTransferNotice',error.message);})
      .finally(()=>{this.coordinator.releaseManualReceive();this.handling=false;this.processWant();});
  }
  async pickPackage():Promise<void>{
    if(deviceInfo.sdkApiVersion<20||this.surface.kind==='BUSY'||this.handling||this.disposed)return;
    this.handling=true;
    let reserved=false;
    try{
      const selected=await new picker.DocumentViewPicker(this.context).select({maxSelectNumber:1,fileSuffixFilters:['SELF 模型包|.zip']});
      if(selected.length!==1)return;
      reserved=this.coordinator.reserveManualReceive();
      if(!reserved){this.context.getApplicationContext().eventHub.emit('selfTransferNotice','当前正在交接模型或页面已离开，请稍后重试');return;}
      const path=await this.bridge.copyExternalUri(selected[0]);
      try{await this.coordinator.importFile(path,true);}finally{this.cleanupIncoming(path);}
    }catch(error){console.error('SELF_SHARE_PICKER '+String(error));this.context.getApplicationContext().eventHub.emit('selfTransferNotice',(error as Error).message);}
    finally{if(reserved)this.coordinator.releaseManualReceive();this.handling=false;this.processWant();}
  }
  private cleanupIncoming(path:string):void{
    const session=path.substring(0,path.lastIndexOf('/'));
    if(session.substring(0,session.lastIndexOf('/'))===this.packages.root+'/incoming'&&fs.accessSync(session))removeTransferTree(session,this.packages.root);
  }
  dispose():void{this.disposed=true;this.pendingWant=undefined;this.coordinator.dispose();SelfTransferRuntime.windows.delete(this.windowId);}
}
