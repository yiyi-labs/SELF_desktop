import { PreparedTransfer, ImportedTransfer } from './SelfTransferContract';
import { TransferIntent, TransferPolicy, TransferPhase, TransferSurface, TransferSnapshot,
  TransferTransport, TransferModels, TransferDiagnostic, surfaceIntent } from './TransferState';

/** One instance per real window. The coordinator alone owns transport listener transitions. */
export class TransferCoordinator {
  onChanged:(snapshot:TransferSnapshot)=>void=()=>{};
  onImported:(model:ImportedTransfer)=>void=()=>{};
  private surface:TransferSurface={kind:'NONE',modelId:'',revision:''};
  private foreground:boolean=false;
  private policy:TransferPolicy=TransferPolicy.AUTO;
  private phase:TransferPhase=TransferPhase.IDLE;
  private intent:TransferIntent=TransferIntent.NONE;
  private generation:number=0;
  private operationGeneration:number=0;
  private active:boolean=false;
  private disposed:boolean=false;
  private lastMessage:string='';
  private prepared:PreparedTransfer|undefined=undefined;
  private preparingKey:string='';
  private transport:TransferTransport;
  private models:TransferModels;
  constructor(transport:TransferTransport,models:TransferModels){this.transport=transport;this.models=models;}
  setForeground(value:boolean):void{
    if(this.foreground===value)return;
    this.foreground=value;
    if(!value){this.generation++;this.transport.clear();this.preparingKey='';this.phase=TransferPhase.IDLE;this.intent=TransferIntent.NONE;this.emit('');}
    else this.reconcile();
  }
  setSurface(surface:TransferSurface):void{
    if(this.disposed)return;
    const changed=this.surface.kind!==surface.kind||this.surface.modelId!==surface.modelId||this.surface.revision!==surface.revision;
    if(!changed)return;
    if(this.surface.kind!==surface.kind||this.surface.modelId!==surface.modelId)this.policy=TransferPolicy.AUTO;
    this.surface=surface;this.generation++;this.preparingKey='';this.transport.clear();this.intent=TransferIntent.NONE;
    if(!this.active)this.phase=TransferPhase.IDLE;
    this.reconcile();
  }
  forceReceive(enabled:boolean):void{
    if(this.active||this.surface.kind!=='VIEWER')return;
    this.policy=enabled?TransferPolicy.FORCE_RECEIVE:TransferPolicy.AUTO;
    this.generation++;this.preparingKey='';this.transport.clear();this.intent=TransferIntent.NONE;this.phase=TransferPhase.IDLE;this.reconcile();
  }
  diagnostic():TransferDiagnostic{return {intent:this.intent,phase:this.phase,policy:this.policy,message:this.lastMessage,
    foreground:this.foreground,surface:this.surface.kind,modelSelected:!!this.surface.modelId,active:this.active,prepared:!!this.prepared};}
  private emit(message:string):void{this.lastMessage=message;this.onChanged({intent:this.intent,phase:this.phase,policy:this.policy,message});}
  private fail(error:Error):void{
    this.transport.clear();this.phase=TransferPhase.ERROR;this.intent=TransferIntent.NONE;
    console.error('SELF_TRANSFER_'+error.name+' '+error.message);this.emit(error.message);
  }
  private begin(expected:TransferIntent,retainSystemListener:boolean=false):boolean{
    if(this.active||this.disposed||!this.foreground||surfaceIntent(this.surface,this.policy,true)!==expected||
      (expected===TransferIntent.SEND?this.phase!==TransferPhase.SEND_READY:this.phase!==TransferPhase.RECEIVE_READY))return false;
    this.operationGeneration=this.generation;
    // The system needs its registered sandbox receiver until receive() completes.
    // active rejects duplicate callbacks; manual imports still detach the system listener.
    this.active=true;if(!retainSystemListener)this.transport.clear();this.phase=TransferPhase.TRANSFERRING;
    this.emit(this.intent===TransferIntent.SEND?'正在交给系统发送…':'正在接收模型…');return true;
  }
  private reconcile():void{
    if(this.disposed||this.active||!this.transport.supported())return;
    const desired=surfaceIntent(this.surface,this.policy,this.foreground);
    if(desired===TransferIntent.NONE){this.transport.clear();this.intent=desired;this.phase=TransferPhase.IDLE;this.emit('');return;}
    if(desired===this.intent&&(this.phase===TransferPhase.SEND_READY||this.phase===TransferPhase.RECEIVE_READY))return;
    this.transport.clear();this.intent=desired;
    if(desired===TransferIntent.RECEIVE){
      try{
        this.transport.listenReceive(()=>this.begin(TransferIntent.RECEIVE,true),(path:string)=>{this.importFile(path,true);},(error:Error)=>{this.active=false;this.fail(error);this.reconcile();});
        this.phase=TransferPhase.RECEIVE_READY;
        this.emit(this.transport.automaticReceive()?'可碰一碰接收 SELF 模型':'碰一碰收到文件后，选择用 SELF 打开');
      }catch(error){this.fail(error as Error);}return;
    }
    const key=this.surface.modelId+':'+this.surface.revision;
    if(this.preparingKey===key)return;
    this.preparingKey=key;this.phase=TransferPhase.PREPARING_SEND;this.emit('正在准备当前模型…');
    const generation=this.generation;
    this.models.prepare(this.surface.modelId,this.surface.revision).then((prepared:PreparedTransfer)=>{
      if(this.disposed||generation!==this.generation||!this.foreground||this.active)return;
      this.prepared=prepared;this.preparingKey='';
      this.transport.listenSend(prepared,()=>this.begin(TransferIntent.SEND,true),()=>{
        this.transport.clear();
        this.active=false;this.phase=TransferPhase.IDLE;this.intent=TransferIntent.NONE;
        // share() resolves without a delivery receipt. The OS reports the actual transfer result.
        console.info('SELF_SHARE_SUBMITTED '+prepared.packageId);this.reconcile();this.emit('已交给系统发送，请查看系统传输结果');
      },(error:Error)=>{this.active=false;this.fail(error);this.reconcile();});
      this.phase=TransferPhase.SEND_READY;this.emit('碰一碰发送当前模型');
    }).catch((error:Error)=>{if(generation===this.generation&&!this.disposed){this.preparingKey='';this.fail(error);}});
  }
  async importFile(path:string,transportStarted:boolean=false):Promise<void>{
    if(!transportStarted&&!this.begin(TransferIntent.RECEIVE))return;
    this.transport.clear();
    // A cancelled/background transfer may finish at the system level; do not publish it into the repository.
    const generation=this.operationGeneration;
    this.phase=TransferPhase.IMPORTING;this.emit('正在校验并导入模型…');
    try{
      const model=await this.models.importPackage(path,()=>this.disposed||!this.foreground||generation!==this.generation);
      this.active=false;this.policy=TransferPolicy.AUTO;this.phase=TransferPhase.IDLE;this.intent=TransferIntent.NONE;
      console.info('SELF_MODEL_IMPORTED '+model.modelId+' '+model.sha256);
      this.onImported(model);this.reconcile();this.emit(model.duplicate?'这个模型已经接收过':'模型已接收');
    }catch(error){this.active=false;if(!this.disposed&&this.foreground)this.fail(error as Error);else this.reconcile();}
  }
  receiveManually(path:string):Promise<void>{
    if(!this.reserveManualReceive())return Promise.resolve();
    return this.importFile(path,true);
  }
  reserveManualReceive():boolean{
    if(this.active||this.disposed)return false;
    if(this.surface.kind==='VIEWER')this.forceReceive(true);
    if(surfaceIntent(this.surface,this.policy,this.foreground)!==TransferIntent.RECEIVE){
      this.emit('当前任务进行中，请回到主页后再导入');return false;
    }
    return this.begin(TransferIntent.RECEIVE);
  }
  releaseManualReceive():void{
    this.active=false;this.policy=TransferPolicy.AUTO;this.phase=TransferPhase.IDLE;this.intent=TransferIntent.NONE;this.reconcile();
  }
  retry():void{if(!this.active){this.generation++;this.preparingKey='';this.phase=TransferPhase.IDLE;this.intent=TransferIntent.NONE;this.reconcile();}}
  dispose():void{this.disposed=true;this.foreground=false;this.generation++;this.transport.clear();this.prepared=undefined;this.onChanged=()=>{};this.onImported=()=>{};}
}
