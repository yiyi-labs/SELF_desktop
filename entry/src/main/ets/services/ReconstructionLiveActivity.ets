import { liveViewManager } from '@kit.LiveViewKit';
import { wantAgent } from '@kit.AbilityKit';
import { BusinessError, deviceInfo } from '@kit.BasicServicesKit';
import { UiText } from './UiText';

export interface ReconstructionActivityState {
  active:boolean;name:string;progress:number;message:string;language:string;
}

/** Local Huawei Live View. Process-independent updates require the server Push Kit channel. */
export class ReconstructionLiveActivity {
  private static instance:ReconstructionLiveActivity=new ReconstructionLiveActivity();
  static shared():ReconstructionLiveActivity{return ReconstructionLiveActivity.instance;}
  private state:ReconstructionActivityState={active:false,name:'',progress:0,message:'',language:'zh'};
  private foreground:boolean=true;
  private started:boolean=false;
  private running:boolean=false;
  private dirty:boolean=false;
  private blocked:boolean=false;
  private timer:number=-1;
  private lastUpdate:number=0;
  private readonly id:number=23001;
  setForeground(value:boolean):void{this.foreground=value;this.blocked=false;this.queue();}
  sync(state:ReconstructionActivityState):void{this.state=state;this.queue();}
  dispose():void{this.state.active=false;this.queue();}
  private queue():void{
    this.dirty=true;
    if(this.running)return;
    if(this.timer>=0){clearTimeout(this.timer);this.timer=-1;}
    const delay=this.foreground||!this.state.active?0:Math.max(0,1200-(Date.now()-this.lastUpdate));
    this.timer=setTimeout(()=>{this.timer=-1;this.flush();},delay);
  }
  private async build(state:ReconstructionActivityState,ended:boolean=false):Promise<liveViewManager.LiveView>{
    const clickAction=await wantAgent.getWantAgent({wants:[{bundleName:'com.self.mirror',abilityName:'EntryAbility',
      parameters:{reconstructionWaiting:true}}],actionType:wantAgent.OperationType.START_ABILITY,
      requestCode:this.id,actionFlags:[wantAgent.WantAgentFlags.UPDATE_PRESENT_FLAG]});
    const progress=Math.max(0,Math.min(99,Math.round(state.progress)));
    const lang=state.language;
    const tr=(zh:string,en:string):string=>lang==='en'?en:UiText.get(zh,lang);
    const view:liveViewManager.LiveView={id:this.id,event:'PROGRESS',isMute:true,liveViewData:{
      primary:{title:tr('星辰构建中','Building your star'),
        content:[{text:state.name?state.name.slice(0,24):tr('寻找你的模样','Finding your portrait')},
          {text:state.message?UiText.get(state.message,lang):tr('正在寻找你的模样','Finding your portrait')}],clickAction,keepTime:0,
        extensionData:{type:liveViewManager.ExtensionType.EXTENSION_TYPE_PROGRESS,progress},
        layoutData:{layoutType:liveViewManager.LayoutType.LAYOUT_TYPE_PROGRESS,progress,
          color:'#FFBEDCF4',backgroundColor:'#FF263A54',
          nodeIcons:['reconstruction-star.png','reconstruction-star.png']}},
      capsule:{type:liveViewManager.CapsuleType.CAPSULE_TYPE_TEXT,status:ended?-1:1,
        icon:'reconstruction-star.png',backgroundColor:'#FF20314B',
        title:tr('构建中','Building'),content:progress+'%',isContentDisplayed:true}
    }};
    if(deviceInfo.sdkApiVersion>=26)view.lifeCycleMode=liveViewManager.LifeCycleMode.AUTO_STOP_WHEN_APP_TERMINATE;
    return view;
  }
  private async flush():Promise<void>{
    if(this.running)return;
    this.running=true;this.dirty=false;
    const snapshot=this.state;
    try{
      if(this.foreground||!snapshot.active){
        if(!this.started){try{await liveViewManager.getActiveLiveView(this.id);this.started=true;}catch(_){}}
        if(this.started){
          const result=await liveViewManager.stopLiveView(await this.build(snapshot,true));this.started=false;
          console.info('SELF_LIVE_VIEW_STOP '+result.resultCode);
          AppStorage.setOrCreate('selfLiveViewStatus','idle');
        }
      }else if(!this.blocked){
        if(!this.started){
          if(!await liveViewManager.isLiveViewEnabled()){
            this.blocked=true;AppStorage.setOrCreate('selfLiveViewStatus','disabled');return;
          }
          try{await liveViewManager.getActiveLiveView(this.id);this.started=true;}catch(_){}
        }
        const view=await this.build(snapshot);
        if(this.foreground||!this.state.active){this.dirty=true;return;}
        const result=this.started?await liveViewManager.updateLiveView(view):await liveViewManager.startLiveView(view);
        this.started=true;this.lastUpdate=Date.now();
        AppStorage.setOrCreate('selfLiveViewStatus',result.resultCode===0?'active':'partial');
        console.info('SELF_LIVE_VIEW_RESULT '+result.resultCode);
      }
    }catch(error){
      const code=(error as BusinessError).code;
      this.blocked=true;
      AppStorage.setOrCreate('selfLiveViewStatus',code===1003500005?'rights-required':'unavailable');
      console.warn('SELF_LIVE_VIEW_UNAVAILABLE '+code+' '+(error as BusinessError).message);
    }finally{this.running=false;if(this.dirty)this.queue();}
  }
}
