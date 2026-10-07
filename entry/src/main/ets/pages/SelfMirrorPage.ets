import { fileUri, fileIo as fs } from '@kit.CoreFileKit';
import { window } from '@kit.ArkUI';
import { SelfTransferRuntime } from '../transfer/SelfTransferRuntime';
import { TransferSnapshot, TransferPolicy } from '../transfer/TransferState';
import { ImportedTransfer } from '../transfer/SelfTransferContract';
import { NativeMirrorSurface } from './NativeMirrorSurface';
import { GaussianPortraitSurface } from './GaussianPortraitSurface';
import { PersonalPortraitEditor } from './PersonalPortraitEditor';
import { StarCloseButton } from './StarCloseButton';
import { PortraitFindButton } from './PortraitFindButton';
import { GalaxyDeleteRow } from './GalaxyDeleteRow';
import { GalaxyDeleteFlight, GalaxyDeleteFlightRequest } from './GalaxyDeleteFlight';
import { GalaxyUniverseSurface, GalaxyScene } from './GalaxyUniverseSurface';
import { CameraCaptureView } from './CameraCaptureView';
import { NightSkySurface } from './NightSkySurface';
import { ReconstructionProgressCapsule } from './ReconstructionProgressCapsule';
import { ReconstructionLiveActivity } from '../services/ReconstructionLiveActivity';
import { ProductCard } from './ProductCard';
import { OlayLibrary } from './OlayLibrary';
import { OlayDiscoveryRepository, OlayDiscoveryItem } from '../services/OlayDiscoveryRepository';
import { NativeRendererPort } from '../bridge/NativeRendererPort';
import { PlannerClient, CloudResponse, CloudSnapshot, DialogueTurn } from '../services/PlannerClient';
import { common } from '@kit.AbilityKit';
import { Envelope } from '../bridge/RendererBridge';
import { SessionStore } from '../domain/SessionStore';
import { EditOperation, RegionRecord } from '../domain/EditPlan';
import { AssetStore } from '../services/AssetStore';
import { WorkspaceStore, WorkItem } from '../services/WorkspaceStore';
import { PlannerService } from '../services/PlannerService';
import { ProductRepository, ProductRecord } from '../services/ProductRepository';
import { AmbientAudio } from '../services/AmbientAudio';
import { CaptureService,CaptureRecord } from '../services/CaptureService';
import { PortraitStarStore, PortraitStar } from '../services/PortraitStarStore';
import { ReconstructionTransportClient, ReconstructionView } from '../services/ReconstructionTransportClient';
import { UiPreference, UiSettings } from '../services/UiPreference';
import { CloudConsentStore, CloudConsentDecision } from '../services/CloudConsentStore';
import { UiText } from '../services/UiText';
import { AmbiencePreference } from '../services/AmbiencePreference';

interface PendingReconstruction {jobId:string;name?:string;}
interface SavedReconstruction {jobId:string;gaussian?:string;view?:string;mesh?:string;}

@Extend(Button)
function softButton(){
  .height(48).padding({left:8,right:8}).fontSize(15).fontColor('#50445F').backgroundColor('#B8FFFFFF').borderRadius(24).border({width:1,color:'#D6FFFFFF'}).stateStyles({pressed:{.opacity(.72).scale({x:.96,y:.96})},normal:{.opacity(1).scale({x:1,y:1})}}).animation({duration:150,curve:Curve.EaseOut})
}

@Entry
@Component
struct SelfMirrorPage {
  private transferPageActive:boolean=true;
  private transfer:SelfTransferRuntime|undefined=undefined;
  @State transferEnabled:boolean=false;
  @State transferPhase:string='IDLE';
  @State transferReceiving:boolean=false;
  @State @Watch('syncTransferIntent') transferEditorSafe:boolean=true;
  private transferNotice=(message:string):void=>{console.warn('SELF_TRANSFER_NOTICE '+message);};
  private attachTransfer():void{
    this.context.getApplicationContext().eventHub.on('selfTransferNotice',this.transferNotice);
    window.getLastWindow(this.context).then((main:window.Window)=>{
      if(!this.transferPageActive)return;
      this.transfer=SelfTransferRuntime.bind(this.context,main.getWindowProperties().id);
      this.transferEnabled=this.transfer.supported();
      this.transfer.coordinator.onChanged=(state:TransferSnapshot)=>{
        this.transferPhase=state.phase;this.transferReceiving=state.policy===TransferPolicy.FORCE_RECEIVE;
      };
      this.transfer.coordinator.onImported=(model:ImportedTransfer)=>{this.refreshStars();this.close();this.openStar(model.modelId);console.info('SELF_MODEL_OPEN_REQUESTED '+model.modelId);};
      this.transfer.setForeground(this.foreground);this.syncTransferIntent();
    }).catch((error:Error)=>console.error('SELF_TRANSFER_WINDOW '+error.message));
  }
  private syncTransferIntent():void{
    if(!this.transfer)return;
    if(!this.transferPageActive){this.transfer.setSurface({kind:'NONE',modelId:'',revision:''});return;}
    const viewing=this.personalActive()&&!!this.activeStarId;
    const busy=this.cameraLive||this.reconstructionActive||this.reconSubmitting||this.busy||
      this.journey==='forming'||viewing&&(!this.personalReady||!this.transferEditorSafe);
    if(busy){this.transfer.setSurface({kind:'BUSY',modelId:'',revision:''});return;}
    if(viewing){
      try{
        const stat=fs.statSync(this.personalGaussianPath),view=fs.statSync(this.personalViewPath);
        this.transfer.setSurface({kind:'VIEWER',modelId:this.activeStarId,revision:stat.size+':'+stat.mtime+':'+view.mtime});
      }catch(_){this.transfer.setSurface({kind:'NONE',modelId:'',revision:''});}
    }else this.transfer.setSurface({kind:this.skyOpen?'LIST':'HOME',modelId:'',revision:''});
  }
  @State @Watch('replyChanged') subtitle: string = '先陪自己待一会儿。想聊聊，或试一点不同，都听你的。';
  @State windowWidth:number=400;
  @State surfaceWidth:number=400;
  @State surfaceHeight:number=600;
  @State focusX:number=.5;
  @State focusY:number=.5;
  @State focusHalfWidth:number=0;
  @State focusOpen:boolean=false;
  @State captureStatus:string='';
  @State captures:CaptureRecord[]=[];
  @State selectedCapture:string='';
  @State @Watch('syncTransferIntent') cameraLive:boolean=false;
  @State @Watch('syncTransferIntent') personalGaussianPath:string='';
  @State @Watch('syncTransferIntent') personalViewPath:string='';
  @State @Watch('syncTransferIntent') showPersonal:boolean=true;
  @State @Watch('syncTransferIntent') legacyEditorOpen:boolean=false;
  @State @Watch('syncTransferIntent') personalReady:boolean=false;
  @State personalBackdropLight:boolean=false;
  @State @Watch('syncTransferIntent') originMode:boolean=true;
  @State @Watch('syncTransferIntent') skyOpen:boolean=false;
  @State starItems:PortraitStar[]=[];
  @State galaxySceneItems:GalaxyScene[]=[];
  @State previewStarId:string='';
  @State galaxyNavigationSerial:number=0;
  @State previewReady:boolean=false;
  @State galaxyDialOpen:boolean=false;
  @State galaxyDeleteId:string='';
  @State galaxyRenameId:string='';
  @State galaxyRenameDraft:string='';
  @State galaxyDissolvingId:string='';
  @State galaxyFlight:GalaxyDeleteFlightRequest|undefined=undefined;
  @State galaxyRiseIds:string[]=[];
  @State galaxyRiseOffset:number=0;
  private galaxyDeletedIndex:number=-1;
  private galaxyRiseTimer:number=-1;
  @State skyMounted:boolean=false;
  @State skyOpacity:number=0;
  @State skyVeil:number=0;
  @State skyTransition:string='idle';
  @State galaxyTravelId:string='';
  @State galaxyStatus:string='';
  @State galaxyCaption:string='走过的光，还在这里等你。';
  @State galaxyCaptionOpacity:number=1;
  private galaxyCaptionTimer:number=-1;
  private galaxyCaptionGeneration:number=0;
  private galaxyCaptionChangedAt:number=0;
  private skyTimers:number[]=[];
  private skyGeneration:number=0;
  private pendingScenes:Set<string>=new Set<string>();
  @State starNameDraft:string='';
  @State keptStarName:string='';
  @State starNameKept:boolean=false;
  @State starNameEditorPresence:number=1;
  @State starNameLabelPresence:number=0;
  @State starNameError:string='';
  private starNameController:TextInputController=new TextInputController();
  private starNameFocusTimer:number=-1;
  @State @Watch('syncTransferIntent') activeStarId:string='';
  @State @Watch('syncTransferIntent') journey:string='idle';
  @State @Watch('syncReconstructionActivity') reconProgress:number=0;
  @State @Watch('syncTransferIntent') reconstructionActive:boolean=false;
  @State waitingMinimized:boolean=false;
  @State reconstructionOutcome:string='';
  @State reconstructionReadyId:string='';
  @StorageLink('selfReconstructionOpen') @Watch('openReconstructionProgress') reconstructionOpen:number=0;
  @State @Watch('syncTransferIntent') reconSubmitting:boolean=false;
  @State reconCanRetry:boolean=false;
  @State reconCancelling:boolean=false;
  @State formationLine:string='';
  @State formationChars:number=0;
  private pendingCaptureName:string='';
  private uploadingJobId:string='';
  private submissionId:number=0;
  private cancelledSubmissionId:number=-1;
  private formationTimer:number=-1;
  @State introStage:number=0;
  @State introLines:string[]=[];
  @State introRevealed:number[]=[];
  @State introPageOpacity:number=1;
  @State introOverlayOpacity:number=1;
  @State revealOpacity:number=1;
  @State revealScale:number=1;
  @State musicPulse:number=0;
  @State storyLine:number=0;
  @State originScene:number=0;
  @State originVerse:number=0;
  @State visibleCharacters:number=0;
  private originVisits:number[]=[0,0,0,0,0];
  private storyVisits:number[]=[1,0,0];
  private characterTimer:number=-1;
  private storyCueTimer:number=-1;
  private lastInteractionAt:number=Date.now();
  private revealTimer:number=-1;
  @State previewToolsCollapsed:boolean=false;
  @State previewCaptionOpacity:number=0;
  @State previewCaptionY:number=0;
  @State previewCaptionTyped:boolean=false;
  @State previewCaptionSuppressed:boolean=false;
  @State previewCaptionSub:number=0;
  private previewToolsTimer:number=-1;
  private previewFresh:boolean=true;
  private introTimers:number[]=[];
  private introCharacterTimer:number=-1;
  private sparks:number[]=[0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31];
  @State language:string='zh';
  @State langFade:number=1;
  @State accent:string='#7C698F';
  @State anchorX:number=380;
  @State anchorY:number=16;
  private surfaceTop:number=76;
  private readonly detailTop:number=110;
  private tr(value:string):string{return UiText.get(value,this.language);}
  private panelWidth():number{return Math.min(this.surfaceWidth-32,this.detail==='氛围'?360:this.detail==='留一句话'?470:520);}
  private detailParent():string{
    if(this.detail==='云端理解'||this.detail==='采集记录'||this.detail==='作品与记录'||this.detail==='关于 SELF')return '设置';
    if(this.detail==='留一句话')return '作品与记录';
    return '';
  }
  private captureTime(name:string):string{
    const match=name.match(/^capture-(\d+)\.mp4$/);
    if(!match)return name;
    const date=new Date(Number(match[1])),pad=(v:number)=>v<10?'0'+v:String(v);
    return pad(date.getMonth()+1)+'-'+pad(date.getDate())+' '+pad(date.getHours())+':'+pad(date.getMinutes());
  }
  private panelPreferredHeight():number{
    if(this.detail==='氛围')return 552;
    if(this.detail==='设置')return 525;
    if(this.detail==='关于 SELF')return 430;
    if(this.detail==='云端理解')return 420;
    if(this.detail==='留一句话')return 438;
    if(this.detail==='作品与记录')return Math.min(570,310+this.workItems.length*62+this.bill.length*24+(this.note.length>0?90:0));
    return 560;
  }
  private panelHeight():number{
    return Math.max(120,Math.min(this.surfaceHeight-this.progressAwareTop()-20,this.panelPreferredHeight()));
  }
  private panelX():number{return Math.max(16,Math.min(this.surfaceWidth-this.panelWidth()-16,this.anchorX-this.panelWidth()/2));}
  private panelY():number{
    const top=this.progressAwareTop();
    return Math.max(top,Math.min(this.surfaceHeight-this.panelHeight()-20,this.anchorY<top?top:this.anchorY-this.panelHeight()-58));
  }
  private panelFromTop():boolean{return this.anchorY<this.progressAwareTop();}
  private panelDark():boolean{return this.detail==='设置'||this.detail==='关于 SELF'||this.detail==='采集记录'||this.detail==='云端理解';}
  private dustAge:number=0;
  private dustFrac(index:number):number{return (this.panelDust+index*.061)%1;}
  private dustY(index:number):number{
    const span=Math.max(62,this.panelHeight()-75);
    return 5+(index%4)*3+this.dustFrac(index)*(48+(index*19)%span);
  }
  private dustOpacity(index:number):number{
    return Math.max(0,(.62-this.dustFrac(index)*.67)*(index%3===0?1:.72));
  }
  private panelEntranceY():number{return this.panelFromTop()?-17:22;}
  private saveUi():void{UiPreference.save(this.context,{language:this.language,accent:this.accent,palette:this.palette,motion:this.motion,followChat:this.followChat,stylusHints:this.stylusHints});}
  private setLanguage(value:string):void{
    if(value===this.language||this.langFade<1)return;
    this.markInteraction();
    this.getUIContext().animateTo({duration:this.motion?180:0,curve:Curve.EaseIn,onFinish:()=>{
      this.language=value;UiText.current=value;AppStorage.setOrCreate('selfLanguage',value);this.saveUi();this.revealStory();
      this.getUIContext().animateTo({duration:this.motion?300:0,curve:Curve.EaseOut},()=>{this.langFade=1;});
    }},()=>{this.langFade=0;});
  }
  private setAccent(value:string):void{this.getUIContext().animateTo({duration:this.motion?280:0,curve:Curve.EaseOut},()=>this.accent=value);this.saveUi();}
  @State showBeginning:boolean=true;
  @State replySources:string[]=[];
  @State productOpen:boolean=false;
  @State careLibraryOpen:boolean=false;
  @State careLibraryProductId:string='';
  @State careGuideText:string='';
  @State productSelection:ProductRecord=ProductRepository.records()[0];
  @State musicOn:boolean=false;
  @State navPressed:string='';
  @State buttonPulse:string='';
  @State panelDust:number=1;
  private pulseTimer:number=-1;
  private panelOpenTimer:number=-1;
  private dustTimer:number=-1;
  @State audioState:string='off';
  @State motion:boolean=true;
  @State palette:string='quiet';
  @State followChat:boolean=true;
  @State stylusHints:boolean=true;
  @State lastUtterance:string='';
  @State replyScale:number=1;
  @State replyOpacity:number=1;
  @StorageLink('selfForeground') @Watch('foregroundChanged') foreground:boolean=true;
  @State ready: boolean = false;
  @State selected: string = '';
  @State applied: boolean = false;
  @State @Watch('syncTransferIntent') busy: boolean = false;
  @State tool: string = 'NAVIGATE';
  @State detail: string = '';
  @State text: string = '';
  @State candidate: string = '';
  @State identity: string = '示例面容';
  @State workItems: WorkItem[] = [];
  @State bill: string[] = [];
  @State note: string = '';
  @State support: string = '';
  @State protectedLabel: string = '';
  @State animationValue: number = 0;
  @State playing: boolean = false;
  @State wide:boolean=false;
  private bubbleX():number{const x=this.focusX*this.surfaceWidth,r=this.focusHalfWidth*this.surfaceWidth;return Math.max(20,Math.min(this.surfaceWidth-380,x+r+24<this.surfaceWidth-360?x+r+24:x-r-384));}
  private bubbleY():number{return Math.max(20,Math.min(this.surfaceHeight-420,this.focusY*this.surfaceHeight-80));}
  private phoneBubbleHeight():number{return Math.min(this.candidate||this.applied?280:220,Math.max(180,this.surfaceHeight-140));}
  private planner:PlannerClient=new PlannerClient();
  @State cloudWaiting:boolean=false;
  @State cloudSessionEnabled:boolean=false;
  @State cloudConsentDecision:CloudConsentDecision='unknown';
  @State uploadOffer:boolean=false;
  @State choices:string[]=[];
  @State replyQuestion:string='';
  private replyQuestionKey:string='';
  private dialogue:DialogueTurn[]=[];
  private cloudGeneration:number=0;
  @State backendAddress:string='http://127.0.0.1:8787';
  @State backendToken:string='';
  private pendingCloudText:string='';
  private setCloudConsent(allowed:boolean):boolean{
    const decision:CloudConsentDecision=allowed?'allowed':'denied';
    if(!CloudConsentStore.save(this.context,decision))return false;
    this.cloudConsentDecision=decision;this.cloudSessionEnabled=allowed;
    if(!allowed){
      this.cloudGeneration++;this.planner.cancel();this.cloudWaiting=false;
      this.pendingCloudText='';this.uploadOffer=false;this.dialogue=[];this.choices=[];
    }
    return true;
  }
  private lastModelProductIds:string[]=[];
  private bridge: NativeRendererPort = new NativeRendererPort();
  private context: common.UIAbilityContext = this.getUIContext().getHostContext() as common.UIAbilityContext;
  private assets: AssetStore = new AssetStore(this.context);
  private works: WorkspaceStore = new WorkspaceStore(this.context,this.assets);
  private stars:PortraitStarStore=new PortraitStarStore(this.context,this.assets);
  private audio:AmbientAudio=new AmbientAudio(this.context);
  private session: SessionStore = new SessionStore();
  private previousTool: string = 'NAVIGATE';
  private timer: number = -1;
  private restoreRequest: string = '';
  private restoreNotice:string='';
  private previousSession: SessionStore | undefined = undefined;
  private reconTimer:number=-1;
  private reconJob:string='';
  private reconChecking:boolean=false;
  private personalActive():boolean{return !this.legacyEditorOpen&&!this.originMode&&!this.skyOpen&&this.showPersonal&&!!this.personalGaussianPath&&!!this.personalViewPath;}
  private introStory():string[][]{
    const zh=[
    ['星河深处，住着本来的你。','循光而行，看见独特之美。','从此学会爱自己。'],
    ['慢一点，星星会等你。','在无人注视的夜空里，你自有光。','把这份温柔，留给自己。'],
    ['深呼吸，你听见自己的心跳。','那节奏，和远方星光一样。','它在提醒：爱自己，从此刻开始。'],
    ['别急着赶路。','夜空里的每一粒光，都在陪你长大。','慢慢来，直到爱上此刻的自己。'],
    ['有些光，只为你亮着。','它不催促，也不评判。','愿你，一天比一天更爱自己。']];
    if(this.language==='zh')return zh;
    return zh.map((set:string[])=>set.map((s:string)=>this.tr(s)));}
  private story():string[]{
    if(this.language==='en')return [
    'Every side of you belongs here.','The lights you passed are still here.','Turn gently. Meet another side of yourself.',
     'Follow one small light, at your own pace.','Each star keeps a moment of yours.','There is room for every detail of you.',
     'No part of you needs to hide.','Wander among the moments that made you.','Rest your gaze on what you want to understand.'];
    const zh=['每一种模样，都值得被看见。','走过的光，还在这里等你。','轻轻转动，遇见另一面的自己。',
     '循着一粒微光，按自己的节奏前行。','每颗星辰，都留着那一刻的你。','你在意的细节，也属于完整的自己。',
     '不必藏起任何一面。','在星辰之间，看见一路的自己。','想细看哪里？先让目光停留片刻。'];
    return this.language==='zh'?zh:zh.map((s:string)=>this.tr(s));}
  private originLines():string[][]{
    if(this.language==='en')return [
    ['One small light is enough to begin.','Every step leaves a trace of light.'],
     ['What you care for grows beside you.','Even a quiet pause can shine.'],
     ['Cross gently; your light comes with you.','You have come farther than you think.'],
     ['Look up. There is room for your hopes.','The stars can wait while you find your way.'],
     ['After every journey, you can still be you.','Come home to every part of yourself.']];
    const zh=[['从一粒微光，慢慢走向夜空。','每一步，都留下属于自己的光。'],
     ['停一停，照亮身边的生长。','安静的片刻，也有自己的光。'],
     ['轻轻越过未知，光会与你同行。','回头看，你已走过很远。'],
     ['抬头看看，心里的星光还在。','星辰会等你，按自己的步调前行。'],
     ['走过许多路，依然自在地成为自己。','回来时，也拥抱每一面的自己。']];
    return this.language==='zh'?zh:zh.map((pair:string[])=>pair.map((s:string)=>this.tr(s)));}
  private originTitles():string[]{
    if(this.language==='en')return ['DEPARTURE','CARE','CROSSING','STARLIGHT','RETURN'];
    const zh=['启程','照料','跨越','寻光','归来'];
    return this.language==='zh'?zh:zh.map((s:string)=>this.tr(s));}
  private currentStoryLine():string{return !this.skyOpen&&!this.personalActive()?
    this.originLines()[this.originScene][this.originVerse]:this.story()[this.storyLine];}
  private onOriginScene(index:number):void{
    if(index<0||index>=5||this.originScene===index||this.skyOpen||this.personalActive())return;
    this.originScene=index;
    this.originVerse=this.originVisits[index]%2;
    this.originVisits[index]++;
    this.revealStory();
  }
  private markInteraction():void{this.lastInteractionAt=Date.now();}
  private revealStory(onComplete?:()=>void):void{
    if(this.characterTimer>=0)clearTimeout(this.characterTimer);
    this.characterTimer=-1;this.visibleCharacters=0;
    const line=this.currentStoryLine(),length=line.length;
    if(!this.motion){this.visibleCharacters=length;if(onComplete)onComplete();return;}
    const next=():void=>{
      this.visibleCharacters=Math.min(length,this.visibleCharacters+1);
      if(this.visibleCharacters>=length){this.characterTimer=-1;if(onComplete)onComplete();return;}
      const last=line[this.visibleCharacters-1];
      const delay=last==='，'||last==='。'||last==='.'?250:72+(this.visibleCharacters%4)*23;
      this.characterTimer=setTimeout(next,delay);
    };
    this.characterTimer=setTimeout(next,130);
  }
  private cueStory(kind:number,delay:number):void{
    if(this.storyCueTimer>=0)clearTimeout(this.storyCueTimer);
    this.storyCueTimer=-1;
    const group=[kind,kind+3,kind+6],visits=this.storyVisits[kind];
    let next=group[visits%3];
    if(next===this.storyLine)next=group[(visits+1)%3];
    this.storyVisits[kind]=visits+1;
    this.storyCueTimer=setTimeout(()=>{this.storyCueTimer=-1;this.storyLine=next;this.revealStory();},delay);
  }
  private startIntro(force:boolean=false):void{
    if(!force&&fs.accessSync(this.context.filesDir+'/self-intro-seen'))return;
    this.clearIntroTimers();
    const sets=this.introStory();
    const story=sets[Math.floor(Math.random()*sets.length)];
    this.introStage=1;this.introLines=story;this.introRevealed=story.map((_line:string)=>0);
    this.introPageOpacity=1;this.introOverlayOpacity=1;
    if(!this.motion){
      this.introRevealed=story.map((line:string)=>line.length);
      this.introTimers.push(setTimeout(()=>this.fadeIntroText(),1200));
      return;
    }
    this.introCharacterTimer=setTimeout(()=>this.revealIntroText(0,0),420);
  }
  private clearIntroTimers():void{
    this.introTimers.forEach((timer:number)=>clearTimeout(timer));this.introTimers=[];
    if(this.introCharacterTimer>=0)clearTimeout(this.introCharacterTimer);
    this.introCharacterTimer=-1;
  }
  private revealIntroText(lineIndex:number,charIndex:number):void{
    if(this.introStage!==1||lineIndex>=this.introLines.length)return;
    const line=this.introLines[lineIndex],length=line.length;
    if(charIndex>=length){
      if(lineIndex+1<this.introLines.length)this.introCharacterTimer=setTimeout(()=>this.revealIntroText(lineIndex+1,0),850);
      else this.introCharacterTimer=setTimeout(()=>this.fadeIntroText(),1500);
      return;
    }
    this.introRevealed[lineIndex]=charIndex+1;
    const last=line[charIndex];
    const delay=last==='，'||last==='。'||last==='、'||last==='.'||last===','?360:last===' '?150:100+(charIndex%3)*24;
    this.introCharacterTimer=setTimeout(()=>this.revealIntroText(lineIndex,charIndex+1),delay);
  }
  private fadeIntroText():void{
    if(this.introStage!==1)return;
    if(this.introCharacterTimer>=0){clearTimeout(this.introCharacterTimer);this.introCharacterTimer=-1;}
    this.getUIContext().animateTo({duration:this.motion?760:0,curve:Curve.EaseInOut},()=>{this.introPageOpacity=0;});
    this.introTimers.push(setTimeout(()=>this.fadeIntroOverlay(),this.motion?560:120));
  }
  private fadeIntroOverlay():void{
    if(this.introStage!==1)return;
    this.introStage=2;
    this.getUIContext().animateTo({duration:this.motion?1500:0,curve:Curve.EaseInOut},()=>{this.introOverlayOpacity=0;});
    this.introTimers.push(setTimeout(()=>this.finishIntro(),this.motion?1620:60));
  }
  private finishIntro():void{
    this.clearIntroTimers();
    this.introStage=0;this.introLines=[];this.introRevealed=[];
    this.introPageOpacity=1;this.introOverlayOpacity=1;
    this.assets.writeAtomic(this.context.filesDir+'/self-intro-seen','1');this.revealStory();
  }

  private activateGaussian(saved:SavedReconstruction,showNow:boolean=true):boolean{
    if(!/^[a-f0-9]{32}$/.test(saved.jobId))return false;
    const directory=this.context.filesDir+'/models/'+saved.jobId;
    const gaussian=directory+'/portrait.gaussian.ply',view=directory+'/portrait.view.json';
    if(saved.gaussian!==gaussian||saved.view!==view||!fs.accessSync(gaussian)||!fs.accessSync(view))return false;
    this.personalGaussianPath=gaussian;this.personalViewPath=view;this.showPersonal=true;this.legacyEditorOpen=false;this.personalReady=false;
    this.activeStarId=saved.jobId;this.originMode=!showNow;this.skyOpen=false;
    this.showBeginning=false;
    return true;
  }
  private async restoreGaussian():Promise<void>{
    const path=this.context.filesDir+'/reconstruction-result.json';
    if(!fs.accessSync(path))return;
    try{
      const saved=JSON.parse(fs.readTextSync(path)) as SavedReconstruction;
      if(!saved.gaussian||!/^[a-f0-9]{32}$/.test(saved.jobId))return;
      const expected=this.context.filesDir+'/models/'+saved.jobId+'/portrait.view.json';
      let refresh=saved.view!==expected||!fs.accessSync(expected);
      if(!refresh){
        try{const current=JSON.parse(fs.readTextSync(expected)) as ReconstructionView;refresh=current.targetFaceFraction!==.5;}
        catch(_){refresh=true;}
      }
      if(refresh){
        const client=new ReconstructionTransportClient();client.endpoint=this.backendAddress;client.token=this.backendToken;
        try{const view=await client.downloadView(saved.jobId,this.context.filesDir);saved.view=view;this.assets.writeAtomic(path,JSON.stringify(saved));}
        catch(error){console.error('SELF_PERSONAL_VIEW_REFRESH_FAILED '+String(error));if(fs.accessSync(expected))saved.view=expected;}
      }
      this.activateGaussian(saved,false);
      if(!fs.accessSync(this.stars.previewPath(saved.jobId))){
        const client=new ReconstructionTransportClient();client.endpoint=this.backendAddress;client.token=this.backendToken;
        try{await client.downloadPreview(saved.jobId,this.context.filesDir);this.refreshStars();}
        catch(_){/* The full personal model remains available without a thumbnail. */}
      }
    }catch(error){console.error('SELF_PERSONAL_RESTORE_FAILED '+String(error));}
  }

  private refreshStars():void{
    if(this.galaxyDissolvingId)return;
    this.starItems=this.stars.list();
    this.galaxySceneItems=this.starItems.map((star:PortraitStar)=>({jobId:star.jobId,name:star.name,
      viewPath:this.stars.modelPaths(star.jobId).view,scenePath:star.scene3dPath} as GalaxyScene));
  }
  private returnOrigin():void{
    this.flushGalaxyDelete();
    if(this.journey==='forming'){this.minimizeReconstruction();return;}
    this.markInteraction();this.clearPreviewToolsTimer();
    this.clearGalaxyCaption();this.galaxyDeleteId='';
    if(this.skyMounted){
      this.clearSkyTimers();this.skyTransition='leaving';this.galaxyTravelId='';this.galaxyDialOpen=false;
      this.getUIContext().animateTo({duration:this.motion?440:0,curve:Curve.EaseInOut},()=>this.skyVeil=.94);
      this.afterSky(this.motion?460:0,()=>{
        this.originMode=true;this.skyOpen=false;this.journey='idle';this.detail='';this.personalReady=false;
        this.originScene=0;this.revealStory();this.audio.setScene('origin');
        this.getUIContext().animateTo({duration:this.motion?1050:0,curve:Curve.EaseInOut},()=>{this.skyOpacity=0;this.skyVeil=0;});
        this.afterSky(this.motion?1080:0,()=>{this.skyMounted=false;this.skyTransition='idle';});
      });
      return;
    }
    this.originMode=true;this.skyOpen=false;
    this.journey='idle';
    this.personalReady=false;this.detail='';this.originScene=0;this.revealStory();this.audio.setScene('origin');
  }
  private enterSky():void{
    if(this.skyTransition!=='idle')return;
    this.markInteraction();this.refreshStars();this.clearPreviewToolsTimer();
    this.clearSkyTimers();this.skyTransition='entering';this.skyMounted=true;this.skyOpacity=0;this.skyVeil=0;
    this.galaxyStatus='';this.galaxyTravelId='';this.galaxyDialOpen=false;this.galaxyDeleteId='';this.previewReady=false;
    this.clearGalaxyCaption();this.galaxyCaptionChangedAt=Date.now();
    this.galaxyCaption=this.tr('走过的光，还在这里等你。');
    if(this.starItems.length>0)this.selectStarPreview(this.starItems.some((star:PortraitStar)=>star.jobId===this.previewStarId)?this.previewStarId:this.starItems[0].jobId);
    this.getUIContext().animateTo({duration:this.motion?560:0,curve:Curve.EaseInOut},()=>this.skyVeil=.94);
    this.afterSky(this.motion?580:0,()=>{
      this.originMode=true;this.skyOpen=true;this.journey='idle';this.detail='';this.personalReady=false;
      this.audio.setScene('sky');this.cueStory(1,220);
      this.getUIContext().animateTo({duration:this.motion?1200:0,curve:Curve.EaseInOut},()=>{this.skyOpacity=1;this.skyVeil=0;});
      this.afterSky(this.motion?1230:0,()=>this.skyTransition='idle');
    });
  }
  private clearSkyTimers():void{
    this.skyGeneration++;this.skyTimers.forEach((timer:number)=>clearTimeout(timer));this.skyTimers=[];
  }
  private afterSky(delay:number,action:()=>void):void{
    const generation=this.skyGeneration;
    this.skyTimers.push(setTimeout(()=>{if(generation===this.skyGeneration)action();},delay));
  }
  private clearGalaxyCaption():void{
    this.galaxyCaptionGeneration++;
    if(this.galaxyCaptionTimer>=0)clearTimeout(this.galaxyCaptionTimer);
    this.galaxyCaptionTimer=-1;this.galaxyCaptionOpacity=1;
  }
  private scheduleGalaxyCaption():void{
    this.clearGalaxyCaption();
    const generation=this.galaxyCaptionGeneration,id=this.previewStarId;
    const name=this.currentGalaxyName().trim();
    const unnamed=!name||/^(未命名的星辰|我的星辰[\s\d]*|\d+)$/.test(name);
    const shortName=name.length>12?name.slice(0,12)+'…':name;
    const caption=unnamed?(this.tr('走过的光，还在这里等你。')):
      (this.language==='en'?'Follow “'+shortName+'”, back to that moment.':this.language==='zh'?'循着「'+shortName+'」，回到那一刻。':this.tr('循着「')+shortName+this.tr('」，回到那一刻。'));
    if(caption===this.galaxyCaption)return;
    // Wait until a memory has settled, and allow at most one quiet change per six seconds.
    this.galaxyCaptionTimer=setTimeout(()=>{
      if(generation!==this.galaxyCaptionGeneration||id!==this.previewStarId||!this.skyOpen||this.galaxyTravelId)return;
      if(this.skyTransition!=='idle'){this.scheduleGalaxyCaption();return;}
      this.getUIContext().animateTo({duration:this.motion?450:0,curve:Curve.EaseInOut},()=>this.galaxyCaptionOpacity=0);
      this.galaxyCaptionTimer=setTimeout(()=>{
        if(generation!==this.galaxyCaptionGeneration||id!==this.previewStarId||!this.skyOpen||this.galaxyTravelId)return;
        this.galaxyCaption=caption;this.galaxyCaptionChangedAt=Date.now();this.galaxyCaptionTimer=-1;
        this.getUIContext().animateTo({duration:this.motion?700:0,curve:Curve.EaseInOut},()=>this.galaxyCaptionOpacity=1);
      },this.motion?480:0);
    },Math.max(2200,6000-(Date.now()-this.galaxyCaptionChangedAt)));
  }
  private recoverGalaxy(message:string=''):void{
    this.clearSkyTimers();this.galaxyTravelId='';this.originMode=true;this.skyOpen=true;
    this.skyMounted=true;this.skyTransition='idle';this.skyOpacity=1;this.skyVeil=0;
    this.personalReady=false;this.journey='idle';this.galaxyStatus=message;this.audio.setScene('sky');
    this.scheduleGalaxyCaption();
    this.cueStory(1,180);
  }
  private arriveAtGalaxy(id:string):void{
    if(this.skyTransition!=='approaching'||this.galaxyTravelId!==id)return;
    const paths=this.stars.modelPaths(id);
    if(!this.activateGaussian({jobId:id,gaussian:paths.gaussian,view:paths.view})){
      this.recoverGalaxy(this.tr('这段记忆暂时未能展开，可以稍后再试。'));return;
    }
    this.clearSkyTimers();this.skyTransition='loading';this.journey='idle';
    this.afterSky(30000,()=>this.recoverGalaxy(this.tr('星光走得有些慢，稍后可以再走近一次。')));
    console.info('SELF_STAR_OPEN '+id);
  }
  private finishGalaxyArrival():void{
    if(this.skyTransition!=='loading')return;
    this.clearSkyTimers();this.skyTransition='arriving';
    this.getUIContext().animateTo({duration:this.motion?1150:0,curve:Curve.EaseInOut},()=>this.skyOpacity=0);
    this.afterSky(this.motion?1180:0,()=>{
      this.skyMounted=false;this.galaxyTravelId='';this.skyTransition='idle';this.audio.setScene('personal');this.cueStory(2,120);this.resetPreviewTools();
    });
  }
  private requestGalaxyScene(id:string):void{
    const star=this.starItems.find((item:PortraitStar)=>item.jobId===id);
    if(!star||star.scene3dPath||this.pendingScenes.has(id))return;
    this.pendingScenes.add(id);
    const client=new ReconstructionTransportClient();client.endpoint=this.backendAddress;client.token=this.backendToken;
    client.downloadScene3d(id,this.context.filesDir).then(()=>{
      if(this.skyOpen)this.refreshStars();
    }).catch((error:Error)=>console.warn('SELF_GALAXY_SCENE_UNAVAILABLE '+String(error)))
      .finally(()=>this.pendingScenes.delete(id));
  }
  private selectStarPreview(id:string,navigate:boolean=true):void{
    if(this.galaxyTravelId)return;
    const star=this.starItems.find((item:PortraitStar)=>item.jobId===id);
    if(!star)return;
    this.previewStarId=id;this.galaxyStatus='';this.markInteraction();
    this.scheduleGalaxyCaption();
    if(navigate)this.galaxyNavigationSerial++;
    const index=this.starItems.findIndex((item:PortraitStar)=>item.jobId===id);
    for(let at=Math.max(0,index-1);at<=Math.min(this.starItems.length-1,index+1);at++)
      this.requestGalaxyScene(this.starItems[at].jobId);
  }
  private nextGalaxy():void{
    if(this.starItems.length===0)return;
    const index=this.starItems.findIndex((star:PortraitStar)=>star.jobId===this.previewStarId);
    this.selectStarPreview(this.starItems[(index+1)%this.starItems.length].jobId);
  }
  private setGalaxyDial(open:boolean):void{
    this.markInteraction();
    if(!open){this.flushGalaxyDelete();this.galaxyDeleteId='';this.galaxyRenameId='';this.galaxyRenameDraft='';}
    this.getUIContext().animateTo({duration:this.motion?420:0,
      curve:this.motion?'spring(0,1,390,34)':Curve.EaseOut},()=>this.galaxyDialOpen=open);
  }
  private chooseGalaxy(id:string):void{
    if(this.previewStarId!==id)this.selectStarPreview(id,false);
  }
  private currentGalaxyName():string{
    return this.starItems.find((star:PortraitStar)=>star.jobId===this.previewStarId)?.name||'';
  }
  private setGalaxyDelete(id:string):void{
    if(this.galaxyDissolvingId||this.galaxyRiseIds.length||!this.skyOpen||this.skyTransition!=='idle'||(id&&!this.starItems.some((star:PortraitStar)=>star.jobId===id)))return;
    this.markInteraction();
    this.getUIContext().animateTo({duration:this.motion?220:0,curve:Curve.EaseInOut},()=>{this.galaxyDeleteId=id;this.galaxyRenameId='';});
  }
  private setGalaxyRename(id:string):void{
    if(this.galaxyDissolvingId||this.galaxyRiseIds.length||!this.skyOpen||this.skyTransition!=='idle')return;
    if(id){
      const star=this.starItems.find((item:PortraitStar)=>item.jobId===id);
      if(!star)return;
      if(this.galaxyRenameId!==id)this.galaxyRenameDraft=star.name;
    }
    this.markInteraction();
    this.getUIContext().animateTo({duration:this.motion?220:0,curve:Curve.EaseInOut},()=>{this.galaxyRenameId=id;this.galaxyDeleteId='';});
  }
  private saveGalaxyRename(id:string):void{
    if(this.galaxyRenameId!==id||this.galaxyDissolvingId||this.galaxyRiseIds.length)return;
    const name=PortraitStarStore.cleanName(this.galaxyRenameDraft);
    try{
      this.stars.upsert(id,name);
      this.refreshStars();
      this.galaxyRenameDraft='';
      this.getUIContext().animateTo({duration:this.motion?220:0,curve:Curve.EaseInOut},()=>{this.galaxyRenameId='';});
      if(this.previewStarId===id)this.scheduleGalaxyCaption();
    }catch(error){console.warn('SELF_STAR_RENAME_FAILED '+String(error));}
  }
  private removeGalaxy(id:string):void{
    if(this.galaxyDissolvingId||this.galaxyRiseIds.length||!this.skyOpen||this.skyTransition!=='idle'||this.galaxyDeleteId!==id)return;
    const index=this.starItems.findIndex((star:PortraitStar)=>star.jobId===id);
    if(index<0)return;
    try{
      this.stars.remove(id);
      this.markInteraction();this.galaxyDeletedIndex=index;this.galaxyDissolvingId=id;
      if(!this.motion)this.finishGalaxyDelete(id);
    }catch(error){
      this.galaxyStatus=this.tr('本地星辰暂未清理完成，请再试一次。');
      console.warn('SELF_STAR_DELETE_FAILED '+String(error));
    }
  }
  private resetGalaxyRise():void{
    if(this.galaxyRiseTimer>=0)clearTimeout(this.galaxyRiseTimer);
    this.galaxyRiseTimer=-1;this.galaxyRiseIds=[];this.galaxyRiseOffset=0;
  }
  private flushGalaxyDelete():void{
    if(this.galaxyDissolvingId)this.finishGalaxyDelete(this.galaxyDissolvingId);
    this.resetGalaxyRise();
    this.galaxyFlight=undefined;
  }
  private finishGalaxyDelete(id:string,height:number=0):void{
    if(this.galaxyDissolvingId!==id)return;
    if(this.galaxyFlight?.id===id)this.galaxyFlight=undefined;
    const index=this.galaxyDeletedIndex;
    this.resetGalaxyRise();
    if(this.motion&&height>0){
      this.galaxyRiseIds=this.starItems.slice(index+1).map((star:PortraitStar)=>star.jobId);
      this.galaxyRiseOffset=height+4;
    }
    this.galaxyDissolvingId='';this.galaxyDeleteId='';this.galaxyDeletedIndex=-1;
      if(this.activeStarId===id){
        this.activeStarId='';this.personalGaussianPath='';this.personalViewPath='';this.personalReady=false;
      }
      const savedPath=this.context.filesDir+'/reconstruction-result.json';
      try{
        if(fs.accessSync(savedPath)&&(JSON.parse(fs.readTextSync(savedPath)) as SavedReconstruction).jobId===id)fs.unlinkSync(savedPath);
      }catch(error){console.warn('SELF_STAR_DELETE_REFERENCE_FAILED '+String(error));}
      this.refreshStars();
      if(this.previewStarId===id){
        this.clearGalaxyCaption();
        this.galaxyCaption=this.tr('走过的光，还在这里等你。');
        this.galaxyCaptionChangedAt=Date.now();
        this.previewStarId='';
        if(this.starItems.length>0)this.selectStarPreview(this.starItems[Math.min(index,this.starItems.length-1)].jobId);
      }
      this.galaxyStatus=this.tr('这颗星辰已删除。');
      console.info('SELF_STAR_DELETED '+id);
    if(this.galaxyRiseIds.length){
      this.galaxyRiseTimer=setTimeout(()=>{
        this.galaxyRiseTimer=-1;
        this.getUIContext().animateTo({duration:560,curve:'spring(0,1,280,26)'},()=>this.galaxyRiseOffset=0);
        this.galaxyRiseTimer=setTimeout(()=>this.resetGalaxyRise(),600);
      },32);
    }
  }
  private openStar(id:string):void{
    if(this.galaxyDissolvingId||this.skyTransition!=='idle')return;
    const star=this.starItems.find((item:PortraitStar)=>item.jobId===id);
    if(!star)return;
    const paths=this.stars.modelPaths(id);
    if(this.skyOpen){
      if(!fs.accessSync(paths.gaussian)||!fs.accessSync(paths.view)){
        this.galaxyStatus=this.tr('这段记忆暂时未能展开，可以稍后再试。');return;
      }
      this.clearSkyTimers();this.clearGalaxyCaption();this.markInteraction();this.galaxyStatus='';this.galaxyDialOpen=false;this.galaxyDeleteId='';
      this.skyTransition='approaching';this.galaxyTravelId=id;this.audio.setScene('travel');
      this.afterSky(12000,()=>this.recoverGalaxy(this.tr('星光暂时停了一下，请再试一次。')));
      return;
    }
    if(!this.activateGaussian({jobId:id,gaussian:paths.gaussian,view:paths.view}))return;
    this.markInteraction();this.journey='revealing';this.revealOpacity=1;this.revealScale=.35;this.audio.setScene('personal');
    this.cueStory(2,1200);this.resetPreviewTools();
    console.info('SELF_STAR_OPEN '+id);
  }
  private saveStarName():void{
    if(this.journey!=='forming'||this.reconCancelling||this.starNameKept||!this.starNameDraft.trim())return;
    const name=PortraitStarStore.cleanName(this.starNameDraft);
    try{
      if(this.reconJob)this.assets.writeAtomic(this.context.filesDir+'/reconstruction-pending.json',
        JSON.stringify({jobId:this.reconJob,name} as PendingReconstruction));
    }catch(error){
      this.starNameError=this.tr('名字暂时没能留下，请再试一次。');
      console.warn('SELF_STAR_NAME_SAVE_FAILED '+String(error));return;
    }
    this.markInteraction();this.clearStarNameFocus();this.starNameController.stopEditing();
    this.starNameDraft=name;this.keptStarName=name;this.starNameError='';
    this.setStarNameKept(true);
    this.syncReconstructionActivity();
    console.info('SELF_STAR_NAME_SAVED '+name.length);
  }
  private editStarName():void{
    if(this.journey!=='forming'||this.reconCancelling||!this.starNameKept)return;
    this.markInteraction();this.starNameDraft=this.keptStarName;this.starNameError='';
    this.setStarNameKept(false);this.focusStarName();
  }
  private setStarNameKept(kept:boolean,animated:boolean=true):void{
    // Keep layout and focus changes outside animation transactions. Only the two
    // fixed layers dissolve; removing a child must never animate its parent's width.
    this.starNameKept=kept;
    if(!this.motion||!animated){
      this.starNameEditorPresence=kept?0:1;this.starNameLabelPresence=kept?1:0;return;
    }
    this.getUIContext().animateTo({duration:kept?220:280,delay:kept?0:80,curve:Curve.EaseOut},()=>{
      this.starNameEditorPresence=kept?0:1;
    });
    this.getUIContext().animateTo({duration:kept?560:160,delay:kept?100:0,curve:Curve.EaseOut},()=>{
      this.starNameLabelPresence=kept?1:0;
    });
  }
  private starNameEditorY():number{
    return Math.max(16,Math.min(this.surfaceHeight*(this.wide?.74:.70),this.surfaceHeight-174));
  }
  private starNameLabelY():number{
    return Math.min(this.surfaceHeight*.595,this.starNameEditorY()+20);
  }
  private starNameLightY():number{
    return Math.min(.555,(this.starNameLabelY()-22)/Math.max(1,this.surfaceHeight));
  }
  private clearStarNameFocus():void{
    if(this.starNameFocusTimer>=0)clearTimeout(this.starNameFocusTimer);
    this.starNameFocusTimer=-1;
  }
  private focusStarName():void{
    this.clearStarNameFocus();
    if(!this.keptStarName)return;
    this.starNameFocusTimer=setTimeout(()=>{
      this.starNameFocusTimer=-1;
      if(this.journey==='forming'&&!this.starNameKept&&!this.reconCancelling)
        this.getUIContext().getFocusController().requestFocus('star-name-input');
    },this.motion?380:32);
  }

  private setFormationLine(line:string):void{
    if(this.formationLine===line)return;
    if(this.formationTimer>=0)clearInterval(this.formationTimer);
    this.formationLine=line;this.formationChars=this.motion?0:line.length;
    if(this.motion&&line.length>0)this.formationTimer=setInterval(()=>{
      this.formationChars=Math.min(this.formationLine.length,this.formationChars+1);
      if(this.formationChars>=this.formationLine.length){clearInterval(this.formationTimer);this.formationTimer=-1;}
    },92);
  }
  private finishCancelledReconstruction():void{
    this.finishReconstruction();this.uploadingJobId='';this.reconCancelling=false;
    this.waitingMinimized=false;this.reconstructionOutcome='';this.reconstructionReadyId='';
    this.reconProgress=0;this.captureStatus='';this.journey='idle';this.setFormationLine('');this.audio.setScene('origin');
    this.revealStory();console.info('SELF_RECON_CANCELLED');
  }
  private async cancelReconstruction():Promise<void>{
    if(this.reconCancelling)return;
    this.clearStarNameFocus();this.starNameController.stopEditing();
    this.cancelledSubmissionId=this.submissionId;this.reconCancelling=true;
    this.setFormationLine(this.tr('这束光，正轻轻停下。'));
    const jobId=this.reconJob||this.uploadingJobId;
    if(!jobId){if(!this.reconSubmitting)this.finishCancelledReconstruction();return;}
    const client=new ReconstructionTransportClient();client.endpoint=this.backendAddress;client.token=this.backendToken;
    try{
      const result=await client.cancelJob(jobId);
      if(['cancelled','gaussian_ready','complete'].includes(result.state))this.finishCancelledReconstruction();
      else if(!this.reconJob){this.trackReconstruction(jobId);this.reconCancelling=true;this.captureStatus=this.tr('星光正在慢慢停下。');}
    }catch(error){
      console.error('SELF_RECON_CANCEL_FAILED '+String(error));
      this.reconCancelling=false;this.captureStatus=this.tr('暂时没能确认停止，连接恢复后可以再试。');
    }
  }

  private trackReconstruction(jobId:string):void{
    if(!/^[a-f0-9]{32}$/.test(jobId))return;
    this.reconJob=jobId;
    this.assets.writeAtomic(this.context.filesDir+'/reconstruction-pending.json',
      JSON.stringify({jobId,name:this.keptStarName} as PendingReconstruction));
    this.reconstructionActive=true;this.reconstructionOutcome='';
    this.journey=this.waitingMinimized?'idle':'forming';this.reconProgress=Math.max(6,this.reconProgress);this.captureStatus=this.tr('你的轮廓，正在星光里渐渐清晰。');
    if(!this.reconCancelling)this.setFormationLine(this.tr('每一面的你，都在慢慢靠近。'));
    if(this.reconTimer<0)this.reconTimer=setInterval(()=>this.pollReconstruction(),5000);
    this.pollReconstruction();
    this.syncReconstructionActivity();
  }
  private finishReconstruction():void{
    this.clearStarNameFocus();this.starNameController.stopEditing();
    if(this.reconTimer>=0)clearInterval(this.reconTimer);this.reconTimer=-1;this.reconJob='';
    this.reconstructionActive=false;this.syncReconstructionActivity();
    const path=this.context.filesDir+'/reconstruction-pending.json';if(fs.accessSync(path))fs.unlinkSync(path);
  }
  private async pollReconstruction():Promise<void>{
    if(this.reconChecking||!this.reconJob)return;
    this.reconChecking=true;
    const jobId=this.reconJob,client=new ReconstructionTransportClient();
    client.endpoint=this.backendAddress;client.token=this.backendToken;
    try{
      const result=await client.status(jobId);if(this.reconJob!==jobId)return;
      if(result.state==='cancelled'){this.finishCancelledReconstruction();return;}
      if(result.state==='cancel_requested'||this.reconCancelling){this.captureStatus=this.tr('星光正在慢慢停下。');return;}
      if(result.state==='failed'){
        this.captureStatus=result.message==='face_not_confirmed_in_capture'?'这段拍摄还没能看清完整面容，可以换个光线再试。':
          result.message==='camera_angles_insufficient'?'这次没有拍到面容的两侧。可以保持头部自然不动，让镜头从一侧缓慢绕到另一侧再试。':
          '这次立体建模中途停住了。拍摄还在采集记录里，可以直接重试。';
        this.subtitle=this.captureStatus;this.reconstructionOutcome='failed';
        this.journey=this.waitingMinimized?'idle':'failed';this.reconCanRetry=false;this.finishReconstruction();return;
      }
      if(result.state==='gaussian_ready'){
        // Finish the transfer on return to the app. Background polling can still report server progress.
        if(!this.foreground){this.reconProgress=Math.max(this.reconProgress,85);this.captureStatus=this.tr('轮廓已构建，回到 SELF 即可接回星辰。');return;}
          this.reconProgress=Math.max(this.reconProgress,85);
          this.captureStatus=this.tr('这颗星辰正在来到你身边。');
        const view=await client.downloadView(jobId,this.context.filesDir);
          const file=await client.downloadGaussian(jobId,this.context.filesDir,(value:number)=>{
            if(this.reconJob===jobId)this.reconProgress=Math.max(this.reconProgress,85+Math.round(value*10));
          });
        try{await client.downloadPreview(jobId,this.context.filesDir);}catch(error){console.warn('SELF_STAR_PREVIEW_UNAVAILABLE '+String(error));}
        try{await client.downloadPreview3d(jobId,this.context.filesDir);}catch(error){console.warn('SELF_STAR_3D_PREVIEW_UNAVAILABLE '+String(error));}
        try{await client.downloadScene3d(jobId,this.context.filesDir);}catch(error){console.warn('SELF_GALAXY_SCENE_UNAVAILABLE '+String(error));}
        if(this.reconJob!==jobId)return;
        const saved:SavedReconstruction={jobId,gaussian:file,view};
        this.assets.writeAtomic(this.context.filesDir+'/reconstruction-result.json',JSON.stringify(saved));
        this.stars.upsert(jobId,this.keptStarName||this.starNameDraft);this.refreshStars();
        this.reconProgress=100;
        if(this.waitingMinimized){
          this.reconstructionReadyId=jobId;this.reconstructionOutcome='ready';
        }else{
          this.activateGaussian(saved);this.cueStory(2,1800);
          this.journey='revealing';this.revealOpacity=1;this.revealScale=.35;this.audio.setScene('personal');this.resetPreviewTools();
        }
        this.captureStatus=result.viewpointQuality?.broadSideCoverage===false?
          '星辰已构建。想看更清楚的侧面，下次可让镜头再多绕一点。':this.waitingMinimized?'你的星辰已构建完成，轻触即可走近。':'你的立体面容正在打开…';
        this.subtitle=this.captureStatus;this.pendingCaptureName='';this.finishReconstruction();return;
      }
      if(result.state==='complete'){
        const file=await client.downloadMesh(jobId,this.context.filesDir);
        if(this.reconJob!==jobId)return;
        this.assets.writeAtomic(this.context.filesDir+'/reconstruction-result.json',JSON.stringify({jobId,mesh:file}));
        this.captureStatus=this.tr('新的轮廓已经来到这里，正在寻找最合适的呈现方式。');this.subtitle=this.captureStatus;
        this.reconstructionOutcome='failed';this.journey=this.waitingMinimized?'idle':'failed';this.audio.setScene('origin');
        this.finishReconstruction();return;
      }
      this.reconProgress=Math.max(this.reconProgress,Math.max(5,Math.min(96,result.progress)));
      this.captureStatus=this.reconProgress<35?'正从光点里，找回你的轮廓。':this.reconProgress<75?'每一个角度，都在慢慢靠近。':'快看见更完整的你了。';
      this.setFormationLine(this.reconProgress<35?'每一面的你，都在慢慢靠近。':this.reconProgress<75?'星光正留下你的轮廓。':'快看见更完整的你了。');
      }catch(error){
        console.error('SELF_RECON_RECEIVE_FAILED '+String(error));
        if(this.reconJob===jobId)this.captureStatus=this.tr('连接暂时停了一下，恢复后会继续接回你的星辰。');
      }
    finally{this.reconChecking=false;this.syncReconstructionActivity();}
  }
  private async submitCapture(name:string):Promise<void>{
    if(!/^capture-[0-9]+\.mp4$/.test(name)){this.captureStatus=this.tr('没有找到这段拍摄，请重新选择。');this.journey='failed';return;}
    if(this.reconJob||this.reconSubmitting)return;
    const attempt=++this.submissionId;
    const client=new ReconstructionTransportClient();client.endpoint=this.backendAddress;client.token=this.backendToken;
    if(this.detail)this.close();
    try{
      if(this.pendingCaptureName!==name){this.starNameDraft='';this.keptStarName='';this.setStarNameKept(false,false);}
      this.starNameError='';this.clearStarNameFocus();
      this.waitingMinimized=false;this.reconstructionOutcome='';this.reconstructionReadyId='';this.reconstructionActive=true;
      this.pendingCaptureName=name;this.uploadingJobId='';this.reconSubmitting=true;this.reconCanRetry=false;this.reconCancelling=false;this.originMode=true;this.skyOpen=false;
      this.journey='forming';this.reconProgress=5;this.captureStatus=this.tr('正从光点里，找回你的轮廓。');this.audio.setScene('forming');
      this.setFormationLine(this.tr('每一面的你，都在慢慢靠近。'));
      const health=await client.probe();if(health.engine!=='ready')throw new Error('建模服务尚未就绪');
      if(this.cancelledSubmissionId===attempt)throw new Error('upload_cancelled');
      const path=this.context.filesDir+'/captures/'+name;
      if(!fs.accessSync(path))throw new Error('拍摄文件没有找到');
      const jobId=await client.uploadCapture(path,(value:number)=>this.reconProgress=Math.max(5,Math.round(value*22)),
        (created:string)=>this.uploadingJobId=created,()=>this.cancelledSubmissionId===attempt);
      if(this.cancelledSubmissionId===attempt){await client.cancelJob(jobId);throw new Error('upload_cancelled');}
      this.uploadingJobId='';
      this.trackReconstruction(jobId);
    }catch(error){
      if(this.cancelledSubmissionId===attempt){
        if(this.uploadingJobId){
          try{
            const result=await client.cancelJob(this.uploadingJobId);
            if(result.state==='cancel_requested'){
              this.trackReconstruction(this.uploadingJobId);this.reconCancelling=true;
              this.captureStatus=this.tr('星光正在慢慢停下。');
            }else this.finishCancelledReconstruction();
          }catch(cancelError){
            console.error('SELF_RECON_CANCEL_UNCONFIRMED '+String(cancelError));
            this.reconCancelling=false;this.captureStatus=this.tr('暂时没能确认停止，连接恢复后可以再试。');
          }
        }else this.finishCancelledReconstruction();
        return;
      }
      const reason=String(error);console.error('SELF_RECON_SUBMIT_FAILED '+reason);
      if(this.uploadingJobId){try{await client.cancelJob(this.uploadingJobId);}catch(_){}this.uploadingJobId='';}
      this.reconCanRetry=!reason.includes('过大')&&!reason.includes('不完整')&&!reason.includes('没有找到');
      this.journey='failed';this.captureStatus=this.reconCanRetry?
        '星光暂时没能连接。拍摄已留下，连接恢复后轻触重试。':
        '这段拍摄暂时无法使用。原片还在，可以再拍一次。';
    }finally{
      this.reconSubmitting=false;
      if(this.journey==='failed'){
        this.reconstructionActive=false;this.reconstructionOutcome='failed';
        if(this.waitingMinimized)this.journey='idle';
      }
      this.syncReconstructionActivity();
    }
  }

  private syncReconstructionActivity():void{
    ReconstructionLiveActivity.shared().sync({active:this.reconstructionActive,
      name:this.keptStarName,progress:this.reconProgress,message:this.captureStatus,language:this.language});
  }
  private minimizeReconstruction():void{
    if(!this.reconstructionActive)return;
    this.clearStarNameFocus();this.starNameController.stopEditing();this.markInteraction();
    this.waitingMinimized=true;this.journey='idle';
    this.originMode=true;this.skyOpen=false;this.personalReady=false;this.detail='';this.audio.setScene('origin');
    this.revealStory();this.syncReconstructionActivity();
  }
  private openReconstructionProgress():void{
    if(!this.reconstructionActive&&!this.reconstructionOutcome)return;
    this.clearSkyTimers();this.clearGalaxyCaption();this.close();
    this.careLibraryOpen=false;this.productOpen=false;this.legacyEditorOpen=false;
    this.skyMounted=false;this.skyOpen=false;this.skyOpacity=0;this.skyVeil=0;this.skyTransition='idle';this.galaxyTravelId='';
    this.waitingMinimized=false;this.originMode=true;this.markInteraction();
    if(this.reconstructionOutcome==='ready'){
      const id=this.reconstructionReadyId;this.reconstructionOutcome='';this.reconstructionReadyId='';
      this.openStar(id);return;
    }
    this.journey=this.reconstructionOutcome==='failed'?'failed':'forming';
    this.audio.setScene(this.journey==='failed'?'origin':'forming');
    this.setStarNameKept(this.starNameKept,false);
    if(this.reconstructionActive)this.pollReconstruction();
  }
  private hasProgressCapsule():boolean{return this.waitingMinimized&&(this.reconstructionActive||!!this.reconstructionOutcome);}
  private previewBarY():number{return this.hasProgressCapsule()?(this.wide?104:164):(this.wide?42:105);}
  private previewCaptionBaseY():number{return Math.max(this.surfaceHeight*(this.skyOpen?.145:this.wide?.22:.18),this.hasProgressCapsule()&&!this.wide?(this.personalActive()?224:178):0);}
  private clearPreviewToolsTimer():void{if(this.previewToolsTimer>=0){clearTimeout(this.previewToolsTimer);this.previewToolsTimer=-1;}}
  private resetPreviewTools():void{
    this.clearPreviewToolsTimer();
    this.previewCaptionY=this.previewCaptionBaseY();
    this.previewToolsCollapsed=false;this.previewCaptionOpacity=0;
    this.previewCaptionTyped=false;this.previewFresh=true;this.previewCaptionSub=0;
    this.previewToolsTimer=setTimeout(()=>{this.previewToolsTimer=-1;this.collapsePreviewTools();},2100);
  }
  private collapsePreviewTools():void{
    if(this.previewToolsCollapsed||!this.personalActive())return;
    this.previewCaptionY=this.wide?112:this.previewBarY();
    const ui=this.getUIContext();
    if(this.motion)ui.animateTo({curve:'spring(0,1,420,32)'},()=>{this.previewToolsCollapsed=true;});
    else this.previewToolsCollapsed=true;
    if(this.previewFresh){
      this.previewFresh=false;this.visibleCharacters=0;
      const typeIn=():void=>{
        if(!this.previewToolsCollapsed||!this.personalActive())return;
        this.previewCaptionTyped=true;this.previewCaptionOpacity=1;
        this.revealStory(()=>{
          if(!this.previewCaptionTyped)return;
          if(this.motion)this.getUIContext().animateTo({duration:420,curve:Curve.EaseOut},()=>{this.previewCaptionSub=1;});
          else this.previewCaptionSub=1;
        });
      };
      if(this.motion)setTimeout(typeIn,300);
      else typeIn();
    }else if(this.motion){
      ui.animateTo({duration:360,curve:Curve.EaseOut,delay:120},()=>{this.previewCaptionOpacity=1;});
    }else{
      this.previewCaptionOpacity=1;
    }
  }
  private expandPreviewTools():void{
    if(!this.previewToolsCollapsed)return;
    if(this.previewCaptionTyped){this.previewCaptionOpacity=1;this.previewCaptionTyped=false;}
    const ui=this.getUIContext();
    if(this.motion){
      ui.animateTo({curve:'spring(0,1,320,20)'},()=>{this.previewToolsCollapsed=false;});
      ui.animateTo({duration:200,curve:Curve.EaseIn},()=>{this.previewCaptionOpacity=0;});
    }else{
      this.previewToolsCollapsed=false;this.previewCaptionOpacity=0;
    }
    this.clearPreviewToolsTimer();
    this.previewToolsTimer=setTimeout(()=>{this.previewToolsTimer=-1;this.collapsePreviewTools();},2600);
  }
  private setPreviewCaptionSuppressed(suppressed:boolean):void{
    if(this.previewCaptionSuppressed===suppressed)return;
    const ui=this.getUIContext();
    if(suppressed){ui.animateTo({duration:220,curve:Curve.EaseIn},()=>{this.previewCaptionSuppressed=true;});}
    else{ui.animateTo({duration:340,curve:Curve.EaseOut,delay:100},()=>{this.previewCaptionSuppressed=false;});}
  }
  private progressAwareTop():number{return this.hasProgressCapsule()&&!this.wide?170:this.detailTop;}
  private progressCapsuleWidth():number{return Math.min(360,this.windowWidth-44);}
  private progressCapsuleY():number{
    return this.wide?42:104;
  }

  aboutToAppear(): void {
    this.transferPageActive=true;this.attachTransfer();
    const ui=UiPreference.load(this.context);this.language=ui.language;this.accent=ui.accent;this.palette=ui.palette;this.motion=ui.motion;this.followChat=ui.followChat;this.stylusHints=ui.stylusHints;UiText.current=ui.language;AppStorage.setOrCreate('selfLanguage',ui.language);
    this.cloudConsentDecision=CloudConsentStore.load(this.context);
    this.cloudSessionEnabled=this.cloudConsentDecision==='allowed';
    this.bridge.onSelectionAnchor=(x:number,y:number,halfWidth:number)=>{this.focusX=x;this.focusY=y;this.focusHalfWidth=halfWidth;};
    this.bridge.onToolChanged=(name:string)=>{this.tool=name;this.focusOpen=false;};
    this.audio.onStatus=(state:string)=>{this.audioState=state;if(state!=='playing')this.musicPulse=0;if(this.context.applicationInfo.debug)console.info('SELF_AUDIO_STATE '+state);if(state==='error'){this.musicOn=false;this.subtitle=this.tr('音乐暂时无法播放，你可以继续安静地使用镜面。');}};
    this.audio.onPulse=(value:number)=>this.musicPulse=value;
    this.startIntro();if(this.introStage===0)this.revealStory();

    this.assets.registerRaw('sample-lee','assets/sample-head.glb');
    for(const name of ['lip','editable','protectionTest']){
      this.assets.registerRaw(name,'assets/'+name+'.mask');
      const r:RegionRecord={regionId:name,assetId:this.session.assetId,assetVersion:this.session.assetVersion,width:1024,height:1024,semantic:name==='lip'?'confirmed-lips':'manual',fileName:name+'.mask'};
      this.session.regions.push(r);
    }
    this.works.loadPreference(this.session);this.labels();
    this.refreshStars();
    const pending=this.context.filesDir+'/reconstruction-pending.json';
    if(fs.accessSync(pending)){try{const saved=JSON.parse(fs.readTextSync(pending)) as PendingReconstruction;this.starNameDraft=saved.name||'';this.keptStarName=this.starNameDraft;this.setStarNameKept(!!this.keptStarName,false);this.trackReconstruction(saved.jobId);}catch(_){}}
    this.restoreGaussian();
    this.audio.setScene(this.skyOpen?'sky':this.personalActive()?'personal':'origin');
    this.bridge.onMessage=(m:Envelope)=>this.receive(m);
    this.bridge.onBytes=(kind:string,bytes:ArrayBuffer)=>{
      try{
        if(kind==='selection'){
          if(bytes.byteLength!==this.session.width*this.session.height)throw new Error('蒙版尺寸不一致');
          if(!new Uint8Array(bytes).some((v:number)=>v>0))throw new Error('这里没有选到面容，请在可见区域重新圈画');
          const id='region-'+Date.now();const fileName=this.assets.saveMask(id,bytes);
          const r:RegionRecord={regionId:id,assetId:this.session.assetId,assetVersion:this.session.assetVersion,width:this.session.width,height:this.session.height,semantic:'manual',fileName};
          this.session.regions.push(r);this.session.regionVersion++;this.session.sceneRevision++;this.bridge.sendBytes('mask:'+id,new Uint8Array(bytes));this.selected=id;
          this.showBeginning=false;this.dialogue=[];this.choices=[];this.uploadOffer=false;this.pendingCloudText='';this.productOpen=false;this.replySources=[];this.lastModelProductIds=[];this.getUIContext().animateTo({duration:this.motion?280:0,curve:Curve.EaseOut},()=>{this.focusOpen=true;});this.tool='NAVIGATE';this.bridge.send('SET_TOOL',{tool:'NAVIGATE'});this.subtitle=this.tr('想说说这里，还是试一点变化？也可以就这样。');console.info('SELF_SELECTION_SAVED '+id+' '+bytes.byteLength);
        }
        if(kind==='png'){
          const p=new Uint8Array(bytes);if(p[0]!==137||p[1]!==80||p[2]!==78||p[3]!==71)throw new Error('PNG 数据无效');
          this.assets.writeAtomic(this.context.filesDir+'/self-export.png',bytes);this.busy=false;this.subtitle=this.tr('PNG 已保存到应用私有目录');console.info('SELF_EXPORT_SAVED '+bytes.byteLength);
        }
        if(kind==='echo'){const p=new Uint8Array(bytes);console.info('SELF_BINARY_ROUNDTRIP '+(p.length===65539&&p.every((v:number,i:number)=>v===i%256)));}
      }catch(e){this.fail(String(e));}
    };
  }
  private fail(message:string):void{this.busy=false;this.subtitle=message;console.error('SELF_ERROR '+message);}
  private async requestCloud():Promise<void>{
    if(this.cloudWaiting||!this.pendingCloudText||!this.cloudSessionEnabled||!CloudConsentStore.allowed(this.context))return;
    const generation=++this.cloudGeneration;const input=this.pendingCloudText;this.pendingCloudText='';this.planner.endpoint=this.backendAddress.trim();this.planner.token=this.backendToken.trim();
    if(this.detail)this.close();this.uploadOffer=false;this.cloudWaiting=true;this.subtitle=this.tr('让我想想，怎么更贴近你的想法…');
    const snapshot=this.planner.snapshot(this.session,input);snapshot.productContextIds=this.lastModelProductIds.slice();snapshot.responseLanguage=this.language;
    snapshot.careAdviceRequested=true;
    snapshot.dialogue=this.dialogue.slice(-3);
    if(/^[1-3]$/.test(input)&&this.choices.length>=Number(input))snapshot.resolvedChoice=this.choices[Number(input)-1];
    else if(this.choices.includes(input))snapshot.resolvedChoice=input;
    this.choices=[];
    try{const regionId=this.selected||(this.session.sourceKind==='MESH'?'lip':'');const capture=await this.bridge.capture(regionId);snapshot.view=capture.view;snapshot.imageWidth=capture.width;snapshot.imageHeight=capture.height;snapshot.annotatedRegionId=regionId;
      snapshot.regions=snapshot.regions.filter((r)=>r.regionId===regionId||snapshot.layers.some((l)=>l.regionId===r.regionId)||snapshot.protectedRegionIds.includes(r.regionId));
      if(this.session.sceneRevision!==snapshot.sceneRevision||this.session.regionVersion!==snapshot.regionVersion)throw new Error('作品状态已改变，请重新提出请求');
      const response=await this.planner.propose(snapshot,capture.images);
      if(!this.cloudWaiting||generation!==this.cloudGeneration||!CloudConsentStore.allowed(this.context))return;
      if(this.session.pending||this.session.assetId!==snapshot.assetId||this.session.assetVersion!==snapshot.assetVersion||this.session.sceneRevision!==snapshot.sceneRevision||this.session.regionVersion!==snapshot.regionVersion)throw new Error('等待期间作品或规则已改变，这份候选不会执行');
      this.subtitle=response.plan.shortMessage;
      const guide=response.plan.careGuide;
      this.careGuideText=guide?guide.howToUse:'';
      this.replySources=response.plan.explanationRefs.concat(guide?[guide.productId]:[])
        .filter((value:string,index:number,all:string[])=>all.indexOf(value)===index).slice(0,3);
      if(this.replySources.length)this.lastModelProductIds=this.replySources.slice();
      this.choices=response.plan.choices||[];
      this.replyQuestion=response.plan.question;this.replyQuestionKey=response.plan.shortMessage;
      this.dialogue.push({userText:input,reply:[response.plan.shortMessage,response.plan.question,this.careGuideText].filter((part:string)=>!!part).join(' ').slice(0,400),choices:this.choices.slice(),productIds:this.replySources.slice()});this.dialogue=this.dialogue.slice(-3);
      if(this.replySources.length>0&&ProductRepository.records().some((p:ProductRecord)=>p.productId===this.replySources[0]))this.showProduct(this.replySources[0]);
      if(response.plan.decision==='edit'){
        const op=response.plan.operations[0];
        const region=this.session.regions.find((r:RegionRecord)=>r.regionId===op.regionId);
        const plan=this.session.propose(region?.semantic==='confirmed-lips'?'lipTint':'localTint',op.regionId,op.presetId,PlannerClient.strength(op.intensityLevel));
        plan.targetLayerId=op.layerId;plan.removeLayer=op.operation==='remove_effect';plan.plannerSource='DeepSeek · '+response.modelEvidence.returnedModel;plan.snapshotId=snapshot.snapshotId;
        this.candidate=response.plan.shortMessage+(this.session.protection?' · 将保留已保护的范围':'');
        // A precise adjustment to an existing authorized layer needs no repeated confirmation.
        if(op.operation==='set_effect_level'&&op.layerId&&!this.session.protection&&/淡一点|浅一点|降低|深一点|浓一点/.test(input))this.applyCandidate();
      }
    }catch(e){if(generation!==this.cloudGeneration)return;console.warn('SELF_CLOUD_FAILED '+String(e));this.subtitle=this.tr('这次没能准备好建议，我们稍后再试。画面还好好地留着。');}
    finally{if(generation===this.cloudGeneration)this.cloudWaiting=false;}
  }
  private receive(m:Envelope):void{
    if(this.context.applicationInfo.debug)console.info('SELF_EVENT '+JSON.stringify(m));
    if(m.type==='INITIALIZED')this.loadSource().catch((e:Error)=>this.fail(e.message));
    if(m.type==='VIEW_CHANGED'&&m.payload.view){const v=m.payload.view;if([v.yaw,v.pitch,v.distance,v.panX,v.panY].every((n:number)=>Number.isFinite(n))){this.session.view=v;this.session.viewRevision++;}}
    if(m.type==='ASSET_REGISTERED'){this.session.width=m.payload.width||1024;this.session.height=m.payload.height||1024;this.previousSession=undefined;}
    if(m.type==='RENDER_SUCCEEDED'){
      if(this.session.succeeded(m.requestId,m.revision)){this.busy=false;this.subtitle=this.tr('这一点变化已经做好了，喜欢就留下。');this.labels();}
      if(m.requestId===this.restoreRequest){this.busy=false;this.ready=true;this.restoreRequest='';this.labels();if(this.restoreNotice){this.subtitle=this.restoreNotice;this.restoreNotice='';}}
    }
    if(m.type==='RENDER_FAILED'){
      if(this.previousSession){this.assets.discardTemporary(this.session.assetId);this.session=this.previousSession;this.previousSession=undefined;this.bridge.assetId=this.session.assetId;this.bridge.assetVersion=this.session.assetVersion;this.bridge.revision=this.session.revision;this.identity=this.session.sourceKind==='PHOTO'?'个人照片 · 本地处理':'示例面容';this.bridge.send('INIT',{});}
      this.session.failed();this.fail(m.payload.message||'未完成修改，保留上一有效作品');
    }
    if(m.type==='RESTORE_REQUEST')this.sendSnapshot();
  }
  private async loadSource():Promise<void>{
    this.dialogue=[];this.choices=[];this.uploadOffer=false;this.pendingCloudText='';
    this.lastModelProductIds=[];
    this.productOpen=false;this.replySources=[];this.careGuideText='';
    const bytes=await this.assets.read(this.session.assetId);this.bridge.sendBytes(this.session.sourceKind==='MESH'?'glb':bytes[0]===137?'photo/png':'photo/jpeg',bytes);
    for(const r of this.session.regions)this.bridge.sendBytes('mask:'+r.regionId,await this.assets.read(r.regionId));
    this.bridge.send('VIEW_SET',{view:this.session.view});this.setAtmosphere();
    this.sendSnapshot();
    if(this.context.applicationInfo.debug){this.bridge.send('ECHO',{text:'中文 "引号" \u0000 结束'});const p=new Uint8Array(65539);for(let i=0;i<p.length;i++)p[i]=i%256;this.bridge.sendBytes('echo',p);}
  }
  private sendSnapshot():void{
    if(!this.bridge.ready)return;this.bridge.revision=this.session.revision;
    const protection=this.session.protection;
    const request=this.session.pendingRequest||'restore-'+Date.now();if(!this.session.pending)this.restoreRequest=request;
    this.bridge.send('RENDER_AUTHORIZED_PLAN',{operations:this.session.pending?this.session.pending.operations:this.session.operations,protectionId:protection?.regionId,protectionRuleId:this.session.protectionKey(),animate:this.motion&&!!this.session.pending,anchorOperations:protection?.anchorOperations||[]},request);
  }
  private labels():void{
    this.applied=this.session.operations.length>0;
    this.bill=this.session.operations.map((o:EditOperation)=>this.tr(o.kind==='lipTint'?'唇色':'局部颜色')+' · '+this.tr(o.presetId==='rose'?'柔玫瑰':'暖陶棕')+' · '+Math.round(o.absoluteStrength*100)+'% · '+this.tr(o.plannerSource||'本地操作'));
    this.protectedLabel=this.session.protection?this.tr(this.session.protection.anchorOperations.length?'保护已确认的当前效果':'保护原始外观')+(this.session.protection.persistent?this.tr(' · 长期'):this.tr(' · 本次')):'';
  }
  private askModel(input:string,regionId:string=''):void{
    if(this.busy||this.cloudWaiting)return;
    this.productOpen=false;this.replySources=[];
    if(regionId&&regionId!==this.selected){this.selected=regionId;this.dialogue=[];this.choices=[];this.lastModelProductIds=[];}
    this.session.candidate=undefined;this.candidate='';this.pendingCloudText=input;this.lastUtterance=input;
    if(this.cloudSessionEnabled)this.requestCloud();
    else if(this.cloudConsentDecision==='unknown')this.uploadOffer=true;
    else{this.pendingCloudText='';this.subtitle=this.tr('云端对话已关闭。想继续时，可以在设置里开启。');}
  }
  private suggest(lip:boolean):void{
    const id=lip&&this.session.sourceKind==='MESH'?'lip':this.selected;
    if(!id){this.subtitle=this.tr('可以先轻轻圈出这里，再告诉我你的想法。');return;}
    this.askModel(lip?'我想在已确认的嘴唇范围尝试轻柔的唇色，请提出一个候选。':'我想看看圈出的这里有什么轻柔的变化。先问我一个简单的问题，不默认上色，不推荐产品。',id);
  }
  private applyCandidate(allowProtectedOnce:boolean=false):void{
    try{if(!this.session.candidate)return;this.session.authorize(this.session.candidate.planId,allowProtectedOnce);this.candidate='';this.busy=true;this.sendSnapshot();}catch(e){this.fail(String(e));}
  }
  private adjust(lighter:boolean):void{
    const last=this.session.operations[this.session.operations.length-1];
    if(!last){this.subtitle=this.tr('等你选好想尝试的变化，我们再慢慢调整。');return;}
    this.askModel(lighter?'请把最后一项已生效的颜色调淡一级，保持区域和预设不变。':'请为最后一项颜色提议另一个柔和预设，范围不变。',last.regionId);
  }
  private command():void{
    this.showBeginning=false;const input=this.text.trim();if(!input)return;this.getUIContext().getFocusController().clearFocus();this.productOpen=false;this.replySources=[];this.lastUtterance=input;const intent=PlannerService.plan(input);this.text='';
    const mood=this.followChat?AmbiencePreference.fromText(input):undefined;
    if(mood){this.palette=mood;this.setAtmosphere();if(this.musicOn)this.audio.configure(true,mood);}
    if(!['musicOn','musicOff','apply','undo','redo','reset','protect','preference','products','observe','cancel','urgentSupport'].includes(intent.action)){this.askModel(input);return;}
    if(intent.action==='urgentSupport'){this.session.candidate=undefined;this.candidate='';this.support='';this.subtitle=intent.text;this.open('求助支持');}
    else if(intent.action==='musicOn'){this.toggleMusic(true);this.subtitle=this.tr('留一点轻柔的声音陪你。随时可以关闭，也可以自己选一种氛围。');}
    else if(intent.action==='musicOff'){this.toggleMusic(false);this.subtitle=this.tr('音乐已关闭。按你舒服的方式来。');}
    else if(intent.action==='observe'){this.session.candidate=undefined;this.candidate='';this.subtitle=this.tr('可以转一转，看看不同角度的自己。保留现在的样子，也是完整的选择。');}
    else if(intent.action==='suggestLip')this.suggest(true);
    else if(intent.action==='apply'){if(this.session.candidate)this.applyCandidate();else this.askModel(input);}
    else if(intent.action==='lighter')this.adjust(true);
    else if(intent.action==='changeColor')this.adjust(false);
    else if(intent.action==='undo')this.undo(-1);
    else if(intent.action==='redo')this.undo(1);
    else if(intent.action==='reset')this.reset();
    else if(intent.action==='cancel'){this.lastModelProductIds=[];this.cloudGeneration++;this.planner.cancel();this.cloudWaiting=false;this.pendingCloudText='';this.session.candidate=undefined;this.candidate='';this.subtitle=intent.text;}
    else if(intent.action==='protect'||intent.action==='preference')this.open('保护');
    else if(intent.action==='products')this.askModel(input);
    else if(intent.action==='supportOffer'){this.support='offered';this.subtitle=intent.text;}
    else this.subtitle=mood?'收到。我们把节奏放轻一点，你可以先看看，也可以说说想尝试什么。':intent.text;
  }
  private pulseButton(name:string):void{
    if(this.pulseTimer>=0)clearTimeout(this.pulseTimer);
    this.buttonPulse=name;
    this.pulseTimer=setTimeout(()=>{this.buttonPulse='';this.pulseTimer=-1;},this.motion?210:0);
  }
  private toggleMusic(enabled:boolean):void{this.markInteraction();this.pulseButton('music');this.musicOn=enabled;this.audio.configure(enabled,this.palette);}
  private setAtmosphere():void{if(this.bridge.ready)this.bridge.send('SET_ATMOSPHERE',{motion:this.motion&&this.foreground,palette:this.palette});}
  private chooseAtmosphere(mode:string):void{this.getUIContext().animateTo({duration:this.motion?280:0},()=>this.palette=mode);this.setAtmosphere();this.saveUi();if(this.musicOn)this.audio.configure(true,mode);}
  private foregroundChanged():void{this.transfer?.setForeground(this.foreground);this.syncTransferIntent();this.bridge.foreground(this.foreground&&!this.cameraLive);this.audio.visibility(this.foreground);this.setAtmosphere();if(this.foreground&&this.reconstructionActive)this.pollReconstruction();if(!this.foreground&&this.timer>=0){clearInterval(this.timer);this.timer=-1;this.playing=false;}}
  private replyChanged():void{if(!this.motion)return;this.replyScale=.98;this.replyOpacity=.75;this.getUIContext().animateTo({duration:320,curve:Curve.EaseOut},()=>{this.replyScale=1;this.replyOpacity=1;});}
  private undo(direction:number):void{this.lastModelProductIds=[];this.productOpen=false;this.replySources=[];try{this.session.replay(direction);this.busy=true;this.sendSnapshot();}catch(e){this.fail(String(e));}}
  private reset():void{this.lastModelProductIds=[];this.productOpen=false;this.replySources=[];try{this.session.reset();this.busy=true;this.sendSnapshot();}catch(e){this.fail(String(e));}}
  private switchTool(next:string):void{if(this.busy||!this.legacyEditorOpen||!this.bridge.ready)return;this.showBeginning=false;this.tool=this.tool===next?'NAVIGATE':next;this.bridge.send('SET_TOOL',{tool:this.tool});}
  private showProduct(id:string=''):void{
    if(OlayDiscoveryRepository.allRecords().some((p:OlayDiscoveryItem)=>p.id===id)&&this.replySources.includes(id)){
      this.careLibraryProductId=id;this.careLibraryOpen=true;this.audio.setScene('care');return;
    }
    if(!id||!this.replySources.includes(id)){this.askModel('我想了解与我关注的问题相关的OLAY产品，请先询问我的具体需求，不要默认推荐产品或修改面容。');return;}
    if(this.detail)this.close();const found=ProductRepository.records().find((p:ProductRecord)=>p.productId===id);
    if(!found)return;this.productSelection=found;
    this.getUIContext().animateTo({duration:this.motion?300:0,curve:Curve.EaseOut},()=>{this.productOpen=true;});
  }
  private chooseProduct(direction:number):void{const all=ProductRepository.records().filter((p:ProductRecord)=>this.replySources.includes(p.productId));if(!all.length)return;const index=all.findIndex((p:ProductRecord)=>p.productId===this.productSelection.productId);this.productSelection=all[(index+direction+all.length)%all.length];}
  private open(name:string,event?:ClickEvent):void{
    if(name==='拍摄面容'&&this.reconstructionActive){this.openReconstructionProgress();return;}
    this.markInteraction();if(this.busy)return;if(name==='产品资料'){this.showProduct();return;}
    if(name==='拍摄面容'){this.cameraLive=true;this.showBeginning=false;if(this.legacyEditorOpen&&this.bridge.ready)this.bridge.send('SET_TOOL',{tool:'DETAIL'});this.bridge.foreground(false);this.audio.setScene('capture');return;}
    if(this.detail===name){this.close();this.pulseButton(name);return;}
    if(this.panelOpenTimer>=0&&this.buttonPulse===name){clearTimeout(this.panelOpenTimer);this.panelOpenTimer=-1;this.buttonPulse='';return;}
    if(!this.detail){
      if(event){this.anchorX=event.windowX;this.anchorY=event.windowY-this.surfaceTop;}
      else{this.anchorX=this.focusOpen?this.focusX*this.surfaceWidth:this.surfaceWidth-100;this.anchorY=this.focusOpen?this.focusY*this.surfaceHeight:16;}
    }
    if(!this.detail)this.previousTool=this.tool;
    if(this.panelOpenTimer>=0){clearTimeout(this.panelOpenTimer);this.panelOpenTimer=-1;}
    const reveal=():void=>{
      if(this.dustTimer>=0){clearInterval(this.dustTimer);this.dustTimer=-1;}
      this.panelDust=this.motion?0:1;
      this.getUIContext().animateTo({duration:this.motion?380:0,
        curve:this.motion?'spring(0,1,330,37)':Curve.EaseOut},()=>this.detail=name);
      if(this.motion){this.dustAge=0;this.dustTimer=setInterval(()=>{this.dustAge+=.033;this.panelDust=(this.panelDust+.012*(.58+.42*Math.exp(-this.dustAge/9)))%1;},33);}
    };
    if(!this.detail&&['氛围','设置','作品与记录','留一句话'].includes(name)&&this.motion){
      this.pulseButton(name);
      this.panelOpenTimer=setTimeout(()=>{this.panelOpenTimer=-1;reveal();},95);
    }else{reveal();}
    if(this.legacyEditorOpen&&this.bridge.ready)this.bridge.send('SET_TOOL',{tool:'DETAIL'});this.workItems=this.works.list();this.note=this.works.readNote();
    if(name==='采集记录'){this.selectedCapture='';this.captures=new CaptureService(this.context).list();}
  }
  private close():void{this.markInteraction();if(this.panelOpenTimer>=0){clearTimeout(this.panelOpenTimer);this.panelOpenTimer=-1;}if(this.dustTimer>=0){clearInterval(this.dustTimer);this.dustTimer=-1;}this.panelDust=1;this.buttonPulse='';this.cameraLive=false;this.bridge.foreground(this.foreground&&this.legacyEditorOpen);if(this.timer>=0)clearInterval(this.timer);this.timer=-1;this.playing=false;this.getUIContext().animateTo({duration:this.motion?260:0,curve:Curve.EaseInOut},()=>this.detail='');this.tool=this.previousTool;if(this.legacyEditorOpen&&this.bridge.ready)this.bridge.send('SET_TOOL',{tool:this.tool});this.audio.setScene(this.skyOpen?'sky':this.personalActive()?'personal':this.journey==='forming'?'forming':'origin');}
  private protect(current:boolean,persistent:boolean):void{
    try{this.session.protect(this.selected,current,persistent);this.sendSnapshot();this.labels();this.close();
      if(persistent)this.works.savePreference(this.session).then(()=>{this.subtitle=this.tr('已明确保存长期偏好');this.labels();}).catch((e:Error)=>this.fail(e.message));
      else this.subtitle=current?'仅本次保留这里当前的效果':'仅本次保留这里原始的样子';
    }catch(e){this.fail(String(e));}
  }
  private async recordCapture():Promise<void>{
    try{this.captureStatus=this.tr('正在打开系统相机…');const capture=await new CaptureService(this.context).record();this.captures=new CaptureService(this.context).list();this.captureStatus=capture?'视频已私密保存。尚未生成个人3D模型，原作品保持不变。':'已取消拍摄，没有更换当前作品。';}
    catch(e){this.captureStatus=this.tr('相机暂未完成：')+(e as Error).message;}
  }
  private async checkReconstruction():Promise<void>{
    try{this.captureStatus=await this.bridge.reconstructionSupport();}catch(e){this.captureStatus=this.tr('设备能力检查失败：')+String(e);}
  }
  private async importPhoto():Promise<void>{
    try{const photo=await this.assets.pickPhoto();if(!photo){this.subtitle=this.tr('已取消导入，当前作品不变');return;}
      const s=new SessionStore();s.assetId=photo.id;s.assetVersion=photo.id+'-v1';s.sourceKind='PHOTO';s.sourceFile=photo.path;s.textureVersion=s.assetVersion;
      this.previousSession=this.session;this.session=s;this.bridge.assetId=s.assetId;this.bridge.assetVersion=s.assetVersion;this.bridge.revision=0;this.ready=false;this.busy=true;this.selected='';this.candidate='';this.identity='个人照片 · 本地处理';this.legacyEditorOpen=true;this.close();this.labels();if(this.bridge.ready)this.bridge.send('INIT',{});this.subtitle=this.tr('原图保留；先圈选，再试局部颜色');
    }catch(e){this.fail(String(e));}
  }
  private async saveWork():Promise<void>{try{this.session.view=await this.bridge.currentView();const item=await this.works.save(this.session);this.workItems=this.works.list();this.subtitle=this.tr('作品已保存，可从记录重开或删除');console.info('SELF_WORK_SAVED '+item.id);}catch(e){this.fail(String(e));}}
  private reopen(id:string):void{
    try{const saved=this.works.open(id);const restored=new SessionStore();restored.restore(saved);if(restored.protection?.persistent)restored.protection=undefined;this.works.loadPreference(restored);this.session=restored;this.identity=saved.sourceKind==='PHOTO'?'个人照片 · 本地处理':'示例面容';this.selected='';this.candidate='';this.bridge.assetId=saved.assetId;this.bridge.assetVersion=saved.assetVersion;this.bridge.revision=this.session.revision;this.legacyEditorOpen=true;this.close();this.restoreNotice=saved.renderPipelineVersion?'已恢复保存的作品与视角':'已保留旧作品文件，并按原操作重算；新旧引擎像素一致性尚未逐作品验证。另存会创建新作品。';if(this.bridge.ready)this.bridge.send('INIT',{});this.labels();this.subtitle=this.tr('正在恢复已保存作品');}catch(e){this.fail(String(e));}
  }
  private animate():void{if(this.timer>=0){clearInterval(this.timer);this.timer=-1;this.playing=false;return;}this.playing=true;this.animationValue=0;this.timer=setInterval(()=>{this.animationValue=(this.animationValue+2)%101;},50);}
  private exportPNG():void{if(!this.busy){this.busy=true;this.bridge.send('EXPORT_REQUEST',{width:768,height:1024});}}
  private deleteFace():void{
    try{this.works.deletePersonalAsset(this.session.assetId);this.session=new SessionStore();
      for(const name of ['lip','editable','protectionTest'])this.session.regions.push({regionId:name,assetId:this.session.assetId,assetVersion:this.session.assetVersion,width:1024,height:1024,semantic:name==='lip'?'confirmed-lips':'manual',fileName:name+'.mask'});
      this.works.loadPreference(this.session);this.bridge.assetId=this.session.assetId;this.bridge.assetVersion=this.session.assetVersion;this.bridge.revision=0;this.identity='示例面容';this.selected='';this.candidate='';this.ready=false;this.close();this.labels();this.bridge.send('INIT',{});this.subtitle=this.tr('已删除这张照片的应用内源文件、作品、蒙版和私有导出；私密文字保留');
    }catch(e){this.fail(String(e));}
  }
  aboutToDisappear():void{this.transferPageActive=false;this.syncTransferIntent();if(this.transfer){this.transfer.coordinator.onChanged=()=>{};this.transfer.coordinator.onImported=()=>{};}this.context.getApplicationContext().eventHub.off('selfTransferNotice',this.transferNotice);this.resetGalaxyRise();this.clearGalaxyCaption();this.clearSkyTimers();this.planner.cancel();if(this.timer>=0)clearInterval(this.timer);if(this.storyCueTimer>=0)clearTimeout(this.storyCueTimer);if(this.characterTimer>=0)clearTimeout(this.characterTimer);if(this.formationTimer>=0)clearInterval(this.formationTimer);if(this.introCharacterTimer>=0)clearTimeout(this.introCharacterTimer);if(this.revealTimer>=0)clearTimeout(this.revealTimer);if(this.panelOpenTimer>=0)clearTimeout(this.panelOpenTimer);if(this.pulseTimer>=0)clearTimeout(this.pulseTimer);if(this.dustTimer>=0)clearInterval(this.dustTimer);this.introTimers.forEach((timer:number)=>clearTimeout(timer));if(this.reconTimer>=0)clearInterval(this.reconTimer);this.reconTimer=-1;this.audio.dispose();this.bridge.dispose();this.assets.cleanupTemporary();}
  onBackPress():boolean{if(this.journey==='forming'){this.minimizeReconstruction();return true;}if(this.galaxyTravelId){this.recoverGalaxy();return true;}if(this.introStage>0){this.finishIntro();return true;}if(this.cameraLive){this.close();return true;}if(this.detail){this.close();return true;}if(this.skyMounted||this.skyOpen||this.personalActive()){this.returnOrigin();return true;}if(this.productOpen){this.productOpen=false;return true;}if(this.legacyEditorOpen){this.legacyEditorOpen=false;this.ready=false;return true;}if(this.tool!=='NAVIGATE'){this.switchTool(this.tool);return true;}return false;}
  @Builder ambienceTile(mode:string,label:string,color:string){
    Button(){Column({space:8}){Stack(){Circle().width(48).height(48).fill(color);Circle().width(26).height(26).fill('#BBFFFFFF').blur(7).offset({x:8,y:-4})}.width(62).height(60);Text(this.tr(label)).fontSize(13).fontColor('#3B4665')}}.id('palette-'+mode).layoutWeight(1).height(102).backgroundColor(this.palette===mode?'#B9E1EAF8':'#72D1DDEF').border({width:this.palette===mode?1.5:1,color:this.palette===mode?'#CDEBFA':'#88E5F0FF'}).borderRadius(22).stateStyles({pressed:{.scale({x:.96,y:.96})},normal:{.scale({x:1,y:1})}}).animation({duration:this.motion?180:0,curve:Curve.EaseOut}).onClick(()=>this.chooseAtmosphere(mode))
  }
  @Builder settingsEntry(id:string,icon:string,label:string,action:(event:ClickEvent)=>void){
    Button(){
      Row({space:12}){
        Row(){Image($rawfile('ui/'+icon)).width(19).height(19)}
          .width(32).height(32).borderRadius(11).backgroundColor('#4E6E96')
          .justifyContent(FlexAlign.Center)
        Text(this.tr(label)).fontSize(15).fontColor('#E6EEF7').fontWeight(FontWeight.Medium).layoutWeight(1)
        Text('›').fontSize(17).fontColor('#7E93AD')
      }.width('100%').padding({left:12,right:12})
    }.id(id).height(48).backgroundColor('#27374E').border({width:1,color:'#3C5170'}).borderRadius(16)
      .shadow({radius:8,color:'#00000040',offsetY:3})
      .stateStyles({pressed:{.scale({x:.97,y:.95})},normal:{.scale({x:1,y:1})}})
      .animation({duration:this.motion?170:0,curve:Curve.EaseOut})
      .onClick(action)
  }
  @Builder aboutFeature(textKey:string){
    Row({space:10}){
      Text('✦').fontSize(11).fontColor('#7E93AD').margin({top:2})
      Text(this.tr(textKey)).fontSize(13).fontColor('#C6D4E4').lineHeight(20).layoutWeight(1)
    }.width('100%')
  }
  @Builder
  details(){
    Scroll(){Column({space:12}){
      Row(){
        if(this.detailParent()){
          Button(){Text('‹').fontSize(19).fontWeight(FontWeight.Medium).fontColor(this.panelDark()?'#C6D4E4':'#425E89')}
            .width(28).height(28).padding(0).borderRadius(14)
            .backgroundColor(this.panelDark()?'#27374E':'#35557424')
            .border({width:1,color:this.panelDark()?'#3C5170':'#00000000'})
            .stateStyles({pressed:{.scale({x:.88,y:.88})},normal:{.scale({x:1,y:1})}})
            .animation({duration:this.motion?170:0,curve:Curve.EaseOut})
            .accessibilityText(this.tr('返回'))
            .onClick(()=>{this.detail=this.detailParent()})
        }
        Text(this.detail==='作品与记录'?(this.tr('足迹')):this.tr(this.detail))
          .fontSize(16).fontWeight(FontWeight.Medium).fontColor(this.panelDark()?'#E6EEF7':'#263951').layoutWeight(1).textAlign(TextAlign.Center)
        Button(){
          Stack(){
            Rect().width(11).height(1.6).fill(this.panelDark()?'#C6D4E4':'#425E89').rotate({angle:45})
            Rect().width(11).height(1.6).fill(this.panelDark()?'#C6D4E4':'#425E89').rotate({angle:-45})
          }.width(26).height(26)
        }.width(26).height(26).borderRadius(13)
          .backgroundColor(this.panelDark()?'#27374E':'#35557424')
          .border({width:1,color:this.panelDark()?'#3C5170':'#00000000'})
          .stateStyles({pressed:{.scale({x:.88,y:.88})},normal:{.scale({x:1,y:1})}})
          .animation({duration:this.motion?170:0,curve:Curve.EaseOut})
          .accessibilityText(this.tr('关闭'))
          .onClick(()=>this.close())
      }.width('100%').height(34)
      Rect().width('100%').height(1).fill(this.panelDark()?'#FFFFFF':'#768FAF').opacity(this.panelDark()?.14:.42)
      if(this.detail==='完整回复'){Text(this.tr(this.subtitle)).fontSize(17).lineHeight(28)}
      if(this.detail==='云端理解'){
        Text(CloudConsentStore.introduction(this.language)).fontSize(16).fontColor('#C6D4E4')
        Text(this.tr('服务端不保留面容画面；第三方的处理与留存依其条款。')).fontSize(14).fontColor('#8FA3BC')
        Toggle({type:ToggleType.Switch,isOn:this.cloudSessionEnabled}).id('cloud-session-toggle').onChange((v:boolean)=>{
          if(this.setCloudConsent(v)&&v&&this.pendingCloudText)this.requestCloud();})
        TextInput({text:this.backendAddress,placeholder:this.tr('自己的后端地址')}).backgroundColor('#27374E').fontColor('#E6EEF7').placeholderColor('#7E93AD').onChange((v:string)=>this.backendAddress=v)
        TextInput({text:this.backendToken,placeholder:this.tr('后端访问口令（不是 DeepSeek 密钥）')}).type(InputType.Password).backgroundColor('#27374E').fontColor('#E6EEF7').placeholderColor('#7E93AD').onChange((v:string)=>this.backendToken=v)
      }
      if(this.detail==='氛围'){
        Row({space:10}){
          this.ambienceTile('quiet','微光','#CCC3E2')
          this.ambienceTile('warm','暖阳','#EECDB2')
          this.ambienceTile('clear','清透','#BEDFD8')
        }.width('100%')
        Text(this.tr('强调色')).fontSize(13).fontColor('#84728F').margin({top:8})
        Row({space:16}){ForEach(['#7C698F','#A5697C','#487F80','#947347'],(color:string)=>{
          Button(){Circle().width(30).height(30).fill(color);}.id('accent-'+color.substring(1)).width(48).height(48).backgroundColor(this.accent===color?'#ECFFFFFF':'#20FFFFFF').border({width:this.accent===color?2:0,color:color}).borderRadius(24).animation({duration:this.motion?220:0,curve:Curve.EaseOut}).accessibilityText(this.tr(color==='#7C698F'?'雾紫':color==='#A5697C'?'玫瑰':color==='#487F80'?'青绿':'琥珀')).onClick(()=>this.setAccent(color))
        },(color:string)=>color)}
        Row(){Text(this.tr('♫  舒缓音乐')).layoutWeight(1);Toggle({type:ToggleType.Switch,isOn:this.musicOn}).selectedColor(this.accent).onChange((v:boolean)=>this.toggleMusic(v))}.height(48)
        Row(){Text(this.tr('✧  柔和运动')).layoutWeight(1);Toggle({type:ToggleType.Switch,isOn:this.motion}).id('ambience-motion').selectedColor(this.accent).onChange((v:boolean)=>{this.motion=v;this.setAtmosphere();this.saveUi();})}.height(48)
        Row(){Text(this.tr('随对话调整')).layoutWeight(1);Toggle({type:ToggleType.Switch,isOn:this.followChat}).id('follow-chat').selectedColor(this.accent).onChange((v:boolean)=>{this.followChat=v;this.saveUi();})}.height(48)
        if(this.legacyEditorOpen&&this.bridge.ready&&this.session.sourceKind==='MESH'){Button(this.tr('缓慢转动人像')).softButton().onClick(()=>{this.close();this.bridge.send('VIEW_ORBIT',{});})}
      }
      if(this.detail==='设置'){
        Text(this.tr('语言 / Language')).fontSize(12).letterSpacing(2).fontColor('#7E93AD').fontWeight(FontWeight.Medium)
        Column({space:10}){
          Row({space:10}){
            Button(this.tr('中文')).id('language-zh').layoutWeight(1).height(44).fontSize(14).fontColor(this.language==='zh'?'#FFFFFF':'#C6D4E4')
              .backgroundColor(this.language==='zh'?'#4E6E96':'#27374E').border({width:1,color:this.language==='zh'?'#6E8CB4':'#3C5170'}).borderRadius(22)
              .stateStyles({pressed:{.opacity(.75).scale({x:.96,y:.96})},normal:{.opacity(1).scale({x:1,y:1})}})
              .animation({duration:150,curve:Curve.EaseOut})
              .onClick(()=>this.setLanguage('zh'))
            Button('English').id('language-en').layoutWeight(1).height(44).fontSize(14).fontColor(this.language==='en'?'#FFFFFF':'#C6D4E4')
              .backgroundColor(this.language==='en'?'#4E6E96':'#27374E').border({width:1,color:this.language==='en'?'#6E8CB4':'#3C5170'}).borderRadius(22)
              .stateStyles({pressed:{.opacity(.75).scale({x:.96,y:.96})},normal:{.opacity(1).scale({x:1,y:1})}})
              .animation({duration:150,curve:Curve.EaseOut})
              .onClick(()=>this.setLanguage('en'))
          }.width('100%')
          Row({space:10}){
            Button(this.tr('日本語')).id('language-ja').layoutWeight(1).height(44).fontSize(14).fontColor(this.language==='ja'?'#FFFFFF':'#C6D4E4')
              .backgroundColor(this.language==='ja'?'#4E6E96':'#27374E').border({width:1,color:this.language==='ja'?'#6E8CB4':'#3C5170'}).borderRadius(22)
              .stateStyles({pressed:{.opacity(.75).scale({x:.96,y:.96})},normal:{.opacity(1).scale({x:1,y:1})}})
              .animation({duration:150,curve:Curve.EaseOut})
              .onClick(()=>this.setLanguage('ja'))
            Button('한국어').id('language-ko').layoutWeight(1).height(44).fontSize(14).fontColor(this.language==='ko'?'#FFFFFF':'#C6D4E4')
              .backgroundColor(this.language==='ko'?'#4E6E96':'#27374E').border({width:1,color:this.language==='ko'?'#6E8CB4':'#3C5170'}).borderRadius(22)
              .stateStyles({pressed:{.opacity(.75).scale({x:.96,y:.96})},normal:{.opacity(1).scale({x:1,y:1})}})
              .animation({duration:150,curve:Curve.EaseOut})
              .onClick(()=>this.setLanguage('ko'))
          }.width('100%')
        }.width('100%')
        Row(){Text(this.tr('使用手写笔')).fontSize(15).fontColor('#E6EEF7').layoutWeight(1);Toggle({type:ToggleType.Switch,isOn:this.stylusHints}).id('stylus-hints-toggle').selectedColor(this.accent).onChange((value:boolean)=>{this.stylusHints=value;this.saveUi();})}.height(44)
        Text(this.tr('可用手写笔或触控在个人立体面容上圈选；先从小范围开始。')).fontSize(12).fontColor('#7E93AD')
        this.settingsEntry('replay-intro','star_light.svg','重温最初的微光',()=>{this.close();this.returnOrigin();this.startIntro(true);})
        this.settingsEntry('open-cloud','cloud_lock_light.svg','隐私与云端',(event:ClickEvent)=>this.open('云端理解',event))
        this.settingsEntry('open-captures','camera_light.svg','采集记录',(event:ClickEvent)=>this.open('采集记录',event))
          if(this.transferEnabled){
            if(this.personalActive()&&(this.transferPhase==='SEND_READY'||this.transferReceiving)){
              this.settingsEntry('transfer-receive','star_light.svg',this.transferReceiving?'取消接收':'接收模型',()=>{
                this.transfer?.coordinator.forceReceive(!this.transferReceiving);this.close();
              })
            }
            if(this.transferPhase==='RECEIVE_READY'){
              this.settingsEntry('transfer-import','star_light.svg','导入模型文件',()=>{this.close();this.transfer?.pickPackage();})
            }
            if(this.transferPhase==='ERROR'){
              this.settingsEntry('transfer-retry','star_light.svg','重试模型交接',()=>{this.transfer?.coordinator.retry();this.close();})
            }
          }
        this.settingsEntry('open-about','info_light.svg','关于 SELF',(event:ClickEvent)=>this.open('关于 SELF',event))
      }
      if(this.detail==='关于 SELF'){
        Column({space:0}){
          Stack(){Image($rawfile('ui/star_light.svg')).width(40).height(40)}
            .width(80).height(80).borderRadius(22).backgroundColor('#3D5A7E')
            .shadow({radius:18,color:'#4E6E9680',offsetY:6})
          Text('SELF').fontSize(22).letterSpacing(8).fontWeight(FontWeight.Bold).fontColor('#EAF1F8').margin({top:14})
          Text('v0.1.0 · API 26').fontSize(12).fontColor('#8FA3BC').margin({top:4})
          Rect().width('100%').height(1).fill('#FFFFFF').opacity(.16).margin({top:18,bottom:18})
          Text(this.tr('每一种样子，都值得被看见')).fontSize(17).fontColor(this.accent).fontWeight(FontWeight.Medium)
          Text(this.tr('不抹去你的特点。保留现在，或尝试一点不同，都由你决定。')).fontSize(13).fontColor('#A9BCD2').lineHeight(21).textAlign(TextAlign.Center)
          Column({space:10}).margin({top:16}).width('100%'){
            this.aboutFeature('关于·拍摄')
            this.aboutFeature('关于·圈选')
            this.aboutFeature('关于·私密')
          }
          Text(this.tr('循光，遇见自己')).fontSize(11).letterSpacing(4).fontColor('#7E93AD').margin({top:20})
        }.width('100%')
      }
      if(this.detail==='采集记录'){
        if(this.selectedCapture){Video({src:fileUri.getUriFromPath(this.context.filesDir+'/captures/'+this.selectedCapture)}).id('capture-playback').onStart(()=>console.info('SELF_CAPTURE_PLAYBACK_STARTED')).onError(()=>console.info('SELF_CAPTURE_PLAYBACK_ERROR')).width('100%').height(210).autoPlay(true).controls(true).objectFit(ImageFit.Contain).borderRadius(16)}
        if(this.captureStatus){Text(this.tr(this.captureStatus)).fontSize(14).fontColor('#9AB2CC')}
        if(this.captures.length===0){
          Column({space:6}){
            Text('✧').fontSize(22).fontColor('#8FA9C9')
            Text(this.tr('还没有采集的原片。')).fontSize(14).fontColor('#8FA9C9')
          }.width('100%').padding({top:26,bottom:26})
        }
        ForEach(this.captures,(clip:CaptureRecord)=>{
          Row({space:8}){
            Text(this.captureTime(clip.name)).fontSize(14).fontColor('#2E4460').fontWeight(FontWeight.Medium).layoutWeight(1)
            Button(this.tr('预览')).id('play-'+clip.name).fontSize(12).fontColor('#3D5A7C')
              .height(32).padding({left:12,right:12}).backgroundColor('#C4EAF5F8')
              .border({width:1,color:'#93DEF0FF'}).borderRadius(16)
              .stateStyles({pressed:{.scale({x:.93,y:.93})},normal:{.scale({x:1,y:1})}})
              .animation({duration:150,curve:Curve.EaseOut})
              .accessibilityText(this.tr('播放视频'))
              .onClick(()=>this.selectedCapture=clip.name)
            Button(this.reconJob||this.reconSubmitting?this.tr('正在寻找中'):this.tr('建模')).id('model-'+clip.name).fontSize(12).fontColor('#3D5A7C')
              .height(32).padding({left:12,right:12}).backgroundColor('#C4EAF5F8')
              .border({width:1,color:'#93DEF0FF'}).borderRadius(16)
              .stateStyles({pressed:{.scale({x:.93,y:.93})},normal:{.scale({x:1,y:1})}})
              .animation({duration:150,curve:Curve.EaseOut})
              .enabled(!this.reconJob&&!this.reconSubmitting)
              .onClick(()=>this.submitCapture(clip.name))
            Button(this.tr('删除')).id('delete-'+clip.name).fontSize(12).fontColor('#8A4A56')
              .height(32).padding({left:12,right:12}).backgroundColor('#F2D9DEF8')
              .border({width:1,color:'#EBC4CDFF'}).borderRadius(16)
              .stateStyles({pressed:{.scale({x:.93,y:.93})},normal:{.scale({x:1,y:1})}})
              .animation({duration:150,curve:Curve.EaseOut})
              .onClick(()=>{if(this.selectedCapture===clip.name)this.selectedCapture='';new CaptureService(this.context).delete(clip.name);this.captures=new CaptureService(this.context).list();})
          }.padding({left:14,right:10,top:6,bottom:6}).width('100%').backgroundColor('#B8FFFFFF').borderRadius(16)
        },(clip:CaptureRecord)=>clip.name)
      }
      if(this.detail==='工具'){
        Button(this.tr('拍摄面容视频')).softButton().onClick(()=>{this.open('拍摄面容');})
        Button(this.tr('选择一张照片')).softButton().onClick(()=>this.importPhoto())
        Button(this.tr('保存当前画面 PNG')).softButton().onClick(()=>{this.close();this.exportPNG();})
        if(this.session.sourceKind==='PHOTO'){Button(this.tr('删除这份个人面容')).softButton().onClick(()=>this.detail='删除个人面容')}
        if(this.session.sourceKind==='MESH'){Button(this.tr('让模型规划唇色')).softButton().onClick(()=>{this.close();this.suggest(true);})}
        if(this.session.sourceKind==='PHOTO'){
          Text(this.tr('照片唇区需自己精细圈出，只包括嘴唇，避开口腔、牙齿与皮肤；可以重圈再确认。')).fontSize(14)
          Button(this.tr('确认这块只含嘴唇')).softButton().enabled(this.selected.length>0).onClick(()=>{const region=this.session.regions.find((r:RegionRecord)=>r.regionId===this.selected);if(region){region.semantic='confirmed-lips';this.session.regionVersion++;this.session.sceneRevision++;this.session.candidate=undefined;this.candidate='';this.close();this.subtitle=this.tr('已记录手工确认的唇区，可从工具试唇色。');}})
          Button(this.tr('让模型规划唇色')).softButton().enabled(this.selected.length>0).onClick(()=>{this.close();this.suggest(true);})
        }
        Button(this.tr('让模型规划这里')).softButton().enabled(this.selected.length>0).onClick(()=>{this.close();this.suggest(false);})
        Button(this.tr('这里别动')).softButton().enabled(this.selected.length>0).onClick(()=>this.detail='保护')
        Button(this.tr('颜色淡一点')).softButton().enabled(this.applied).onClick(()=>{this.close();this.adjust(true);})
        Button(this.tr('换一种颜色')).softButton().enabled(this.applied).onClick(()=>{this.close();this.adjust(false);})
        Button(this.tr('重做')).softButton().onClick(()=>{this.close();this.undo(1);})
        Button(this.tr('回到原始')).softButton().onClick(()=>{this.close();this.reset();})
        Button(this.tr('作品与记录')).softButton().onClick(()=>this.detail='作品与记录')
        Button(this.tr('产品资料')).softButton().onClick(()=>this.showProduct())
      }
      if(this.detail==='保护'){
        Text(this.tr(this.protectedLabel||'默认只对本次生效。保留原貌与保留当前效果是不同选择。')).fontSize(16)
        if(!this.protectedLabel){
          Button(this.tr('本次保留原貌')).softButton().enabled(this.selected.length>0).onClick(()=>this.protect(false,false))
          Button(this.tr('本次保留当前效果')).softButton().enabled(this.selected.length>0).onClick(()=>this.protect(true,false))
          Button(this.tr('以后也保留原貌')).softButton().enabled(this.selected.length>0&&this.session.sourceKind==='MESH').onClick(()=>this.protect(false,true))
        }else{Button(this.tr('明确移除这处保护')).softButton().onClick(()=>{if(this.session.protection?.persistent)this.works.deletePreference();this.session.protection=undefined;this.session.sceneRevision++;this.sendSnapshot();this.labels();this.subtitle=this.tr('已按你的选择移除保护');})}
        Text(this.tr('本版一次支持一处保护范围。当前效果的保护与作品一起保存。')).fontSize(14)
      }
      if(this.detail==='作品与记录'){
        if(this.legacyEditorOpen&&this.bridge.ready){Button(this.tr('保存当前作品')).softButton().onClick(()=>this.saveWork())}
        if(this.personalGaussianPath&&!this.legacyEditorOpen){Text(this.tr('这颗星辰仍在这里，随时可以回来看看。')).fontSize(15).fontColor('#3A4E6B')}
        if(this.legacyEditorOpen){Text(this.tr('实际成功的操作')).fontSize(17)}
        if(this.workItems.length===0&&this.bill.length===0&&this.note.length===0){
          Text('✧').fontSize(26).fontColor('#4D668D').margin({top:18})
          Text(this.tr('第一段足迹，会从你愿意留下的瞬间开始。'))
            .fontSize(16).lineHeight(24).fontColor('#324766')
        }
        ForEach(this.bill,(line:string)=>{Text(this.tr(line)).fontSize(15).width('100%')})
        ForEach(this.workItems,(item:WorkItem)=>{Row({space:8}){Button(this.tr(item.label)).id('open-'+item.id).softButton().onClick(()=>this.reopen(item.id));Button(this.tr('删除作品')).id('delete-'+item.id).softButton().onClick(()=>{this.works.delete(item.id);this.workItems=this.works.list();this.subtitle=this.tr('已删除该作品的私有文件与记录');})}},(item:WorkItem)=>item.id)
        if(this.note.length>0){Text(this.tr(this.note)).fontSize(16);Button(this.tr('修改那句话')).softButton().onClick(()=>this.detail='留一句话');Button(this.tr('删除那句话')).softButton().onClick(()=>{this.works.deleteNote();this.note='';})}
      }
      if(this.detail==='删除个人面容'){
        Text(this.tr('删除这张照片在 SELF 中的源文件、关联作品、蒙版、临时数据和当前私有导出。你另存到外部的文件不受影响。私密文字单独管理。')).fontSize(16)
        Button(this.tr('确认删除这份面容')).softButton().onClick(()=>this.deleteFace())
      }
      if(this.detail==='求助支持'){
        Text(this.tr(this.subtitle)).fontSize(18)
        Text(this.tr('也可以联系医生、心理健康专业人员或身边可信任的人。此处不提供诊断或治疗。')).fontSize(16)
        Text(this.tr('参考：WHO Suicide Q&A\nhttps://www.who.int/news-room/questions-and-answers/item/suicide')).fontSize(12).copyOption(CopyOptions.LocalDevice)
      }
      if(this.detail==='留一句话'){
        Text(this.tr('写给此刻的自己。只有你确认后，这句话才会留下。')).fontSize(15).fontColor('#354B68')
        TextArea({text:this.note,placeholder:this.tr('写给自己的话')}).height(156).maxLength(2000)
          .backgroundColor('#B5D9E3F0').border({width:1,color:'#84F3F7FF'}).borderRadius(18)
          .onChange((v:string)=>this.note=v)
        Row({space:12}){
          Button(this.tr('留下这句话')).layoutWeight(1).height(48).fontSize(15).fontColor('#F2F7FF')
            .backgroundColor('#D23B5879').border({width:1,color:'#83C9DCEB'}).borderRadius(20)
            .stateStyles({pressed:{.scale({x:.97,y:.94})},normal:{.scale({x:1,y:1})}})
            .animation({duration:this.motion?180:0,curve:Curve.EaseOut})
            .onClick(()=>{this.works.saveNote(this.note);this.close();this.subtitle=this.tr('已私密保存，可在记录中修改或删除');})
          Button(this.tr('稍后再说')).layoutWeight(1).height(48).fontSize(15).fontColor('#30445F')
            .backgroundColor('#8BE8EFF8').border({width:1,color:'#92FFFFFF'}).borderRadius(20)
            .stateStyles({pressed:{.scale({x:.97,y:.94})},normal:{.scale({x:1,y:1})}})
            .animation({duration:this.motion?180:0,curve:Curve.EaseOut})
            .onClick(()=>this.close())
        }.width('100%')
        Text(this.tr('私密留在本机 · 可在足迹中改写或删除。'))
          .fontSize(12).fontColor('#4B5F79')
      }
    }.padding(22).width('100%').alignItems(HorizontalAlign.Start)}.align(Alignment.TopStart).width('100%').height('100%')
      .scrollBar(BarState.Off)
      .edgeEffect(EdgeEffect.Spring)
      .backgroundColor(this.panelDark()?'#E01B2536':(this.panelFromTop()?'#D0A6B7D2':'#CCAFA9C7'))
      .backgroundBlurStyle(BlurStyle.COMPONENT_ULTRA_THIN,{colorMode:this.panelDark()?ThemeColorMode.DARK:ThemeColorMode.LIGHT})
      .linearGradient({angle:150,colors:this.panelDark()?
        [['#202C3FEB',0],['#182233EB',.55],['#1E2A3DEB',1]]:
        (this.panelFromTop()?
        [['#C7B7C9E1',0],['#C0A5B8D5',.58],['#C8BAC9E0',1]]:
        [['#C9C0B9D8',0],['#C2B3AACE',.56],['#C8CABDE1',1]])})
      .border({width:1,color:this.panelDark()?'#4E6486':(this.panelFromTop()?'#A0DFEAF7':'#A5E6DDF5')})
      .shadow({radius:22,color:'#61405477',offsetY:10}).borderRadius(this.panelFromTop()?28:32)
  }
  @Builder
  panelCard(){
    Stack(){
      this.details()
      ForEach(this.sparks.slice(0,32),(index:number)=>{
        Circle().width(index%5===0?4.5:3).height(index%5===0?4.5:3)
          .fill(index%3===0?'#F5F6FF':this.panelFromTop()?'#C7E4F8':'#E8D9F8')
          .opacity(this.dustOpacity(index))
          .position({x:index%2===0?10+(index%4)*4:this.panelWidth()-16-(index%4)*4,y:this.dustY(index)})
          .hitTestBehavior(HitTestMode.None)
      },(index:number)=>index.toString())
    }.width('100%').height('100%').clip(true).borderRadius(this.panelFromTop()?28:32)
  }
  @Builder
  conversation(){
    Column({space:10}){
      Row(){Text(this.tr(this.focusOpen?'从这里开始':'✧  SELF 陪你')).fontSize(13).fontColor('#89759C');Blank();Text(this.tr(this.cloudWaiting?'正在理解':this.cloudSessionEnabled?'云端已开启':'隐私设置')).fontSize(11).fontColor('#95879F').onClick((event:ClickEvent)=>this.open('云端理解',event))}.width('100%')
      if(this.uploadOffer){
        Text(CloudConsentStore.introduction(this.language)).fontSize(12).fontColor('#756380')
        Row({space:8}){Button(this.tr('开启对话')).id('cloud-enable-send').softButton().layoutWeight(1).onClick(()=>{
          if(this.setCloudConsent(true))this.requestCloud();});
          Button(this.tr('现在先不用')).softButton().onClick(()=>{
            if(this.setCloudConsent(false))this.subtitle=this.tr('好，画面留在这里。');})}
      }
      if(this.lastUtterance&&(!this.productOpen||this.wide)){Text(this.tr('你说 · '+this.lastUtterance)).fontSize(12).fontColor('#8E819A').maxLines(2).width('100%')}
      Text(this.tr(this.subtitle)).fontSize(15).lineHeight(23).fontColor('#52465F').maxLines(this.productOpen?2:this.wide?5:3).width('100%')
      if(this.careGuideText){Text(this.careGuideText).fontSize(13).lineHeight(20).fontColor('#685571').width('100%')}
      if(this.replyQuestion&&this.replyQuestionKey===this.subtitle){Text(this.tr(this.replyQuestion)).fontSize(15).lineHeight(23).fontColor('#685571').width('100%')}
      if(this.choices.length>0&&!this.cloudWaiting&&!this.uploadOffer){Flex({wrap:FlexWrap.Wrap}){ForEach(this.choices,(choice:string,index:number)=>{Button(this.tr((index+1)+' · '+choice)).softButton().fontSize(13).margin(3).onClick(()=>this.askModel(choice))},(choice:string)=>choice)}}
      if(this.subtitle.length>70){Button(this.tr('完整回复')).softButton().height(this.productOpen?30:48).fontSize(12).onClick((event:ClickEvent)=>this.open('完整回复',event))}
      if(this.replySources.length>0&&!this.productOpen){Button(this.tr('看看这款')).softButton().fontSize(12).onClick(()=>this.showProduct(this.replySources[0]))}
      if(this.focusOpen&&!this.candidate&&!this.cloudWaiting){
        Flex({wrap:FlexWrap.Wrap}){
          Button(this.tr('想试一点变化')).softButton().fontSize(13).margin(3).onClick(()=>this.suggest(false))
          Button(this.tr('就这样也好')).softButton().fontSize(13).margin(3).onClick((event:ClickEvent)=>this.open('保护',event))
          Button(this.tr('说说这里')).softButton().fontSize(13).margin(3).onClick(()=>this.askModel('请和我聊聊圈出的这里，先不要提出编辑。'))
        }
      }
      if(this.support==='offered'){Row({space:8}){Button(this.tr('愿意聊聊')).softButton().layoutWeight(1).onClick(()=>{this.support='accepted';this.subtitle=this.tr('愿意说说，是什么让你在意这里吗？我在听。');});Button(this.tr('先看看就好')).softButton().layoutWeight(1).onClick(()=>{this.support='';this.subtitle=this.tr('好的，按你的节奏来。');})}}
      if(this.support==='accepted'){Button(this.tr('给自己留句话')).softButton().onClick((event:ClickEvent)=>this.open('留一句话',event))}
      if(this.cloudWaiting){Button(this.tr('取消这次请求')).softButton().onClick(()=>{this.cloudGeneration++;this.planner.cancel();this.cloudWaiting=false;this.subtitle=this.tr('好，先不等了。我们保留现在。');})}
      if(this.candidate){
        Row({space:8}){Button(this.tr('试一下')).id('apply-candidate').softButton().layoutWeight(1).backgroundColor(this.accent).fontColor('#FFFFFF').onClick(()=>this.applyCandidate()).enabled(!this.busy);Button(this.tr('保留现在')).softButton().layoutWeight(1).onClick(()=>{this.session.candidate=undefined;this.candidate='';this.subtitle=this.tr('好，就保留你现在的样子。');})}
        if(this.protectedLabel){Button(this.tr('仅这项允许修改保护区')).softButton().fontSize(12).enabled(!this.busy).onClick(()=>this.applyCandidate(true))}
      }
      if(this.applied&&!this.candidate){Row({space:6}){Button(this.tr('淡一点')).softButton().fontSize(13).layoutWeight(1).onClick(()=>this.adjust(true));Button(this.tr('换个颜色')).softButton().fontSize(13).layoutWeight(1).onClick(()=>this.adjust(false));Button(this.tr('去掉这项')).softButton().fontSize(13).layoutWeight(1).onClick(()=>this.askModel('请移除最后一项已生效的编辑层。'))}}
      if(this.wide){this.composer()}
    }.id('conversation-card').padding(18).width('100%').backgroundColor('#E8FFFFFF').backgroundBlurStyle(BlurStyle.COMPONENT_REGULAR).border({width:1,color:'#DDFFFFFF'}).borderRadius(28).shadow({radius:24,color:'#1575608C',offsetY:6}).scale({x:this.replyScale,y:this.replyScale}).opacity(this.replyOpacity)
  }
  @Builder composer(){
    Row({space:8}){TextInput({text:this.text,placeholder:this.tr(this.focusOpen?'关于这里，想说些什么…':'此刻，想说些什么…')}).id('conversation-input').layoutWeight(1).height(48).fontSize(15).backgroundColor('#C7FFFFFF').borderRadius(24).enabled(this.ready&&!this.busy&&!this.cloudWaiting).onChange((v:string)=>this.text=v).onSubmit(()=>this.command());Button(this.tr('发送')).softButton().width(62).backgroundColor(this.accent).fontColor('#FFFFFF').onClick(()=>this.command()).enabled(this.ready&&!this.busy&&!this.cloudWaiting)}.width('100%')
  }
  @Builder product(){
    ProductCard({product:this.productSelection,motion:this.motion,suggestionCount:this.replySources.length,onClose:()=>{this.getUIContext().animateTo({duration:this.motion?260:0,curve:Curve.EaseOut},()=>{this.productOpen=false;});},onChoose:(direction:number)=>this.chooseProduct(direction),onAsk:(_id:string)=>this.askModel('请简短介绍 OLAY '+this.productSelection.name+' 的关键资料，不推断配方或效果，也不要编辑面容。')})
  }
  @Builder canvasActions(){
    Row({space:8}){
      Button(this.tr(this.tool==='LASSO'?'结束圈画':'圈画')).id('lasso-tool').softButton().width(80).backgroundColor(this.tool==='LASSO'?'#DDCCE9':'#DCFFFFFF').onClick(()=>{this.focusOpen=false;this.switchTool('LASSO');}).enabled(this.ready&&!this.busy)
      Button(this.tr('对照')).softButton().width(66).onClick(()=>this.switchTool('COMPARE')).enabled(this.ready&&!this.busy)
      Button(this.tr('撤销')).softButton().width(66).onClick(()=>this.undo(-1)).enabled(this.applied&&!this.busy)
      if(this.wide){Button(this.tr('唇色想法')).softButton().width(96).onClick(()=>this.suggest(true)).enabled(this.ready&&!this.busy&&!this.cloudWaiting)}
      if(this.wide){
        Button(this.tr('照片')).softButton().width(66).onClick(()=>this.importPhoto())
        Button(this.tr('拍摄')).softButton().width(66).onClick((event:ClickEvent)=>this.open('拍摄面容',event))
        Button(this.tr('护理想法')).softButton().width(90).onClick((event:ClickEvent)=>this.open('产品资料',event))
        Button(this.tr('作品')).softButton().width(66).onClick((event:ClickEvent)=>this.open('作品与记录',event))
        Button(this.tr('导出')).softButton().width(66).onClick(()=>this.exportPNG()).enabled(this.ready&&!this.busy)
      }else{Button(this.tr('工具')).softButton().width(66).onClick((event:ClickEvent)=>this.open('工具',event)).enabled(this.ready&&!this.busy)}
    }.padding({left:12,right:12,top:8,bottom:8})
  }
  @Builder introOverlay(){
    Stack(){
      if(this.introStage===1){
        Column(){
          ForEach(this.introLines,(line:string,lineIndex:number)=>{
            Flex({wrap:FlexWrap.Wrap,justifyContent:FlexAlign.Start}){
              ForEach(line.split(''),(letter:string,index:number)=>{
                Text(letter).fontSize(this.wide?26:this.language==='zh'?18:16)
                  .lineHeight(this.wide?44:this.language==='zh'?34:29)
                  .letterSpacing(1.6).fontColor('#F2F2FF')
                  .opacity(index<(this.introRevealed[lineIndex]||0)?1:0)
                  .blur(index<(this.introRevealed[lineIndex]||0)?0:8)
                  .animation({duration:this.motion?360:0,curve:Curve.EaseOut})
              },(_letter:string,index:number)=>lineIndex.toString()+'-'+index.toString())
            }.width('100%')
          },(_line:string,lineIndex:number)=>lineIndex.toString())
        }.width(Math.min(this.surfaceWidth-56,this.wide?520:340))
          .alignItems(HorizontalAlign.Start)
          .justifyContent(FlexAlign.SpaceEvenly)
          .position({x:this.wide?56:28,y:Math.max(72,this.surfaceHeight*.08)})
          .height(this.surfaceHeight*2/3-Math.max(72,this.surfaceHeight*.08))
          .opacity(this.introPageOpacity)
          .animation({duration:this.motion?760:0,curve:Curve.EaseInOut})
      }
      Button(this.tr('跳过')).id('skip-intro').softButton().width(72).height(40).position({x:Math.max(16,this.surfaceWidth-92),y:42}).onClick(()=>this.finishIntro())
    }.width('100%').height('100%').backgroundColor('#080B17').opacity(this.introOverlayOpacity)
      .animation({duration:this.motion?1500:0,curve:Curve.EaseInOut}).zIndex(50)
  }
  @Builder galaxyHistoryRow(star:PortraitStar,index:number){
  Column({space:6}){
    Row({space:4}){
      Button({type:ButtonType.Normal,stateEffect:false}){
        Row({space:9}){
          Text((index+1).toString().padStart(2,'0')).fontSize(11).fontColor('#ACC2E2')
          Text(star.name).fontSize(15).fontWeight(FontWeight.Medium).layoutWeight(1)
            .fontColor(star.jobId===this.previewStarId?'#FFFFFF':'#E2EAF8').maxLines(1)
            .textOverflow({overflow:TextOverflow.Ellipsis}).textAlign(TextAlign.Start)
          if(star.jobId===this.previewStarId){Text('✦').fontSize(10).fontColor('#D9E8FF')}
        }.width('100%')
      }.id('star-'+star.jobId).layoutWeight(1).height(52).padding({left:11,right:7})
        .backgroundColor('#00000000').borderRadius(14)
        .onClick(()=>{this.selectStarPreview(star.jobId);this.setGalaxyDial(false);})
      Button({type:ButtonType.Normal,stateEffect:false}){
        Image($rawfile('ui/star_edit.svg')).width(19).height(19)
      }.id('rename-star-'+star.jobId).width(40).height(44).padding(0)
        .backgroundColor(this.galaxyRenameId===star.jobId?'#3E4E6E80':'#19293E3E')
        .border({width:1,color:this.galaxyRenameId===star.jobId?'#8FA9CFA6':'#35506E64'}).borderRadius(13)
        .stateStyles({pressed:{.opacity(.7).scale({x:.94,y:.94})},normal:{.opacity(1).scale({x:1,y:1})}})
        .animation({duration:this.motion?180:0,curve:Curve.EaseOut})
        .accessibilityText((this.tr('重命名星辰：'))+star.name)
        .onClick(()=>this.setGalaxyRename(this.galaxyRenameId===star.jobId?'':star.jobId))
      Button({type:ButtonType.Normal,stateEffect:false}){
        Image($rawfile('ui/star_delete.svg')).width(19).height(19)
      }.id('delete-star-'+star.jobId).width(40).height(44).padding(0)
        .backgroundColor(this.galaxyDeleteId===star.jobId?'#494E344B':'#192D293E')
        .border({width:1,color:this.galaxyDeleteId===star.jobId?'#94775B73':'#355E5064'}).borderRadius(13)
        .stateStyles({pressed:{.opacity(.7).scale({x:.94,y:.94})},normal:{.opacity(1).scale({x:1,y:1})}})
        .animation({duration:this.motion?180:0,curve:Curve.EaseOut})
        .accessibilityText((this.tr('删除星辰：'))+star.name)
        .onClick(()=>this.setGalaxyDelete(this.galaxyDeleteId===star.jobId?'':star.jobId))
    }.width('100%').padding({right:4})
    if(this.galaxyDeleteId===star.jobId){
      Column({space:10}){
        Text(this.tr('删除「')+star.name+this.tr('」？'))
          .fontSize(13).fontColor('#F3D6E1').maxLines(2).textOverflow({overflow:TextOverflow.Ellipsis})
          .lineHeight(20).width('100%')
        Text(this.tr('这段记忆将从我的星辰中移除。'))
          .fontSize(11).fontColor('#BFA9BD').lineHeight(18).width('100%')
        Row({space:8}){
          Button(this.tr('保留')).id('cancel-delete-star').layoutWeight(1).height(36)
            .fontSize(12).fontColor('#D1DEEF').backgroundColor('#34405269').borderRadius(12)
            .onClick(()=>this.setGalaxyDelete(''))
          Button(this.tr('删除')).id('confirm-delete-star').layoutWeight(1).height(36)
            .fontSize(12).fontColor('#FFE8EF').backgroundColor('#7B57435D')
            .border({width:1,color:'#967B607A'}).borderRadius(12).onClick(()=>this.removeGalaxy(star.jobId))
        }.width('100%')
      }.id('star-delete-confirmation').padding(12).margin({left:5,right:5,bottom:6})
        .backgroundColor('#71332940').border({width:1,color:'#5A725069'}).borderRadius(16)
        .transition({opacity:0,translate:{y:-4}})
    }
    if(this.galaxyRenameId===star.jobId){
      Column({space:10}){
        Text(this.tr('为这颗星辰起个名字'))
          .fontSize(13).fontColor('#DCE7F8').width('100%')
        TextInput({text:this.galaxyRenameDraft,placeholder:this.tr('星辰的名字')})
          .id('star-rename-input').fontSize(14).fontColor('#F2F6FF')
          .placeholderColor('#7E93B4').caretColor('#AFC9EE')
          .backgroundColor('#1B2A4566').border({width:1,color:'#5F7BA466'}).borderRadius(12)
          .padding({left:12,right:12}).height(38).width('100%')
          .onChange((value:string)=>{this.galaxyRenameDraft=value;})
          .onSubmit(()=>{this.saveGalaxyRename(star.jobId);})
        Row({space:8}){
          Button(this.tr('取消')).id('cancel-rename-star').layoutWeight(1).height(36)
            .fontSize(12).fontColor('#C9D8EC').backgroundColor('#2C3B5666').borderRadius(12)
            .onClick(()=>this.setGalaxyRename(''))
          Button(this.tr('保存')).id('confirm-rename-star').layoutWeight(1).height(36)
            .fontSize(12).fontColor('#F2F7FF').backgroundColor('#3D5A8566')
            .border({width:1,color:'#7E9CC4A6'}).borderRadius(12)
            .onClick(()=>this.saveGalaxyRename(star.jobId))
        }.width('100%')
      }.id('star-rename-editor').padding(12).margin({left:5,right:5,bottom:6})
        .backgroundColor('#1A274280').border({width:1,color:'#5F7BA473'}).borderRadius(16)
        .transition({opacity:0,translate:{y:-4}})
    }
  }.width('100%')
    .backgroundColor(star.jobId===this.previewStarId?'#3F5B82B5':'#00000000').borderRadius(14)
  }
  @Builder galaxyNavigation(){
    Stack(){
      if(this.galaxyDialOpen){
        Column({space:9}){
          Row(){
            Text(this.tr('我的星辰')).fontSize(17).fontWeight(FontWeight.Medium).fontColor('#F6F8FF')
            Blank()
            StarCloseButton({diameter:36,label:this.tr('关闭'),onClose:()=>this.setGalaxyDial(false)})
              .id('galaxy-list-close')
          }.width('100%')
          Scroll(){
            Column({space:4}){
              if(this.starItems.length===0){
                Column({space:9}){
                  Text('✦').fontSize(25).fontColor('#8DA3C8')
                  Text(this.tr('留一片星空，等下一次相遇')).fontSize(13)
                    .fontColor('#B4C4DF').textAlign(TextAlign.Center).lineHeight(21)
                }.width('100%').padding({top:28,bottom:28,left:8,right:8})
              }
              ForEach(this.starItems,(star:PortraitStar,index:number)=>{
                GalaxyDeleteRow({rowId:star.jobId,deleting:this.galaxyDissolvingId===star.jobId,
                  active:this.foreground,motion:this.motion,content:()=>{this.galaxyHistoryRow(star,index);},
                  onFlight:(request:GalaxyDeleteFlightRequest)=>{this.galaxyFlight={id:request.id,token:request.token,
                    x:request.x,y:request.y-this.surfaceTop,width:request.width,height:request.height};},
                  onDissolved:(id:string,height:number)=>this.finishGalaxyDelete(id,height)})
                  .translate({y:this.galaxyRiseIds.includes(star.jobId)?this.galaxyRiseOffset:0})
                  .enabled(!this.galaxyDissolvingId&&this.galaxyRiseIds.length===0)
              },(star:PortraitStar)=>star.jobId+'-'+star.name)
            }
          }.scrollBar(BarState.Off).width('100%').height(Math.min(this.surfaceHeight*.46,290))
        }.padding(13).width(Math.min(290,this.surfaceWidth*.78))
          .backgroundColor('#E6101C31').backgroundBlurStyle(BlurStyle.COMPONENT_REGULAR,{colorMode:ThemeColorMode.DARK})
          .border({width:1,color:'#819ABE91'}).borderRadius(24)
          .shadow({radius:22,color:'#59050B18',offsetY:8})
          .transition({opacity:0,scale:{x:.84,y:.78,centerX:Math.min(290,this.surfaceWidth*.78)-20,centerY:26},translate:{y:-10}})
      }else{
        Column({space:8}){
          Text((this.starItems.length===0?0:Math.max(0,this.starItems.findIndex((star:PortraitStar)=>star.jobId===this.previewStarId))+1).toString().padStart(2,'0')+
            ' / '+this.starItems.length.toString().padStart(2,'0')).fontSize(12).fontColor('#DBE7F8').letterSpacing(1)
          Button(){
            Column({space:3}){
              Circle().width(8).height(8).fill('#EAF3FF')
              Rect().width(1.5).height(21).fill('#AFC3DF')
              Text('⌄').fontSize(21).fontColor('#F3F7FF')
            }
          }.id('galaxy-next').width(54).height(80).backgroundColor('#253A5899')
            .border({width:1,color:'#829CC3A8'}).borderRadius(27)
            .stateStyles({pressed:{.scale({x:.94,y:.9})},normal:{.scale({x:1,y:1})}})
            .animation({duration:this.motion?220:0,curve:Curve.EaseOut}).onClick(()=>this.nextGalaxy())
          Button('☰').id('galaxy-list-toggle').width(40).height(40).fontSize(17)
            .fontColor('#E8F0FC').backgroundColor('#23385186').borderRadius(20)
            .onClick(()=>this.setGalaxyDial(true))
        }.alignItems(HorizontalAlign.Center).width(66)
          .transition({opacity:0,scale:{x:.92,y:.88},translate:{y:-8}})
      }
    }.width(this.galaxyDialOpen?Math.min(290,this.surfaceWidth*.78):66)
      .position({x:this.galaxyDialOpen?Math.max(18,this.surfaceWidth-Math.min(290,this.surfaceWidth*.78)-28):this.surfaceWidth-94,
        y:this.wide?140:155}).zIndex(12)
  }
  @Builder nightHome(){
    Stack(){
      NightSkySurface({formation:this.journey==='forming'?.22+this.reconProgress*.006:this.skyOpen?.22:this.personalActive()?.16:.82+Math.min(.09,this.starItems.length*.013),nameKept:this.starNameKept,nameLightY:this.starNameLightY(),musicPulse:this.musicPulse,motion:this.motion,active:this.foreground&&!this.cameraLive&&!this.galaxyDissolvingId&&!this.galaxyFlight&&(!this.personalActive()||this.journey==='forming'),phaseMode:this.skyOpen?'sky':this.journey==='forming'?'forming':this.personalActive()?'sky':'origin',onSceneChange:(index:number)=>this.onOriginScene(index)}).width('100%').height('100%')
      if(this.skyMounted){
        GalaxyUniverseSurface({items:this.galaxySceneItems,selectedId:this.previewStarId,navigationSerial:this.galaxyNavigationSerial,
          travelId:this.galaxyTravelId,motion:this.motion,language:this.language,paused:!!this.galaxyDissolvingId||!!this.galaxyFlight,
          onSelection:(id:string)=>this.chooseGalaxy(id),
          onReady:()=>{this.previewReady=true;console.info('SELF_GALAXY_UNIVERSE_READY');},
          onApproach:(id:string)=>this.arriveAtGalaxy(id),
          onFailure:(message:string)=>{this.previewReady=false;
            if(this.galaxyTravelId)this.recoverGalaxy(this.tr('星光暂时中断了，可以返回后重试。'));
            else this.galaxyStatus=this.tr('星光暂时中断了，可以返回后重试。');
            console.warn('SELF_GALAXY_UNIVERSE_FAILED '+message);},
          onInteraction:()=>{this.markInteraction();if(this.skyOpen&&!this.galaxyTravelId)this.scheduleGalaxyCaption();}}).width('100%').height('100%')
          .opacity(this.skyOpacity).zIndex(1)
          .hitTestBehavior(this.skyOpen&&this.skyTransition==='idle'?HitTestMode.Default:HitTestMode.None)
      }
      if(this.personalActive()&&this.journey!=='forming'){
        PersonalPortraitEditor({gaussianPath:this.personalGaussianPath,viewPath:this.personalViewPath,
          onTransferAvailability:(allowed:boolean)=>{this.transferEditorSafe=allowed;},
          assetId:this.activeStarId,language:this.language,cloudEnabled:this.cloudSessionEnabled,
          cloudConsentDecision:this.cloudConsentDecision,
          backendAddress:this.backendAddress,backendToken:this.backendToken,
          viewportWidth:this.surfaceWidth,viewportHeight:this.surfaceHeight,
          onCaptionSuppress:(suppressed:boolean)=>{this.setPreviewCaptionSuppressed(suppressed);},
          onBackgroundTone:(light:boolean)=>{if(this.personalBackdropLight!==light){
            this.getUIContext().animateTo({duration:this.motion?650:0,curve:Curve.EaseInOut},()=>{this.personalBackdropLight=light;});}},
          onEnableCloud:()=>this.setCloudConsent(true),onDeclineCloud:()=>{this.setCloudConsent(false);},
          onReady:()=>{this.personalReady=true;this.captureStatus='';
            if(this.skyTransition==='loading'){this.finishGalaxyArrival();return;}
            if(this.journey==='revealing'){
            this.getUIContext().animateTo({duration:this.motion?1350:0,curve:Curve.EaseOut},()=>{this.revealOpacity=0;this.revealScale=7;});
            this.revealTimer=setTimeout(()=>{this.journey='idle';this.revealTimer=-1;},this.motion?1380:50);
          }},onFailure:(message:string)=>{
            if(this.galaxyTravelId){this.recoverGalaxy(this.tr('这段记忆暂时未能展开，可以稍后再试。'));return;}
            this.personalReady=false;this.captureStatus=message;this.journey='failed';},onInteraction:()=>{this.markInteraction();this.collapsePreviewTools();}}).width('100%').height('100%')
      }
      if(this.journey==='revealing'){
        Stack(){Circle().width(72).height(72).fill('#B6C8EC').shadow({radius:80,color:'#A7C7EE'}).scale({x:this.revealScale,y:this.revealScale})}.width('100%').height('100%').backgroundColor('#080C1B').opacity(this.revealOpacity).hitTestBehavior(HitTestMode.None)
      }
      Row({space:10}){
        Column({space:2}){Text('SELF').fontSize(25).letterSpacing(5).fontWeight(FontWeight.Medium)
          .fontColor(this.personalActive()&&this.personalBackdropLight?'#263149':'#F5F5FF');
          Text(this.tr('循光，遇见自己')).fontSize(10).letterSpacing(2)
            .fontColor(this.personalActive()&&this.personalBackdropLight?'#40516B':'#A9BCD8')}
          .alignItems(HorizontalAlign.Start).onClick(()=>this.returnOrigin())
        Blank()
        Button({type:ButtonType.Capsule,stateEffect:false}){
          Stack(){Image($rawfile('ui/nav_music.svg')).width(28).height(28)
              .scale({x:this.buttonPulse==='music'?1.12:1,y:this.buttonPulse==='music'?1.12:1})
              .animation({duration:this.motion?210:0,curve:Curve.EaseOut})
            if(this.musicOn){Circle().width(4).height(4).fill('#46617E').position({x:40,y:36})}}
            .width(58).height(46)
        }.id('music-toggle').width(58).height(46).padding(0).borderRadius(23)
          .backgroundColor(this.navPressed==='music'?'#ECEDF3FA':'#D8D8E5F2')
          .backgroundBlurStyle(BlurStyle.COMPONENT_ULTRA_THIN)
          .border({width:1,color:'#B5F8FAFF'})
          .shadow({radius:6,color:'#3C405878',offsetY:2})
          .stateStyles({pressed:{.scale({x:.94,y:.9})},normal:{.scale({x:1,y:1})}})
          .animation({duration:this.motion?170:0,curve:Curve.EaseOut})
          .onTouch((event:TouchEvent)=>{this.navPressed=event.type===TouchType.Down?'music':'';})
          .accessibilityText(this.tr(this.musicOn?'音乐开':'音乐关')).onClick(()=>this.toggleMusic(!this.musicOn))
        Button({type:ButtonType.Capsule,stateEffect:false}){
          Image($rawfile('ui/nav_settings.svg')).width(28).height(28)
            .scale({x:this.buttonPulse==='设置'?1.1:1,y:this.buttonPulse==='设置'?1.1:1})
            .animation({duration:this.motion?210:0,curve:Curve.EaseOut})
        }.id('open-settings').width(52).height(46).padding(0).borderRadius(17)
          .backgroundColor(this.navPressed==='settings'?'#ECEDF3FA':'#D8DDE8F2')
          .backgroundBlurStyle(BlurStyle.COMPONENT_ULTRA_THIN)
          .border({width:1,color:'#B5F8FAFF'})
          .shadow({radius:6,color:'#3C405878',offsetY:2})
          .stateStyles({pressed:{.scale({x:.93,y:.89})},normal:{.scale({x:1,y:1})}})
          .animation({duration:this.motion?160:0,curve:Curve.EaseOut})
          .onTouch((event:TouchEvent)=>{this.navPressed=event.type===TouchType.Down?'settings':'';})
          .accessibilityText(this.tr('设置')).onClick((event:ClickEvent)=>this.open('设置',event))
      }.padding({left:this.wide?40:22,right:this.wide?40:22,top:42,bottom:12}).width('100%').position({x:0,y:0}).zIndex(30)
        .opacity(this.galaxyTravelId?0:1).enabled(!this.galaxyTravelId)
        .animation({duration:this.motion?650:0,curve:Curve.EaseInOut})
      if(this.personalActive()&&!this.detail&&this.journey!=='forming'&&this.skyTransition==='idle'){
        Stack({alignContent:Alignment.Center}){
          Row({space:0}){
            Button({type:ButtonType.Normal,stateEffect:false}){
              Row({space:7}){
                Image($rawfile('ui/island_star.svg')).width(15).height(15)
                Text(this.tr('我的星辰')).fontSize(13)
                  .fontWeight(FontWeight.Medium).fontColor('#F4F7FF')
              }.justifyContent(FlexAlign.Center)
            }.id('open-star-sky').width(132).height(44).padding(0)
              .backgroundColor('#00000000').borderRadius(22)
              .stateStyles({pressed:{.scale({x:.95,y:.94})},normal:{.scale({x:1,y:1})}})
              .animation({duration:this.motion?170:0,curve:Curve.EaseOut}).onClick(()=>this.enterSky())
            Rect().width(1).height(20).fill('#587593')
            Button({type:ButtonType.Normal,stateEffect:false}){
              Row({space:7}){
                Image($rawfile('ui/island_origin.svg')).width(15).height(15)
                Text(this.tr('回到原点')).fontSize(13)
                  .fontWeight(FontWeight.Medium).fontColor('#F4F7FF')
              }.justifyContent(FlexAlign.Center)
            }.id('return-origin').width(132).height(44).padding(0)
              .backgroundColor('#00000000').borderRadius(22)
              .stateStyles({pressed:{.scale({x:.95,y:.94})},normal:{.scale({x:1,y:1})}})
              .animation({duration:this.motion?170:0,curve:Curve.EaseOut}).onClick(()=>this.returnOrigin())
          }.width(277).height(46).justifyContent(FlexAlign.Center)
            .opacity(this.previewToolsCollapsed?0:1)
            .scale({x:this.previewToolsCollapsed?.6:1,y:this.previewToolsCollapsed?.6:1})
            .hitTestBehavior(this.previewToolsCollapsed?HitTestMode.None:HitTestMode.Default)
          Row({space:4}){
            Image($rawfile('ui/island_star.svg')).width(13).height(13)
            Image($rawfile('ui/island_chevron.svg')).width(11).height(11)
          }.justifyContent(FlexAlign.Center)
            .opacity(this.previewToolsCollapsed?1:0)
            .scale({x:this.previewToolsCollapsed?1:.4,y:this.previewToolsCollapsed?1:.4})
            .hitTestBehavior(this.previewToolsCollapsed?HitTestMode.Default:HitTestMode.None)
            .onClick(()=>this.expandPreviewTools())
        }.width(this.previewToolsCollapsed?54:277).height(this.previewToolsCollapsed?32:46)
          .position({x:(this.surfaceWidth-(this.previewToolsCollapsed?54:277))/2,
            y:this.previewToolsCollapsed?49:this.previewBarY()})
          .backgroundColor(this.previewToolsCollapsed?'#D91B2D47':'#CE1B2D47')
          .backgroundBlurStyle(BlurStyle.COMPONENT_ULTRA_THIN)
          .border({width:1,color:'#7E9EBE'})
          .borderRadius(this.previewToolsCollapsed?16:23)
          .shadow({radius:9,color:'#42101B31',offsetY:2})
          .zIndex(31)
          .onClick(()=>{if(this.previewToolsCollapsed)this.expandPreviewTools();})
      }
      if(this.journey==='idle'&&!this.detail&&!this.galaxyTravelId){
        Column({space:12}){
          if(this.skyOpen){
            Text(this.tr(this.galaxyCaption)).id('galaxy-caption').fontSize(this.wide?27:21).letterSpacing(2)
              .fontWeight(FontWeight.Medium).fontColor('#F5F4FF').maxLines(2)
              .textOverflow({overflow:TextOverflow.Ellipsis}).opacity(this.galaxyCaptionOpacity)
              .textShadow({radius:5,color:'#7D101528',offsetY:2}).width('100%')
          }else{
          Flex({wrap:FlexWrap.Wrap}){
            ForEach(this.currentStoryLine().split(''),(letter:string,index:number)=>{
              Text(letter).fontSize(this.wide?27:21).letterSpacing(2).fontWeight(FontWeight.Medium)
                .fontColor(this.personalActive()&&this.personalBackdropLight?'#27334D':'#F5F4FF')
                .opacity(index<this.visibleCharacters?1:0).blur(index<this.visibleCharacters?0:7)
                .textShadow({radius:5,color:'#7D101528',offsetY:2})
                .animation({duration:this.motion?280:0,curve:Curve.EaseOut})
            },(_letter:string,index:number)=>this.currentStoryLine()+'-'+index.toString())
          }.width('100%')
          }
          if(!this.skyOpen){Text(this.personalActive()?(this.tr('轻轻转动，看看每一面的自己。')):this.originTitles()[this.originScene])
            .fontSize(13).letterSpacing(2).fontColor(this.personalActive()&&this.personalBackdropLight?'#40516B':'#BAC9E0')
            .opacity(this.personalActive()&&this.previewCaptionTyped?this.previewCaptionSub:1)
            .textShadow({radius:5,color:'#7D101528',offsetY:2})}
        }.alignItems(HorizontalAlign.Start).width(Math.min(this.surfaceWidth-48,this.wide?460:340))
          .position({x:this.wide?50:26,y:this.personalActive()?this.previewCaptionY:Math.max(this.surfaceHeight*(this.skyOpen?.145:this.wide?.22:.18),
            this.hasProgressCapsule()&&!this.wide?(this.personalActive()?224:178):0)})
          .opacity(this.personalActive()?(this.previewCaptionSuppressed?0:this.previewCaptionOpacity):1)
          .hitTestBehavior(HitTestMode.None).zIndex(5)
      }
      if(this.skyOpen&&!this.detail&&!this.galaxyTravelId){
        if(this.starItems.length===0){
          Text(this.tr('第一颗星辰，会从一次拍摄开始。'))
            .fontSize(16).fontColor('#D3E0F5').position({x:this.wide?50:26,y:this.surfaceHeight*.39}).zIndex(5)
        }else{Column(){this.galaxyNavigation()}.width('100%').height('100%').hitTestBehavior(HitTestMode.Transparent).zIndex(5)}
      }
      if(this.journey==='forming'){
        Flex({wrap:FlexWrap.Wrap}){
          ForEach(this.formationLine.split(''),(letter:string,index:number)=>{
            Text(letter).fontSize(this.wide?27:21).letterSpacing(2).fontWeight(FontWeight.Medium).fontColor('#F5F4FF')
              .opacity(index<this.formationChars?1:0).blur(index<this.formationChars?0:7)
              .animation({duration:this.motion?280:0,curve:Curve.EaseOut})
          },(_letter:string,index:number)=>this.formationLine+'-'+index.toString())
        }.width(Math.min(this.surfaceWidth-48,this.wide?460:340))
          .position({x:this.wide?50:26,y:this.surfaceHeight*(this.wide?.22:.18)}).hitTestBehavior(HitTestMode.None)
        Button({type:ButtonType.Normal,stateEffect:false}){
          Column({space:6}){
            Text(this.keptStarName).fontSize(this.wide?25:21).lineHeight(this.wide?30:26).fontWeight(FontWeight.Medium)
              .fontColor('#F1F4FF').letterSpacing(1.5).maxLines(2).textAlign(TextAlign.Center)
              .textOverflow({overflow:TextOverflow.Ellipsis}).textShadow({radius:12,color:'#738FB3C8'})
            Text(this.tr('名字已留下 · 轻触重新命名'))
              .fontSize(11).lineHeight(14).fontColor('#ADBED5').letterSpacing(.6)
          }.width('100%')
        }.id('edit-star-name').width(Math.min(this.surfaceWidth-64,420)).height(88).padding({left:12,right:12,top:4,bottom:4})
          .backgroundColor(Color.Transparent).borderRadius(18).zIndex(2)
          .position({x:(this.surfaceWidth-Math.min(this.surfaceWidth-64,420))/2,y:this.starNameLabelY()})
          .opacity(this.starNameLabelPresence).translate({x:0,y:(1-this.starNameLabelPresence)*16})
          .blur((1-this.starNameLabelPresence)*2)
          .accessibilityText((this.tr('重新命名星辰：'))+this.keptStarName)
          .accessibilityLevel(this.starNameKept?'yes':'no-hide-descendants')
          .hitTestBehavior(this.starNameKept?HitTestMode.Default:HitTestMode.None)
          .focusable(this.starNameKept&&!this.reconCancelling)
          .enabled(!this.reconCancelling).onClick(()=>this.editStarName())
        Column({space:12}){
          TextInput({text:this.starNameDraft,controller:this.starNameController,placeholder:this.tr('这颗星辰，想叫什么？')}).id('star-name-input')
            .width('100%').height(44).maxLength(24).fontColor('#F5F4FF').placeholderColor('#C0C8DC')
            .backgroundColor('#1A293D').border({width:1,color:'#6E8BA9'}).borderRadius(18)
            .enabled(!this.reconCancelling).focusable(!this.starNameKept&&!this.reconCancelling)
            .enterKeyType(EnterKeyType.Done)
            .onChange((value:string)=>{if(!this.starNameKept){this.starNameDraft=value;this.starNameError='';}}).onSubmit(()=>this.saveStarName())
            .onDisAppear(()=>this.clearStarNameFocus())
          Button(this.tr('留下名字')).id('save-star-name').width(144).height(38)
            .fontSize(13).fontColor('#DFEEFF').backgroundColor('#263E5B').border({width:1,color:'#7B9AB9'}).borderRadius(19)
            .enabled(!this.reconCancelling&&this.starNameDraft.trim().length>0)
            .focusable(!this.starNameKept&&!this.reconCancelling).onClick(()=>this.saveStarName())
        }.id('star-name-editor').width(Math.min(300,this.surfaceWidth-84)).height(94)
          .position({x:(this.surfaceWidth-Math.min(300,this.surfaceWidth-84))/2,y:this.starNameEditorY()})
          .opacity(this.starNameEditorPresence).blur((1-this.starNameEditorPresence)*2)
          .scale({x:.985+.015*this.starNameEditorPresence,y:.985+.015*this.starNameEditorPresence,centerX:'50%',centerY:'50%'})
          .accessibilityLevel(this.starNameKept?'no-hide-descendants':'auto')
          .hitTestBehavior(this.starNameKept?HitTestMode.None:HitTestMode.Default)
        Column({space:10}){
          Row({space:10}){
          Button(this.tr('先回主页'))
            .id('minimize-reconstruction').width(144).height(34).fontSize(12).fontColor('#DAE8FA')
            .backgroundColor('#253A55').border({width:1,color:'#718BAA'}).borderRadius(17)
            .onClick(()=>this.minimizeReconstruction())
          Button(this.reconCancelling?(this.tr('正在停下…')):(this.tr('取消这次寻找')))
            .id('cancel-reconstruction').width(144).height(34).fontSize(12).fontColor('#B8CAE1')
            .backgroundColor('#172336').border({width:1,color:'#536781'}).borderRadius(17)
            .enabled(!this.reconCancelling).onClick(()=>this.cancelReconstruction())
          }.justifyContent(FlexAlign.Center)
          Row({space:9}){
            Text(this.tr('循光')).fontSize(11).fontColor('#A7BDD6')
            Progress({value:this.reconProgress,total:100,type:ProgressType.Linear})
              .width(Math.min(195,this.surfaceWidth-180)).height(3).color('#BEDCF4').backgroundColor('#263A54')
            Text(Math.round(this.reconProgress)+'%').fontSize(11).fontColor('#A7BDD6')
          }.justifyContent(FlexAlign.Center)
        }.width(Math.min(this.surfaceWidth-40,360))
          .position({x:Math.max(20,(this.surfaceWidth-Math.min(this.surfaceWidth-40,360))/2),y:this.starNameEditorY()+112})
        if(this.starNameError){
          Text(this.tr(this.starNameError)).fontSize(12).fontColor('#ECD4BD').maxLines(2).textAlign(TextAlign.Center)
            .width(Math.min(300,this.surfaceWidth-64)).height(32)
            .position({x:(this.surfaceWidth-Math.min(300,this.surfaceWidth-64))/2,y:this.starNameEditorY()-38})
        }
      }
      if(this.journey==='failed'&&this.captureStatus){
        Column({space:12}){
          Text(this.tr(this.captureStatus)).fontSize(14).fontColor('#E9E2F4').maxLines(3).textAlign(TextAlign.Center)
          if(this.pendingCaptureName&&this.reconCanRetry){Button(this.tr('重试这段拍摄')).id('retry-reconstruction').softButton().fontColor('#F5F4FF').backgroundColor('#536787A6').onClick(()=>this.submitCapture(this.pendingCaptureName))}
          else{Button(this.tr('再拍一次')).id('retake-capture').softButton().fontColor('#F5F4FF').backgroundColor('#536787A6').onClick((event:ClickEvent)=>this.open('拍摄面容',event))}
        }.padding(18).width(Math.min(this.surfaceWidth-40,440)).backgroundColor('#34465C91').border({width:1,color:'#7D9AB9A1'}).borderRadius(22).position({x:Math.max(20,(this.surfaceWidth-Math.min(this.surfaceWidth-40,440))/2),y:this.surfaceHeight*.61})
      }
      if((!this.detail||this.detail==='留一句话'||this.detail==='作品与记录')&&this.journey!=='forming'&&!this.personalActive()&&!this.galaxyTravelId){
        Column({space:12}){
          if(this.skyOpen&&this.starItems.length>0&&!this.galaxyStatus){Text(this.tr('轻轻滑动 · 循光寻回一段记忆')).fontSize(11).letterSpacing(1).fontColor('#98AAC8')}
          if(this.skyOpen&&this.galaxyStatus){Text(this.tr(this.galaxyStatus)).fontSize(12).fontColor('#CBD8EB').textAlign(TextAlign.Center).maxLines(2).width('84%')}
          Row({space:10}){
            if(!this.detail&&!this.personalActive()&&!this.skyOpen){
              PortraitFindButton({label:this.tr('寻找我的模样'),english:this.language==='en',
                motion:this.motion,active:this.foreground&&!this.cameraLive,onFind:(event:ClickEvent)=>this.open('拍摄面容',event)})
                .borderRadius(28).clip(true)
            }
            if(this.skyOpen){
              if(this.previewStarId){Button((this.tr('走近 · '))+this.currentGalaxyName()).id('open-star-full').softButton().fontColor('#F4E8D7').backgroundColor('#A62A354D').constraintSize({maxWidth:this.surfaceWidth*.62}).enabled(this.previewReady&&this.skyTransition==='idle').onClick(()=>this.openStar(this.previewStarId))}
              Button(this.tr('回到原点')).id('return-origin-sky').softButton().fontColor('#F4F2FF').backgroundColor('#61374766').enabled(this.skyTransition==='idle').onClick(()=>this.returnOrigin())
            }
            else{
              if(!this.detail){Button(this.tr('我的星辰')).id('open-star-sky-origin').softButton().fontColor('#F4F2FF').backgroundColor('#61374766').onClick(()=>this.enterSky())}
              Button(this.tr('留句话')).id('home-note').softButton().fontColor('#F4F2FF')
                .backgroundColor(this.detail==='留一句话'?'#82536D91':'#61374766')
                .scale({x:this.buttonPulse==='留一句话'?1.055:1,y:this.buttonPulse==='留一句话'?1.055:1})
                .shadow({radius:this.buttonPulse==='留一句话'?13:this.detail==='留一句话'?9:5,color:this.buttonPulse==='留一句话'?'#7489B4A8':'#26344B77',offsetY:2})
                .animation({duration:this.motion?210:0,curve:Curve.EaseOut})
                .onClick((event:ClickEvent)=>this.open('留一句话',event))
              Button(this.tr('足迹')).id('home-works').softButton().fontColor('#F4F2FF')
                .backgroundColor(this.detail==='作品与记录'?'#82536D91':'#61374766')
                .scale({x:this.buttonPulse==='作品与记录'?1.055:1,y:this.buttonPulse==='作品与记录'?1.055:1})
                .shadow({radius:this.buttonPulse==='作品与记录'?13:this.detail==='作品与记录'?9:5,color:this.buttonPulse==='作品与记录'?'#7489B4A8':'#26344B77',offsetY:2})
                .animation({duration:this.motion?210:0,curve:Curve.EaseOut})
                .onClick((event:ClickEvent)=>this.open('作品与记录',event))
            }
          }.justifyContent(FlexAlign.Center)
          if(!this.detail&&!this.skyOpen&&!this.personalActive()){Text(this.journey==='forming'?'':this.tr('从一次轻轻的拍摄开始。')).fontSize(12).fontColor('#AFC1D6').textAlign(TextAlign.Center)}
        }.width('100%').position({x:0,y:Math.max(0,this.surfaceHeight-(this.skyOpen?178:154))})
          .hitTestBehavior(HitTestMode.Transparent).zIndex(10)
      }
      if(this.detail){Column(){this.panelCard()}.id('detail-panel').width(this.panelWidth()).height(this.panelHeight()).position({x:this.panelX(),y:this.panelY()})
        .transition({opacity:0,scale:{x:.97,y:.92,centerX:this.anchorX-this.panelX(),centerY:this.anchorY-this.panelY()},translate:{y:this.panelEntranceY()}}).zIndex(20)}
      if(this.galaxyTravelId&&this.skyTransition!=='arriving'){
        Button(this.tr('留在星辰之间')).id('cancel-star-travel')
          .height(42).padding({left:20,right:20}).fontSize(13).fontColor('#B9CBE4')
          .backgroundColor('#66202D44').border({width:1,color:'#5D7897'}).borderRadius(23)
          .position({x:Math.max(20,this.surfaceWidth/2-80),y:this.surfaceHeight*.84}).width(160).zIndex(35)
          .onClick(()=>this.recoverGalaxy())
      }
      if(this.skyMounted){
        Column(){}.width('100%').height('100%').backgroundColor('#02040B').opacity(this.skyVeil)
          .hitTestBehavior(HitTestMode.None).zIndex(40)
      }
      if(this.skyTransition==='entering'||this.skyTransition==='leaving'){
        Column(){}.id('sky-transition-blocker').width('100%').height('100%').backgroundColor('#00000000').zIndex(41)
      }
      GalaxyDeleteFlight({request:this.galaxyFlight,active:this.foreground,motion:this.motion,
        onEnded:(id:string,height:number)=>{if(this.galaxyFlight?.id===id){
          this.galaxyFlight=undefined;this.finishGalaxyDelete(id,height);}}})
        .width('100%').height('100%').hitTestBehavior(HitTestMode.None).zIndex(32)
      if(this.introStage>0){this.introOverlay()}
    }.width('100%').height('100%').backgroundColor('#080C1B').onAreaChange((_old:Area,area:Area)=>{this.surfaceWidth=Number(area.width);this.surfaceHeight=Number(area.height);this.surfaceTop=Number(area.globalPosition.y);this.windowWidth=this.surfaceWidth;this.wide=this.surfaceWidth>=840;})
  }
  build(){
    Stack(){
    if(!this.legacyEditorOpen){this.nightHome()}
    else{
    Column(){
      Row({space:10}){
        Column({space:2}){Text(this.tr('SELF')).fontSize(23).letterSpacing(4).fontWeight(FontWeight.Medium).fontColor('#42374E');Text(this.tr('自在此刻')).fontSize(10).letterSpacing(2).fontColor('#887A93')}.alignItems(HorizontalAlign.Start)
        if(this.wide){Text(this.tr('每一种样子，都值得被看见')).fontSize(13).fontColor('#998AA4').margin({left:22})}
        Blank()
        Button(){Image(this.musicOn?$rawfile('ui/music.svg'):$rawfile('ui/music_off.svg')).width(23).height(23)}.id('legacy-music-toggle').softButton().width(48).accessibilityText(this.tr(this.musicOn?'音乐开':'音乐关')).onClick(()=>this.toggleMusic(!this.musicOn))
        Button(){Image($rawfile('ui/camera.svg')).width(25).height(25)}.id('legacy-begin-capture').softButton().width(48).accessibilityText(this.tr('拍摄我的面容')).onClick(()=>this.open('拍摄面容'))
        Button(){Image($rawfile('ui/atmosphere.svg')).width(25).height(25)}.id('legacy-open-ambience').softButton().width(48).accessibilityText(this.tr('氛围')).enabled(this.ready&&!this.busy).onClick((event:ClickEvent)=>this.open('氛围',event))
        Button(){Image($rawfile('ui/settings.svg')).width(24).height(24)}.id('legacy-open-settings').softButton().width(48).accessibilityText(this.tr('设置')).onClick((event:ClickEvent)=>this.open('设置',event))
      }.padding({left:22,right:22,top:10,bottom:8}).width('100%')
      Stack({alignContent:Alignment.Bottom}){
        if(this.personalActive()){
          GaussianPortraitSurface({gaussianPath:this.personalGaussianPath,viewPath:this.personalViewPath,language:this.language,
            onReady:()=>{this.personalReady=true;this.captureStatus='';this.subtitle=this.tr('你的立体面容已经来到这里。轻轻拖动，可以从不同角度看看自己。');},
            onFailure:(message:string)=>{this.personalReady=false;this.captureStatus=message;}}).width('100%').height('100%')
        }else{
          NativeMirrorSurface({port:this.bridge,interactionEnabled:!this.busy&&!this.detail&&!this.cameraLive,motion:this.motion}).width('100%').height('100%')
        }
        if(!this.detail&&this.personalActive()){
          Row({space:8}){
            Text(this.tr('你的立体面容')).fontSize(13).fontColor('#584B68')
            Text(this.personalReady?this.tr('拖动观察'):this.tr('正在打开…')).fontSize(11).fontColor('#887A93')
          }.padding({left:14,right:14,top:8,bottom:8}).backgroundColor('#DFFFFFFF').backgroundBlurStyle(BlurStyle.COMPONENT_ULTRA_THIN).borderRadius(18).position({x:20,y:16})
          if(this.captureStatus){Text(this.tr(this.captureStatus)).fontSize(12).fontColor('#62516F').padding(10).backgroundColor('#E9FFFFFF').borderRadius(14).position({x:20,y:58})}
          Button(this.tr('查看创作示例')).softButton().height(40).fontSize(12).position({x:20,y:Math.max(76,this.surfaceHeight-70)}).onClick(()=>{this.showPersonal=false;this.subtitle=this.tr('这里是创作示例；你的立体面容已妥善保存。');})
        }
        if(!this.detail&&!this.personalActive()){
          if(this.personalGaussianPath){Button(this.tr('回到我的立体面容')).softButton().height(40).fontSize(12).position({x:20,y:16}).onClick(()=>{this.showPersonal=true;this.captureStatus='';})}
          Text(this.tr(this.identity+' · 数字表达')).fontSize(11).fontColor('#7D7188').padding({left:12,right:12,top:6,bottom:6}).backgroundColor('#BFFFFFFF').borderRadius(14).position({x:20,y:this.personalGaussianPath?64:12})
          if(this.captureStatus){Text(this.tr(this.captureStatus)).fontSize(12).fontColor('#62516F').padding({left:12,right:12,top:7,bottom:7}).backgroundColor('#DDFCF9FF').borderRadius(16).maxLines(2).position({x:20,y:this.personalGaussianPath?96:44})}
          if(this.showBeginning&&this.wide){Column({space:12}){
            Text(this.tr('从你的面容开始')).fontSize(22).fontColor('#51415F')
            Text(this.tr('拍摄自己，留下多个真实视角。')).fontSize(14).fontColor('#75617F')
            Button(this.tr('拍摄我的面容')).id('intro-capture').softButton().backgroundColor(this.accent).fontColor('#FFFFFF').onClick((event:ClickEvent)=>this.open('拍摄面容',event))
              Text(this.tr('从相机开始 · 完成后会告诉你结果')).fontSize(11).fontColor('#81758D')
            Button(this.tr('先看示例')).softButton().height(36).fontSize(12).onClick(()=>{this.showBeginning=false;if(this.motion)this.bridge.send('VIEW_ORBIT',{});})
          }.alignItems(HorizontalAlign.Start).padding(22).width(290).backgroundColor('#CAFFFFFF').backgroundBlurStyle(BlurStyle.COMPONENT_REGULAR).borderRadius(28).position({x:24,y:62}).transition({opacity:0,translate:{y:12}})}
          Text(this.tr(!this.ready?'镜面准备中':this.tool==='LASSO'?'轻轻圈画一个范围，松手后聊聊':this.wide?'拖动转身 · 双指缩放 · 手写笔直接圈画':'拖动转身 · 双指缩放')).fontSize(11).fontColor('#81758D').padding(16).position({x:0,y:this.surfaceHeight-(this.wide?128:56)}).hitTestBehavior(HitTestMode.None)
          if(!this.focusOpen&&!this.productOpen){Button(){Image($rawfile('ui/recenter.svg')).width(27).height(27)}.id('recenter-view').accessibilityText(this.tr('回正')).width(46).height(46).backgroundColor('#AFFFFFFF').backgroundBlurStyle(BlurStyle.COMPONENT_ULTRA_THIN).border({width:1,color:'#E6FFFFFF'}).borderRadius(23).shadow({radius:16,color:'#17756387',offsetY:4}).stateStyles({pressed:{.scale({x:.90,y:.90})},normal:{.scale({x:1,y:1})}}).animation({duration:this.motion?180:0,curve:Curve.EaseOut}).position({x:20,y:Math.max(70,this.surfaceHeight*.48)}).onClick(()=>this.bridge.send('VIEW_RESET',{motion:this.motion})).enabled(this.ready&&!this.busy)}
          if(this.wide){
            if(this.productOpen){
              Scroll(){Column({space:12}){this.conversation();this.product()}.width('100%')}.align(Alignment.TopStart).width(420).height(Math.max(260,this.surfaceHeight-108)).scrollBar(BarState.Off).position({x:this.focusOpen?Math.min(this.bubbleX(),this.surfaceWidth-440):Math.max(20,this.surfaceWidth-440),y:this.focusOpen?Math.min(this.bubbleY(),Math.max(16,this.surfaceHeight-680)):16}).transition({opacity:0,translate:{x:20}})
            }else{
              Column(){this.conversation()}.width(360).position({x:this.focusOpen?this.bubbleX():Math.max(20,this.surfaceWidth-396),y:this.focusOpen?this.bubbleY():40}).transition({opacity:0,scale:{x:.94,y:.94}})
            }
            Scroll(){this.canvasActions()}.scrollable(ScrollDirection.Horizontal).scrollBar(BarState.Off).width('96%').height(72).margin({bottom:12})
          }
          if(!this.wide&&this.productOpen){Scroll(){this.product()}.align(Alignment.TopStart).width('94%').height('98%').scrollBar(BarState.Off).transition({opacity:0,translate:{y:20}})}
          if(!this.wide&&this.focusOpen&&!this.productOpen){
            Scroll(){this.conversation()}.align(Alignment.TopStart).width('92%').height(this.phoneBubbleHeight()).scrollBar(BarState.Off).position({x:this.surfaceWidth*.04,y:Math.max(48,Math.min(this.surfaceHeight-this.phoneBubbleHeight()-92,this.focusY*this.surfaceHeight+35))}).transition({opacity:0,scale:{x:.94,y:.94},translate:{y:-12}})
          }
        }
        if(this.detail){Column(){this.panelCard()}.id('legacy-detail-panel').width(this.panelWidth()).height(this.panelHeight()).position({x:this.panelX(),y:this.panelY()}).transition({opacity:0,scale:{x:.97,y:.92,centerX:this.anchorX-this.panelX(),centerY:this.anchorY-this.panelY()},translate:{y:this.panelEntranceY()}})}
      }.layoutWeight(1).width('100%').onAreaChange((_old:Area,area:Area)=>{this.surfaceWidth=parseFloat(String(area.width));this.surfaceHeight=parseFloat(String(area.height));this.surfaceTop=Number(area.globalPosition.y);})
      if(!this.wide&&!this.detail&&!this.personalActive()){
        if(this.showBeginning){Button(this.tr('从拍摄我的面容开始')).softButton().onClick((event:ClickEvent)=>this.open('拍摄面容',event))}
        if(!this.focusOpen||this.productOpen){Column(){this.conversation()}.width('92%')}
        Scroll(){this.canvasActions()}.scrollable(ScrollDirection.Horizontal).scrollBar(BarState.Off).width('100%').height(66)
        Column(){this.composer()}.padding({left:20,right:20,top:4,bottom:12}).width('100%')
      }
    }.width('100%').height('100%').backgroundColor('#F3F1F5').onAreaChange((_old:Area,area:Area)=>{this.windowWidth=parseFloat(String(area.width));this.wide=this.windowWidth>=840;if(this.context.applicationInfo.debug)console.info('SELF_WINDOW '+JSON.stringify({width:this.windowWidth,wide:this.wide}));}).linearGradient({angle:145,colors:[['#EDF0F8',0],['#F8F0E9',.6],['#F3F1F5',1]]})
    }
    if(this.cameraLive){CameraCaptureView({motion:this.motion,language:this.language,backendAddress:this.backendAddress,backendToken:this.backendToken,onCapture:(name:string)=>this.submitCapture(name),onClose:()=>this.close()}).zIndex(100)}
    if(this.careLibraryOpen){
      OlayLibrary({language:this.language,viewportWidth:this.windowWidth,viewportHeight:this.surfaceHeight,
        initialProductId:this.careLibraryProductId,onClose:()=>{this.careLibraryOpen=false;this.audio.setScene(this.skyOpen?'sky':this.personalActive()?'personal':this.journey==='forming'?'forming':'origin');}})
        .position({x:12,y:this.hasProgressCapsule()?this.progressAwareTop():80}).zIndex(80)
    }
    if(this.waitingMinimized&&(this.reconstructionActive||this.reconstructionOutcome)){
      ReconstructionProgressCapsule({name:this.keptStarName,progress:this.reconProgress,
        outcome:this.reconstructionOutcome,message:this.captureStatus,language:this.language,motion:this.motion,
        capsuleWidth:this.progressCapsuleWidth(),onOpen:()=>this.openReconstructionProgress()})
        .position({x:(this.windowWidth-this.progressCapsuleWidth())/2,y:this.progressCapsuleY()}).zIndex(120)
        .transition({opacity:0,scale:{x:.98,y:.94}})
    }
    }.width('100%').height('100%').opacity(this.langFade).expandSafeArea([SafeAreaType.SYSTEM],[SafeAreaEdge.TOP,SafeAreaEdge.BOTTOM])
  }
}
