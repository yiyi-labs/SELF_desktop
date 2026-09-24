import { media } from '@kit.MediaKit';
import { common } from '@kit.AbilityKit';
export class AmbientAudio {
  private context:common.UIAbilityContext;
  private player:media.AVPlayer|undefined=undefined;
  private rawPath:string='';
  private wanted:boolean=false;
  private foreground:boolean=true;
  private mode:string='quiet';
  private token:number=0;
  private queue:Promise<void>=Promise.resolve();
  onStatus:(state:string)=>void=()=>{};
  onPulse:(level:number)=>void=()=>{};
  constructor(context:common.UIAbilityContext){this.context=context;}
  configure(enabled:boolean,mode:string):void{
    const next=['quiet','warm','clear'].includes(mode)?mode:'quiet';if(this.wanted===enabled&&this.mode===next)return;
    this.wanted=enabled;this.mode=next;this.schedule();
  }
  visibility(foreground:boolean):void{this.foreground=foreground;this.schedule();}
  private schedule():void{
    const token=++this.token;
    this.queue=this.queue.then(async()=>{if(token!==this.token)return;await this.releasePlayer();if(token!==this.token)return;if(!this.wanted||!this.foreground){this.onStatus(this.wanted?'paused':'off');return;}await this.start(token);}).catch((e:Error)=>{if(token===this.token)this.error(e);});
  }
  private async start(token:number):Promise<void>{
    this.onStatus('loading');const player=await media.createAVPlayer();
    if(token!==this.token){await player.release();return;}this.player=player;
    const rawPath='audio/'+this.mode+'.wav';this.rawPath=rawPath;
    player.on('stateChange',(state:string)=>{
      if(token!==this.token)return;
      if(state==='initialized')player.prepare().catch((e:Error)=>{if(token===this.token)this.error(e);});
      if(state==='prepared'){
        player.loop=true;player.setVolume(.28);player.play().catch((e:Error)=>{if(token===this.token)this.error(e);});
      }
      if(state==='playing'){this.onStatus('playing');console.info('SELF_AUDIO_PLAYING '+this.mode);}
    });
    let reported=false,lastPulse=-1;
    player.on('timeUpdate',(time:number)=>{
      if(token!==this.token)return;
      if(!reported&&time>=1000){reported=true;console.info('SELF_AUDIO_PROGRESS '+this.mode+' '+time);}
      // The original soundtrack has one soft bell every four seconds. Follow its playback clock.
      const slot=Math.floor(time/220);
      if(slot!==lastPulse){lastPulse=slot;const beat=(time/1000)%4;this.onPulse(Math.min(1,Math.exp(-beat*.85)*(.35+.65*Math.min(1,beat*3))));}
    });
    player.on('error',(e)=>{if(token===this.token)this.error(e);});
    const fd=await this.context.resourceManager.getRawFd(rawPath);if(token!==this.token)return;player.fdSrc={fd:fd.fd,offset:fd.offset,length:fd.length};
  }
  private error(error:Error):void{this.wanted=false;++this.token;this.onStatus('error');console.error('SELF_AUDIO_ERROR '+error.message);this.queue=this.queue.then(()=>this.releasePlayer());}
  private async releasePlayer():Promise<void>{
    const player=this.player;this.player=undefined;
    if(player){try{if(player.state==='playing'){player.setVolume(.12);await new Promise<void>(r=>setTimeout(r,80));player.setVolume(0);}await player.release();}catch(e){console.warn('SELF_AUDIO_RELEASE '+String(e));}}
    if(this.rawPath){const path=this.rawPath;this.rawPath='';try{await this.context.resourceManager.closeRawFd(path);}catch(e){}}
  }
  dispose():void{this.wanted=false;this.schedule();}
}
