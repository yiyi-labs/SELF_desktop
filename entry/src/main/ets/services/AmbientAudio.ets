import { media } from '@kit.MediaKit';
import { common } from '@kit.AbilityKit';
const MOODS:string[]=['quiet','warm','clear'];
const SCENES:string[]=['origin','capture','forming','sky','travel','personal','care'];
function sceneVolume(key:string):number{
  switch(key){
    case 'capture':return .24;
    case 'forming':return .28;
    case 'sky':return .30;
    case 'travel':return .34;
    case 'personal':return .28;
    case 'care':return .26;
    default:return .28;
  }
}
export class AmbientAudio {
  private context:common.UIAbilityContext;
  private player:media.AVPlayer|undefined=undefined;
  private rawPath:string='';
  private wanted:boolean=false;
  private foreground:boolean=true;
  private mood:string='quiet';
  private scene:string='origin';
  private token:number=0;
  private queue:Promise<void>=Promise.resolve();
  onStatus:(state:string)=>void=()=>{};
  onPulse:(level:number)=>void=()=>{};
  constructor(context:common.UIAbilityContext){this.context=context;}
  configure(enabled:boolean,mode:string):void{
    const next=MOODS.includes(mode)?mode:'quiet';if(this.wanted===enabled&&this.mood===next)return;
    this.wanted=enabled;this.mood=next;this.schedule();
  }
  // Interface changes retarget the soundtrack; the chosen atmosphere still owns the mirror home.
  setScene(scene:string):void{
    const next=SCENES.includes(scene)?scene:'origin';if(this.scene===next)return;
    this.scene=next;this.schedule();
  }
  private track():string{return this.scene==='origin'?this.mood:'scene-'+this.scene;}
  visibility(foreground:boolean):void{this.foreground=foreground;this.schedule();}
  private schedule():void{
    const token=++this.token;
    this.queue=this.queue.then(async()=>{if(token!==this.token)return;
      if(this.wanted&&this.foreground&&this.player&&this.rawPath==='audio/'+this.track()+'.wav')return;
      await this.releasePlayer();if(token!==this.token)return;
      if(!this.wanted||!this.foreground){this.onStatus(this.wanted?'paused':'off');return;}
      await this.start(token);}).catch((e:Error)=>{if(token===this.token)this.error(e);});
  }
  private async start(token:number):Promise<void>{
    this.onStatus('loading');const player=await media.createAVPlayer();
    if(token!==this.token){await player.release();return;}this.player=player;
    const track=this.track(),rawPath='audio/'+track+'.wav';this.rawPath=rawPath;
    const target=sceneVolume(this.scene==='origin'?this.mood:this.scene);
    player.on('stateChange',(state:string)=>{
      if(token!==this.token)return;
      if(state==='initialized')player.prepare().catch((e:Error)=>{if(token===this.token)this.error(e);});
      if(state==='prepared'){player.loop=true;player.setVolume(0);player.play().catch((e:Error)=>{if(token===this.token)this.error(e);});}
      if(state==='playing'){this.onStatus('playing');console.info('SELF_AUDIO_PLAYING '+track);this.fadeIn(player,token,target);}
    });
    let reported=false,lastPulse=-1;
    player.on('timeUpdate',(time:number)=>{
      if(token!==this.token)return;
      if(!reported&&time>=1000){reported=true;console.info('SELF_AUDIO_PROGRESS '+track+' '+time);}
      // Every scene loop keeps one soft bell every four seconds. Follow its playback clock.
      const slot=Math.floor(time/220);
      if(slot!==lastPulse){lastPulse=slot;const beat=(time/1000)%4;this.onPulse(Math.min(1,Math.exp(-beat*.85)*(.35+.65*Math.min(1,beat*3))));}
    });
    player.on('error',(e)=>{if(token===this.token)this.error(e);});
    const fd=await this.context.resourceManager.getRawFd(rawPath);if(token!==this.token)return;player.fdSrc={fd:fd.fd,offset:fd.offset,length:fd.length};
  }
  private fadeIn(player:media.AVPlayer,token:number,target:number):void{
    const steps:number[]=[.05,.11,.17,.22,target];let i=0;
    const tick=():void=>{if(token!==this.token||this.player!==player||player.state!=='playing')return;if(i>=steps.length)return;player.setVolume(steps[i]);i++;setTimeout(tick,120);};
    setTimeout(tick,60);
  }
  private error(error:Error):void{this.wanted=false;++this.token;this.onStatus('error');console.error('SELF_AUDIO_ERROR '+error.message);this.queue=this.queue.then(()=>this.releasePlayer());}
  private async releasePlayer():Promise<void>{
    const player=this.player;this.player=undefined;
    if(player){try{if(player.state==='playing'){player.setVolume(.10);await new Promise<void>(r=>setTimeout(r,110));player.setVolume(.04);await new Promise<void>(r=>setTimeout(r,90));player.setVolume(0);}await player.release();}catch(e){console.warn('SELF_AUDIO_RELEASE '+String(e));}}
    if(this.rawPath){const path=this.rawPath;this.rawPath='';try{await this.context.resourceManager.closeRawFd(path);}catch(e){}}
  }
  dispose():void{this.wanted=false;this.schedule();}
}
