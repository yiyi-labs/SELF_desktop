import { common } from '@kit.AbilityKit';
import { fileIo as fs } from '@kit.CoreFileKit';
import { util } from '@kit.ArkTS';
import { display, window, KeyboardAvoidMode } from '@kit.ArkUI';
import { GaussianPortraitSurface, GsSelection } from './GaussianPortraitSurface';
import { PlannerClient, CloudResponse, CloudSnapshot, CloudRegion, DialogueTurn, CloudCareGuide, SelectionObservation } from '../services/PlannerClient';
import { GsRenderLayer, GsViewSnapshot } from '../bridge/RendererBridge';
import { AssetStore } from '../services/AssetStore';
import { StoryConversationClient, StoryRequest, StoryResponse, StoryTurn } from '../services/StoryConversationClient';
import { StoryObservationStore, StoryObservation } from '../services/StoryObservationStore';
import { CloudConsentStore, CloudConsentDecision } from '../services/CloudConsentStore';
import { OlayLibrary } from './OlayLibrary';
import { OlayDiscoveryRepository,OlayDiscoveryItem } from '../services/OlayDiscoveryRepository';
import { OlayPhotoRepository } from '../services/OlayPhotoRepository';
import { StarCloseButton } from './StarCloseButton';
import { UiText } from '../services/UiText';

interface SavedGsEdit {
  schemaVersion:number;
  assetId:string;
  assetBytes:number;
  splatCount:number;
  maskChecksum:string;
  preset:string;
  strength:number;
  plannerSource:string;
}
interface GsLayer {
  layerId:string;
  regionId:string;
  preset:string;
  strength:number;
  maskChecksum:string;
  maskBase64:string;
}
interface GsGroup {groupId:string;label:string;createdAt:number;layers:GsLayer[];careGuide?:CloudCareGuide|null;}
interface GsHistory {schemaVersion:number;assetId:string;assetBytes:number;splatCount:number;groups:GsGroup[];}
interface SelectedGsRegion {info:GsSelection;mask:ArrayBuffer;}
interface GsHistoryItem {layerId:string;preset:string;}
interface GsHistoryDisplay {groupId:string;label:string;items:GsHistoryItem[];careGuide?:CloudCareGuide|null;}

/** Personal 3DGS editing remains inside its PlayCanvas surface. The PLY is immutable. */
@Component
export struct PersonalPortraitEditor {
  @Prop gaussianPath:string='';
  @Prop viewPath:string='';
  @Prop assetId:string='';
  @Prop language:string='zh';
  @Prop @Watch('cloudAccessChanged') cloudEnabled:boolean=false;
  @Prop cloudConsentDecision:CloudConsentDecision='unknown';
  @Prop backendAddress:string='http://127.0.0.1:8787';
  @Prop backendToken:string='';
  @Prop viewportWidth:number=400;
  @Prop viewportHeight:number=600;
  onTransferAvailability:(allowed:boolean)=>void=()=>{};
  onReady:()=>void=()=>{};
  onFailure:(message:string)=>void=()=>{};
  onInteraction:()=>void=()=>{};
  onCaptionSuppress:(suppressed:boolean)=>void=()=>{};
  onEnableCloud:()=>boolean=()=>false;
  onDeclineCloud:()=>void=()=>{};
  onBackgroundTone:(light:boolean)=>void=()=>{};
  private context:common.UIAbilityContext=this.getUIContext().getHostContext() as common.UIAbilityContext;
  private assets:AssetStore=new AssetStore(this.context);
  private planner:PlannerClient=new PlannerClient();
  private storyClient:StoryConversationClient=new StoryConversationClient();
  private storyInputController:TextInputController=new TextInputController();
  private observationStore:StoryObservationStore=new StoryObservationStore(this.context);
  private storySessionId:string='session-'+Date.now()+'-'+Math.floor(Math.random()*1000000);
  private storyGeneration:number=0;
  private storyHintToken:number=0;
  private appWindow:window.Window|undefined=undefined;
  private previousKeyboardAvoidMode:KeyboardAvoidMode=KeyboardAvoidMode.OFFSET;
  private keyboardHeightListener=(height:number):void=>{
    if(height<=0){this.keyboardTopVp=0;return;}
    try{const screenHeight=display.getDefaultDisplaySync().height;
      this.keyboardTopVp=this.getUIContext().px2vp(screenHeight-height);}
    catch(error){console.warn('SELF_STORY_KEYBOARD_BOUNDS '+String(error));this.keyboardTopVp=0;}
  };
  private storyTurns:StoryTurn[]=[];
  private pendingStoryText:string='';
  private pendingObservationQuote:string='';
  private pendingObservationMessageId:string='';
  private selections:SelectedGsRegion[]=[];
  private lastProductIds:string[]=[];
  private selectionObservations:SelectionObservation[]=[];
  private requestChoice:string='';
  private productsDismissed:boolean=false;
  @State libraryProductId:string='';
  @State storyProductIds:string[]=[];
  @State replyProductIds:string[]=[];
  private history:GsHistory|undefined=undefined;
  private pendingHistory:GsHistory|undefined=undefined;
  private comparisonTarget:string='';
  private pendingComparison:string|undefined=undefined;
  private pending:CloudResponse|undefined=undefined;
  private pendingSnapshot:CloudSnapshot|undefined=undefined;
  private revision:number=0;
  private serial:number=0;
  private requestText:string='';
  private dialogue:DialogueTurn[]=[];
  @State editCommand:string='';
  @State @Watch('syncTransferAvailability') ready:boolean=false;
  @State @Watch('syncCaptionSuppression') tool:string='move';
  @State toolPressed:boolean=false;
  @State bubble:boolean=false;
  @State selected:boolean=false;
  @State @Watch('syncTransferAvailability') waiting:boolean=false;
  @State consentOffer:boolean=false;
  @State consentIntent:string='';
  @State @Watch('syncTransferAvailability') candidateReady:boolean=false;
  @State @Watch('syncTransferAvailability') applied:boolean=false;
  @State @Watch('syncTransferAvailability') comparing:boolean=false;
  @State keyboardOpen:boolean=false;
  @State @Watch('syncCaptionSuppression') historyOpen:boolean=false;
  @State historyPressed:boolean=false;
  @State libraryOpen:boolean=false;
  @State expandedCareGroup:string='';
  @State historyRevision:number=0;
  @State selectionCount:number=0;
  @State historyDisplay:GsHistoryDisplay[]=[];
  @State @Watch('responseChanged') responseText:string='';
  @State replyLines:string[]=[];
  @State visibleReplyLines:number=0;
  @State replyBloom:boolean=false;
  private replyToken:number=0;
  private carePreviewToken:number=0;
  @State careProductId:string='';
  @State careWhy:string='';
  @State careHow:string='';
  @State careWeek:number=0;
  @State careExpanded:boolean=false;
  @State question:string='';
  @State choices:string[]=[];
  @State input:string='';
  @State anchorX:number=.5;
  @State anchorY:number=.5;
  @State storyOpen:boolean=false;
  @State storyWaiting:boolean=false;
  @State storyInput:string='';
  @State storyReply:string='';
  @State storyKind:string='conversation';
  @State storyLastQuote:string='';
  @State storyLastMessageId:string='';
  @State storyNotesOpen:boolean=false;
  @State storyObservations:StoryObservation[]=[];
  @State storyPhase:string='start';
  @State storyHintVisible:number=0;
  @State composerDust:boolean=false;
  @State composerDustSpread:boolean=false;
  @State keyboardTopVp:number=0;
  private composerDustToken:number=0;

  private tr(value:string):string{return UiText.get(value,this.language);}
  private cloudAccessChanged():void{
    if(this.cloudEnabled)return;
    this.storyGeneration++;this.storyClient.cancel();this.storyWaiting=false;
    this.planner.cancel();this.waiting=false;this.consentOffer=false;this.consentIntent='';
  }
  private replyPanelHeight():number{
    if(this.storyNotesOpen)return Math.min(230,this.viewportHeight*.36);
    const lines=Math.max(1,Math.ceil(this.storyReply.length/(this.viewportWidth>=840?38:24)));
    const extra=(this.storyLastQuote&&this.storyKind!=='closing'?43:0)+
      (this.storyKind==='edit_entry'||this.storyKind==='real_effect_boundary'?42:0)+
       (this.consentOffer&&this.consentIntent==='story'?132:0)+(this.storyWaiting?38:0);
    return Math.min(this.viewportHeight*.36,Math.max(104,70+Math.min(6,lines)*20+extra));
  }
  private composerHeight():number{
    if(!this.storyOpen)return 62;
    return this.replyPanelHeight()+59;
  }
  private composerBottom():number{
    return this.keyboardTopVp>0?Math.min(this.viewportHeight-10,this.keyboardTopVp-12):this.viewportHeight-20;
  }
  private syncTransferAvailability():void{
    this.onTransferAvailability(this.ready&&!this.applied&&!this.candidateReady&&!this.waiting&&!this.comparing&&!this.pendingHistory);
  }
  aboutToAppear():void{
    this.previousKeyboardAvoidMode=this.getUIContext().getKeyboardAvoidMode();
    window.getLastWindow(this.context).then((found:window.Window)=>{
      this.appWindow=found;found.on('keyboardHeightChange',this.keyboardHeightListener);
    }).catch((error:Error)=>console.warn('SELF_STORY_KEYBOARD_OBSERVER '+String(error)));
  }
  private storyHint():string{
    if(this.storyPhase==='discover')return this.tr('刚才那句话，想留在这颗星辰里吗？');
    if(this.storyPhase==='return')return this.tr('今天停在这里，也很好。');
    if(this.storyPhase==='act')return this.selected?
      this.tr('这一处已经圈好，说说想试怎样的变化。'):
      this.tr('想试一点变化，可以先轻轻圈选。');
    if(this.storyPhase==='care')return this.tr('可以慢慢说，从你在意的一件事开始。');
    return this.tr('先转动看看，哪一面让你想停一会儿？');
  }
  private revealStoryHint():void{
    this.storyHintVisible=0;const token=++this.storyHintToken,length=this.storyHint().length;
    const step=()=>{if(token!==this.storyHintToken||this.storyHintVisible>=length)return;
      this.storyHintVisible++;setTimeout(step,40);};
    setTimeout(step,80);
  }
  private openStory():void{
    this.bubble=false;this.historyOpen=false;this.libraryOpen=false;this.storyOpen=true;
    if(!this.storyReply)this.storyReply=this.tr('想从哪里开始看？也可以只说说此刻的想法。');
  }
  private closeStory():void{
    this.storyInputController.stopEditing();
    this.storyGeneration++;this.storyClient.cancel();this.storyWaiting=false;
    this.consentOffer=false;this.consentIntent='';this.pendingStoryText='';this.pendingObservationQuote='';
    this.storyOpen=false;this.storyNotesOpen=false;this.keyboardOpen=false;
    this.storyPhase='return';this.revealStoryHint();
  }
  private sendStory(value:string):void{
    const text=value.trim();if(!text||this.storyWaiting)return;
    if(text.length>500){this.storyReply=this.tr('这一段稍长，分成两次说也可以。');return;}
    if(/(?:不要|不用|不想|别).{0,8}(?:推荐|产品|商品|买)|no products|don.t recommend/i.test(text))this.productsDismissed=true;
    else if(/推荐|哪款|想买|recommend/i.test(text))this.productsDismissed=false;
    if(this.selected&&/这里|圈|保养|养护|护理|护肤|怎么用|眼|脸|痘|olay|玉兰油|care|routine|this area/i.test(text)){
      this.enterExistingEdit(text);this.submit(text);return;
    }
    if(!this.cloudEnabled){
      if(this.cloudConsentDecision==='denied'){
        this.storyReply=this.tr('云端对话已关闭。想再继续时，可以在设置里开启。');return;
      }
      this.pendingStoryText=text;this.consentIntent='story';this.consentOffer=true;return;
    }
    this.askStory(text);
  }
  private acceptCloudIntroduction():void{
    const intent=this.consentIntent,text=this.pendingStoryText;
    if(!this.onEnableCloud()){
      this.storyReply=this.tr('这次没能保存选择，稍后再试。');
      this.responseText=this.storyReply;return;
    }
    this.consentOffer=false;this.consentIntent='';
    if(intent==='story')this.askStory(text);
    else if(intent==='edit')this.capture();
  }
  private declineCloudIntroduction():void{
    this.onDeclineCloud();this.consentOffer=false;this.consentIntent='';this.pendingStoryText='';
    if(this.storyOpen)this.storyReply=this.tr('好，我们先留在这里。');
    else this.responseText=this.tr('好，画面留在这里。');
  }
  private async askStory(text:string):Promise<void>{
    this.consentOffer=false;this.consentIntent='';this.pendingStoryText='';
    if(!CloudConsentStore.allowed(this.context))return;
    this.storyWaiting=true;
    const generation=++this.storyGeneration,requestId='story-'+Date.now()+'-'+Math.floor(Math.random()*1000000);
    const input:StoryRequest={schemaVersion:1,requestId,sessionId:this.storySessionId,assetId:this.assetId,
      userText:text,responseLanguage:this.language,turns:this.storyTurns.slice(-4),dismissedProducts:this.productsDismissed,
      productContextIds:this.storyProductIds.slice()};
    this.storyClient.endpoint=this.backendAddress.trim();this.storyClient.token=this.backendToken.trim();
    try{
      const result:StoryResponse=await this.storyClient.ask(input);
      if(generation!==this.storyGeneration||!this.storyOpen||result.assetId!==this.assetId||
        !CloudConsentStore.allowed(this.context))return;
      this.storyReply=result.message;this.storyKind=result.kind;this.storyLastQuote=text;
      this.storyLastMessageId=requestId;this.storyInput='';
      this.storyProductIds=result.evidenceRefs.slice();
      this.storyTurns=this.storyTurns.concat([{userText:text,reply:result.message,productIds:result.evidenceRefs.slice()}]).slice(-4);
      if(result.kind==='closing')this.storyPhase='return';
      else if(result.kind==='edit_entry'||result.kind==='product'||result.kind==='real_effect_boundary')this.storyPhase='act';
      else if(/我发现|我注意到|我喜欢|我记起|我明白/.test(text))this.storyPhase='discover';
      else this.storyPhase='care';
      this.revealStoryHint();
    }catch(error){
      if(generation===this.storyGeneration&&this.storyOpen){
        console.warn('SELF_STORY_REQUEST_FAILED '+String(error));
        this.storyReply=this.tr('这次没有接上对话。你仍可以转动、观察，稍后再说。');
      }
    }finally{if(generation===this.storyGeneration)this.storyWaiting=false;}
  }
  private enterExistingEdit(text:string):void{
    this.closeStory();this.input=text;this.bubble=true;
    this.responseText=this.selected?this.tr('圈选还在。说出想试的变化，再由你确认是否留下。'):
      this.tr('先圈出你想试的地方，再说说想法。');
    if(this.tool!=='lasso'){this.animateComposerDust(true);this.tool='lasso';this.command('TOOL','lasso');}
  }
  private animateComposerDust(out:boolean):void{
    const token=++this.composerDustToken;
    this.composerDust=true;this.composerDustSpread=!out;
    setTimeout(()=>{
      if(token!==this.composerDustToken)return;
      this.getUIContext().animateTo({duration:240,curve:Curve.EaseOut},()=>{this.composerDustSpread=out;});
    },20);
    setTimeout(()=>{if(token===this.composerDustToken)this.composerDust=false;},290);
  }
  private saveStoryQuote():void{
    if(!this.storyLastQuote||!this.storyLastMessageId)return;
    this.pendingObservationQuote=this.storyLastQuote;
    this.pendingObservationMessageId=this.storyLastMessageId;this.command('VIEW_SNAPSHOT');
  }
  private persistObservation(quote:string,messageId:string,view?:GsViewSnapshot):void{
    try{
      const record:StoryObservation={recordId:'observation-'+Date.now()+'-'+Math.floor(Math.random()*1000000),
        messageId,userQuote:quote,starId:this.assetId,assetId:this.assetId,createdAt:Date.now(),
        recallAllowed:false};
      if(view)record.view=view;
      this.storyObservations=this.observationStore.save(this.assetId,record);
      this.storyReply=this.tr('这句话已留在这颗星辰里。以后是否重新提起，仍由你决定。');
      this.storyLastQuote='';this.storyLastMessageId='';this.storyPhase='return';
      this.revealStoryHint();
    }catch(error){this.storyReply=this.tr('这句话暂时没能保存，原话还在这里。');console.warn('SELF_STORY_SAVE_FAILED '+String(error));}
  }
  private receivedView(view:GsViewSnapshot):void{
    if(!this.pendingObservationQuote||!this.storyOpen)return;
    const quote=this.pendingObservationQuote,messageId=this.pendingObservationMessageId;
    this.pendingObservationQuote='';this.pendingObservationMessageId='';
    if(view.assetId!==this.assetId||view.frame<1||view.position.length!==3||view.rotation.length!==4){
      this.persistObservation(quote,messageId);return;
    }
    this.persistObservation(quote,messageId,view);
  }
  private deleteObservation(id:string):void{
    try{this.storyObservations=this.observationStore.remove(this.assetId,id);}
    catch(error){this.storyReply=this.tr('这条记录暂时没能移除。');}
  }
  private setCareWeek(week:number):void{
    if(week===this.careWeek)return;
    this.careWeek=week;
    const token=++this.carePreviewToken;
    setTimeout(()=>{if(token===this.carePreviewToken&&this.selected&&this.careProductId){
      this.command('CARE_PREVIEW','','',week);
    }},90);
  }
  private responseChanged():void{
    const text=this.responseText.trim(),size=this.language==='en'?37:19;
    const lines:string[]=[];
    for(let i=0;i<text.length;i+=size)lines.push(text.slice(i,i+size));
    this.replyLines=lines;this.visibleReplyLines=0;
    this.revealReply(++this.replyToken);
  }
  private revealReply(token:number):void{
    if(token!==this.replyToken||this.visibleReplyLines>=this.replyLines.length)return;
    setTimeout(()=>{if(token!==this.replyToken)return;
      this.visibleReplyLines++;this.replyBloom=true;
      setTimeout(()=>{if(token===this.replyToken)this.replyBloom=false;},105);
      this.revealReply(token);
    },this.visibleReplyLines===0?35:125);
  }
  private careProduct(id:string):OlayDiscoveryItem|undefined{return OlayDiscoveryRepository.records().find((item:OlayDiscoveryItem)=>item.id===id);}
  private historyPanelWidth():number{return Math.min(this.viewportWidth-24,this.viewportHeight>this.viewportWidth?420:360);}
  private historyPanelHeight():number{return this.viewportHeight>this.viewportWidth?
    Math.min(this.viewportHeight*.69,820):Math.min(this.viewportHeight*.62,520);}
  private bubbleLeft():number {
    const width=Math.min(330,this.viewportWidth-36);
    if(this.keyboardOpen&&this.viewportWidth>=840)return 24;
    if(this.viewportWidth>=840)return this.anchorX<.5?
      Math.min(this.viewportWidth-width-24,Math.max(this.viewportWidth*.66,this.anchorX*this.viewportWidth+100)):
      28;
    return Math.max(18,Math.min(this.viewportWidth-width-18,this.anchorX*this.viewportWidth-width/2));
  }
  private directory():string{return this.context.filesDir+'/models/'+this.assetId;}
  private command(action:string,tool:string='',preset:string='',strength:number=0,maskBase64:string=''):void{
    this.editCommand=JSON.stringify({action,tool,preset,strength,maskBase64,serial:++this.serial});
  }
  private savedPath():string{return this.directory()+'/portrait.edit.json';}
  private maskPath():string{return this.directory()+'/portrait.edit.mask';}
  private historyPath():string{return this.directory()+'/portrait.edit.v2.json';}
  private checksum(bytes:Uint8Array):string {
    let value=2166136261;
    for(let i=0;i<bytes.length;i++)value=Math.imul(value^bytes[i],16777619)>>>0;
    return value.toString(16);
  }
  private restore():void {
    if(!/^[a-f0-9]{32}$/.test(this.assetId)){console.warn('SELF_GS_EDIT_RESTORE invalid_asset');return;}
    try{
      if(fs.accessSync(this.historyPath())){
        const history=JSON.parse(fs.readTextSync(this.historyPath())) as GsHistory;
        if(history.schemaVersion!==2||history.assetId!==this.assetId||history.assetBytes!==fs.statSync(this.gaussianPath).size||
          !Array.isArray(history.groups)||history.groups.length>12||
          history.groups.some((group:GsGroup)=>!Array.isArray(group.layers)||group.layers.length<1||group.layers.length>4||
            group.groupId.length>80||group.label.length>100)||
          history.groups.reduce((n:number,group:GsGroup)=>n+group.layers.length,0)>16)throw new Error('history_mismatch');
        for(const group of history.groups){
          const guide=group.careGuide;
          if(guide&&(!this.careProduct(guide.productId)||typeof guide.whyHere!=='string'||guide.whyHere.length>100||
            typeof guide.howToUse!=='string'||guide.howToUse.length>140))group.careGuide=null;
        }
        const decoder=new util.Base64Helper();
        for(const group of history.groups)for(const layer of group.layers){
          const bytes=decoder.decodeSync(layer.maskBase64);
          if(bytes.length!==history.splatCount||this.checksum(bytes)!==layer.maskChecksum||
            layer.layerId.length>100||layer.regionId.length>100||
            !['rose','terracotta'].includes(layer.preset)||![.18,.32,.5].includes(layer.strength))throw new Error('layer_mismatch');
        }
        this.history=history;this.applied=history.groups.length>0;this.refreshHistoryDisplay();
        this.renderHistory(history);console.info('SELF_GS_EDIT_RESTORE_V2 '+history.groups.length);return;
      }
      if(!fs.accessSync(this.savedPath())||!fs.accessSync(this.maskPath())){console.info('SELF_GS_EDIT_RESTORE no_recipe');return;}
      const saved=JSON.parse(fs.readTextSync(this.savedPath())) as SavedGsEdit;
      const bytes=this.assets.readFile(this.maskPath());
      if(saved.schemaVersion!==1||saved.assetId!==this.assetId||
        saved.assetBytes!==fs.statSync(this.gaussianPath).size||
        saved.splatCount!==bytes.length||bytes.length<80||saved.maskChecksum!==this.checksum(bytes)||
        !['rose','terracotta'].includes(saved.preset)||![.18,.32,.5].includes(saved.strength)){
        console.warn('SELF_GS_EDIT_RESTORE recipe_mismatch');return;
      }
      const layer:GsLayer={layerId:'legacy-1',regionId:'gs-selected-1',preset:saved.preset,strength:saved.strength,
        maskChecksum:saved.maskChecksum,maskBase64:new util.Base64Helper().encodeToStringSync(bytes)};
      this.history={schemaVersion:2,assetId:this.assetId,assetBytes:saved.assetBytes,splatCount:saved.splatCount,
        groups:[{groupId:'legacy',label:this.tr('原有试色'),createdAt:0,layers:[layer]}]};
      this.applied=true;this.refreshHistoryDisplay();this.renderHistory(this.history);
      console.info('SELF_GS_EDIT_RESTORE accepted '+bytes.length);
    }catch(error){console.warn('SELF_GS_EDIT_RESTORE_FAILED '+String(error));}
  }
  private save():void {
    if(!this.history)throw new Error('edit_state_missing');
    this.assets.writeAtomic(this.historyPath(),JSON.stringify(this.history));
    console.info('SELF_GS_EDIT_SAVED_V2 '+this.history.groups.length);
  }
  private emptyHistory():GsHistory{return {schemaVersion:2,assetId:this.assetId,
    assetBytes:fs.statSync(this.gaussianPath).size,splatCount:0,groups:[]};}
  private refreshHistoryDisplay():void{
    this.historyDisplay=(this.history?.groups||[]).map((group:GsGroup)=>{
      const items:GsHistoryItem[]=group.layers.map((layer:GsLayer)=>{
        const item:GsHistoryItem={layerId:layer.layerId,preset:layer.preset};return item;
      });
      const display:GsHistoryDisplay={groupId:group.groupId,label:group.label,items,careGuide:group.careGuide};return display;
    });
    this.historyRevision++;
  }
  private renderHistory(history:GsHistory,filter:string=''):void{
    const layers:GsRenderLayer[]=[];
    for(const group of history.groups)for(const layer of group.layers){
      if(filter&&filter!==group.groupId&&filter!==layer.layerId)continue;
      const renderLayer:GsRenderLayer={maskBase64:layer.maskBase64,preset:layer.preset,strength:layer.strength};
      layers.push(renderLayer);
    }
    this.editCommand=JSON.stringify({action:'SET_HISTORY',layers,serial:++this.serial});
  }
  private stageHistory(next:GsHistory):void{
    this.pendingHistory=next;this.syncTransferAvailability();this.renderHistory(next);
  }
  private editFailed(message:string):void{
    this.waiting=false;
    if(this.pendingHistory){this.pendingHistory=undefined;this.syncTransferAvailability();if(this.history)this.renderHistory(this.history);}
    this.pendingComparison=undefined;
    this.responseText=message;this.bubble=true;
  }
  private viewerReady():void{
    this.ready=true;this.restore();this.storyObservations=this.observationStore.list(this.assetId);
    this.revealStoryHint();this.onReady();
  }
  private selectedRegion(info:GsSelection,mask:ArrayBuffer):void{
    console.info('SELF_GS_SELECTION_READY '+info.count+' '+info.total+' '+mask.byteLength);
    this.planner.cancel();this.pending=undefined;this.pendingSnapshot=undefined;
    this.carePreviewToken++;
    if(this.careWeek>0)this.command('CARE_PREVIEW','','',0);
    this.careWeek=0;this.careProductId='';this.careWhy='';this.careHow='';
    const existing=this.selections.findIndex((item:SelectedGsRegion)=>item.info.regionId===info.regionId);
    if(existing<0&&this.selections.length>=4)return;
    if(existing>=0)this.selections[existing]={info,mask};
    else this.selections.push({info,mask});
    this.selectionCount=this.selections.length;
    this.dialogue=[];this.lastProductIds=[];this.selectionObservations=[];this.requestChoice='';
    this.selected=true;this.candidateReady=false;
    this.storyPhase='act';this.revealStoryHint();
    this.anchorX=Math.max(.1,Math.min(.9,info.x));this.anchorY=Math.max(.15,Math.min(.7,info.y));
    const firstPrompts=['这一处已留下。再画可重选，也可以说说想法。',
      '光落在这里了。想换一处，直接再画一圈。','这处会跟着你的面容；想微调，还可以重画。'];
    this.bubble=true;this.responseText=existing>=0?
      this.tr('这一处已经换成刚画的范围。'):
      this.selections.length===1?
        this.tr(firstPrompts[(this.history?.groups.length||0)%firstPrompts.length]):
      this.tr('已经圈出{count}处。可以一起告诉我每处想试的变化。').replace('{count}',String(this.selections.length));
    this.question='';this.choices=[];this.revision++;this.onInteraction();
  }
  private appendSelection():void{
    if(!this.ready||this.waiting||this.selectionCount>=4)return;
    this.getUIContext().animateTo({duration:200,curve:Curve.EaseOut},()=>{this.tool='lasso';this.bubble=false;});
    this.command('ARM_APPEND');this.onInteraction();
  }
  private syncCaptionSuppression():void{this.onCaptionSuppress(this.historyOpen||this.tool==='lasso');}
  private toggleTool():void{
    if(!this.ready||this.waiting)return;
    if(this.comparing)this.previewHistory('');
    const toLasso=this.tool==='move';
    this.animateComposerDust(toLasso);
    if(toLasso){
      this.storyInputController.stopEditing();
      this.storyGeneration++;this.storyClient.cancel();this.storyWaiting=false;
      this.storyOpen=false;this.consentOffer=false;this.consentIntent='';this.storyNotesOpen=false;
      this.keyboardOpen=false;
    }
    this.getUIContext().animateTo({duration:240,curve:Curve.EaseOut},()=>{
      this.tool=toLasso?'lasso':'move';
      this.bubble=toLasso&&this.selected;
    });
    this.command('TOOL',this.tool);
    if(toLasso&&!this.selected)this.responseText=this.tr('顺着想看的地方画一圈。');
    this.onInteraction();
  }
  private submit(value:string):void{
    const text=value.trim();
    if(!text||this.waiting)return;
    if(!this.selected){this.responseText=this.tr('先轻轻圈出面容上的一处吧。');return;}
    this.requestChoice=/^[1-3]$/.test(text)?this.choices[Number(text)-1]||'':this.choices.includes(text)?text:'';
    if(/(?:不要|不用|不想|别).{0,8}(?:推荐|产品|商品|买)|no products|don.t recommend/i.test(text))this.productsDismissed=true;
    else if(/推荐|哪款|想买|recommend/i.test(text))this.productsDismissed=false;
    this.requestText=text;this.input='';this.pending=undefined;this.pendingSnapshot=undefined;this.candidateReady=false;this.question='';this.choices=[];
    this.carePreviewToken++;
    if(this.careWeek>0)this.command('CARE_PREVIEW','','',0);
    this.careWeek=0;this.careProductId='';this.careWhy='';this.careHow='';
    if(!this.cloudEnabled){
      if(this.cloudConsentDecision==='denied'){
        this.responseText=this.tr('云端对话已关闭。想再继续时，可以在设置里开启。');return;
      }
      this.consentIntent='edit';this.consentOffer=true;return;
    }
    this.capture();
  }
  private capture():void{
    this.consentOffer=false;this.consentIntent='';
    if(!CloudConsentStore.allowed(this.context))return;
    this.waiting=true;
    this.responseText=this.tr('我陪你看看这些地方…');
    this.command('CAPTURE');
  }
  private async captured(clean:ArrayBuffer,annotated:ArrayBuffer,width:number,height:number,gsView?:GsViewSnapshot):Promise<void>{
    if(!this.waiting||this.selections.length===0||!CloudConsentStore.allowed(this.context))return;
    if(!gsView||gsView.assetId!==this.assetId||gsView.frame<1){
      this.waiting=false;this.responseText=this.tr('当前画面的视角还未就绪，请停一瞬再试。');return;
    }
    const rev=this.revision;
    const id='gs-'+Date.now()+'-'+Math.floor(Math.random()*1000000);
    const snapshot:CloudSnapshot={
      schemaVersion:1,requestId:id,snapshotId:'snapshot-'+id,assetId:this.assetId,assetVersion:this.assetId,
      textureVersion:'gs-original-v1',sceneRevision:rev,regionVersion:rev,viewRevision:gsView.cameraRevision,
      view:{yaw:gsView.yaw,pitch:gsView.pitch,distance:gsView.distance,panX:0,panY:0},userText:this.requestText,
      regions:this.selections.map((item:SelectedGsRegion,index:number)=>{
        const region:CloudRegion={regionId:item.info.regionId,
            description:'用户手工圈定的第'+(index+1)+'处；请从本次干净图和编号图识别部位。'+
              (this.selectionObservations.find((o:SelectionObservation)=>o.regionId===item.info.regionId)?.area||''),semantic:'manual'};
        return region;
      }),
      layers:[],
      protectedRegionIds:[],productContextIds:this.lastProductIds.slice(),uploadAuthorized:true,
      imageWidth:width,imageHeight:height,annotatedRegionId:this.selections.length===1?this.selections[0].info.regionId:'',
      annotatedRegionIds:this.selections.map((item:SelectedGsRegion)=>item.info.regionId),
      dialogue:this.dialogue.slice(-3),resolvedChoice:this.requestChoice,responseLanguage:this.language,
      careAdviceRequested:true,dismissedProducts:this.productsDismissed
    };
    this.planner.endpoint=this.backendAddress.trim();this.planner.token=this.backendToken.trim();
    try{
      const reply=await this.planner.propose(snapshot,[clean,annotated]);
      if(!this.waiting||this.revision!==rev||!CloudConsentStore.allowed(this.context))return;
      console.info('SELF_GS_PLAN '+reply.plan.decision+' '+reply.modelEvidence.returnedModel);
      this.responseText='✧ '+reply.plan.shortMessage;this.question=reply.plan.question;this.choices=reply.plan.choices||[];
      this.selectionObservations=reply.plan.selectionObservations||[];
      const guide=reply.plan.careGuide;
      if(guide&&this.careProduct(guide.productId)){
        this.careProductId=guide.productId;this.careWhy=guide.whyHere;this.careHow=guide.howToUse;
        this.careExpanded=true;this.careWeek=0;
      }
      const productIds=reply.plan.explanationRefs.concat(guide?[guide.productId]:[]).filter((value:string,index:number,all:string[])=>all.indexOf(value)===index).slice(0,3);
      this.replyProductIds=productIds;
      if(productIds.length)this.lastProductIds=productIds;
      const fullReply=[reply.plan.shortMessage,reply.plan.question,guide?guide.whyHere+' '+guide.howToUse:''].filter((part:string)=>!!part).join(' ');
      this.dialogue.push({userText:this.requestText,reply:fullReply.slice(0,400),choices:this.choices.slice(),productIds});
      this.dialogue=this.dialogue.slice(-3);
      if(reply.plan.decision==='edit'){this.pending=reply;this.pendingSnapshot=snapshot;this.candidateReady=true;}
    }catch(error){
      console.warn('SELF_GS_PLAN_FAILED '+String(error));
      this.responseText=this.tr('这次护理建议没有接上，请再试一次。产品资料仍可在护理星图查看。');
    }finally{this.waiting=false;}
  }
  private confirm():void{
    const reply=this.pending, snapshot=this.pendingSnapshot;
    if(!reply||!snapshot||snapshot.sceneRevision!==this.revision||this.selections.length===0)return;
    const operations=reply.plan.operations;
    if(operations.length<1||operations.length>4||operations.some(op=>op.operation!=='set_digital_tint'||op.productProfileId||
      !this.selections.some((item:SelectedGsRegion)=>item.info.regionId===op.regionId)))return;
    const old=this.history||this.emptyHistory();
    if(old.groups.length>=12||old.groups.reduce((n:number,group:GsGroup)=>n+group.layers.length,0)+operations.length>16){
      this.responseText=this.tr('这颗星辰的变化记录已满；可以先整理旧记录。');return;
    }
    const groupId='group-'+Date.now();
    const layers:GsLayer[]=operations.map((op,index:number)=>{
      const item=this.selections.find((selected:SelectedGsRegion)=>selected.info.regionId===op.regionId) as SelectedGsRegion;
      const bytes=new Uint8Array(item.mask);
      const layer:GsLayer={layerId:groupId+'-'+index,regionId:op.regionId,preset:op.presetId,
        strength:PlannerClient.strength(op.intensityLevel),maskChecksum:this.checksum(bytes),
        maskBase64:new util.Base64Helper().encodeToStringSync(bytes)};
      return layer;
    });
    const group:GsGroup={groupId,label:this.requestText.slice(0,28),createdAt:Date.now(),layers,
      careGuide:reply.plan.careGuide||null};
    this.stageHistory({schemaVersion:2,assetId:old.assetId,assetBytes:old.assetBytes,
      splatCount:this.selections[0].mask.byteLength,groups:old.groups.concat([group])});
    this.pending=undefined;this.pendingSnapshot=undefined;this.candidateReady=false;
  }
  private appliedResult(action:string):void{
    try{
      if(action!=='SET_HISTORY')return;
      if(this.pendingHistory){
        const previous=this.history;
        this.history=this.pendingHistory;this.pendingHistory=undefined;this.syncTransferAvailability();
        try{this.save();}
        catch(error){this.history=previous;if(previous)this.renderHistory(previous);throw new Error(String(error));}
        this.applied=this.history.groups.length>0;this.comparing=false;this.comparisonTarget='';this.refreshHistoryDisplay();
        this.selections=[];this.selectionCount=0;this.selected=false;
        this.command('CLEAR_SELECTION');this.revision++;
        this.storyPhase='act';this.revealStoryHint();
        this.responseText=this.tr('这组变化已留在你的星辰里。转动看看，也可以逐项对比。');
      }else if(this.pendingComparison!==undefined){
        this.comparisonTarget=this.pendingComparison;this.comparing=!!this.comparisonTarget;
        this.pendingComparison=undefined;
      }
      console.info('SELF_GS_HISTORY_APPLIED '+this.history?.groups.length);
    }catch(error){this.pendingHistory=undefined;this.syncTransferAvailability();this.responseText=this.tr('变化未能稳妥保存，已回到上一次记录。');console.warn('SELF_GS_EDIT_SAVE_FAILED '+String(error));}
  }
  private undo():void{
    this.planner.cancel();this.waiting=false;this.candidateReady=false;this.pending=undefined;
    if(this.history&&this.history.groups.length){this.deleteGroup(this.history.groups[this.history.groups.length-1].groupId);}
    else this.responseText=this.tr('现在仍是原来的模样。');
  }
  private compare():void{
    if(!this.applied||this.waiting)return;
    this.previewHistory(this.comparing?'':'original');
  }
  private previewHistory(target:string):void{
    if(!this.history||this.pendingHistory)return;
    this.pendingComparison=target;
    this.renderHistory(this.history,target==='original'?'none':target);
  }
  private deleteGroup(id:string):void{
    if(!this.history||this.pendingHistory)return;
    this.stageHistory({schemaVersion:2,assetId:this.history.assetId,assetBytes:this.history.assetBytes,
      splatCount:this.history.splatCount,groups:this.history.groups.filter((group:GsGroup)=>group.groupId!==id)});
  }
  private deleteLayer(id:string):void{
    if(!this.history||this.pendingHistory)return;
    const groups=this.history.groups.map((group:GsGroup)=>{
      const revised:GsGroup={groupId:group.groupId,label:group.label,createdAt:group.createdAt,careGuide:null,
        layers:group.layers.filter((layer:GsLayer)=>layer.layerId!==id)};return revised;
    }).filter((group:GsGroup)=>group.layers.length>0);
    this.stageHistory({schemaVersion:2,assetId:this.history.assetId,assetBytes:this.history.assetBytes,
      splatCount:this.history.splatCount,groups});
  }
  private clearSelection():void{
    this.planner.cancel();this.pending=undefined;this.pendingSnapshot=undefined;this.candidateReady=false;
    this.carePreviewToken++;
    this.selections=[];this.selectionCount=0;this.selected=false;
    this.dialogue=[];this.lastProductIds=[];this.selectionObservations=[];
    this.waiting=false;this.consentOffer=false;this.consentIntent='';this.question='';this.choices=[];
    this.careProductId='';this.careWhy='';this.careHow='';this.careWeek=0;
    this.command('CLEAR_SELECTION');this.bubble=false;this.revision++;
  }
  aboutToDisappear():void{this.planner.cancel();this.storyClient.cancel();this.storyGeneration++;
    this.storyHintToken++;this.replyToken++;this.composerDustToken++;
    if(this.appWindow){this.appWindow.off('keyboardHeightChange',this.keyboardHeightListener);this.appWindow=undefined;}
    this.getUIContext().setKeyboardAvoidMode(this.previousKeyboardAvoidMode);
  }

  build(){
    Stack(){
      GaussianPortraitSurface({gaussianPath:this.gaussianPath,viewPath:this.viewPath,editCommand:this.editCommand,language:this.language,
        onReady:()=>this.viewerReady(),onFailure:(message:string)=>{this.waiting=false;this.onFailure(message);},
        onEditFailure:(message:string)=>{if(this.pendingObservationQuote){
          const quote=this.pendingObservationQuote,messageId=this.pendingObservationMessageId;
          this.pendingObservationQuote='';this.pendingObservationMessageId='';
          this.persistObservation(quote,messageId);}
          else this.editFailed(message);},
        onInteraction:()=>this.onInteraction(),
        onBackgroundTone:(light:boolean)=>this.onBackgroundTone(light),
        onSelection:(info:GsSelection,mask:ArrayBuffer)=>this.selectedRegion(info,mask),
        onCapture:(clean:ArrayBuffer,annotated:ArrayBuffer,width:number,height:number,view?:GsViewSnapshot)=>{this.captured(clean,annotated,width,height,view);},
        onViewSnapshot:(view:GsViewSnapshot)=>this.receivedView(view),
        onApplied:(action:string)=>this.appliedResult(action)}).width('100%').height('100%')
      if(this.bubble){
        Column({space:8}){
          Row(){Text('✦ SELF').fontSize(12).letterSpacing(2).fontColor('#BFD8F3').layoutWeight(1);
            StarCloseButton({diameter:30,label:this.tr('关闭'),onClose:()=>this.clearSelection()})}
          Column({space:1}){
            ForEach(this.replyLines.slice(0,this.visibleReplyLines),(line:string,index:number)=>{
              Text(line).fontSize(15).lineHeight(22).fontColor('#F1F5FF')
                .blur(index===this.visibleReplyLines-1&&this.replyBloom?4:0)
                .opacity(index===this.visibleReplyLines-1&&this.replyBloom?.7:1)
                .animation({duration:190,curve:Curve.EaseOut})
            },(_line:string,index:number)=>index.toString())
          }.alignItems(HorizontalAlign.Start).width('100%')
          if(this.careProductId&&this.careProduct(this.careProductId)){
            Column({space:5}){
              Row({space:9}){
                Image(OlayPhotoRepository.thumbnail(this.careProductId)).width(42).height(42).objectFit(ImageFit.Contain)
                Column({space:2}){
                  Text((this.careProduct(this.careProductId) as OlayDiscoveryItem).name).fontSize(12)
                    .fontColor('#F0F5FF').maxLines(1)
                  Text(this.tr('日常一小步')).fontSize(10).fontColor('#B8D2EC')
                }.alignItems(HorizontalAlign.Start).layoutWeight(1)
                Text(this.careExpanded?'⌃':'⌄').fontSize(17).fontColor('#E1EBFF')
              }.width('100%').onClick(()=>this.getUIContext().animateTo({duration:240,curve:Curve.EaseOut},()=>{
                this.careExpanded=!this.careExpanded;}))
              Text(this.careWhy).fontSize(11).lineHeight(16).fontColor('#D9E7F7')
              if(this.careExpanded){Text(this.careHow).fontSize(11).lineHeight(16).fontColor('#E5EEFA')}
              Button(this.tr('查看这款资料')).fontSize(11).fontColor('#E5EEFA')
                .backgroundColor('#344E6B').borderRadius(14)
                .onClick(()=>{this.libraryProductId=this.careProductId;this.libraryOpen=true;})
            }.padding(9).width('100%').backgroundColor('#263C58D9')
              .border({width:1,color:'#7896BA'}).borderRadius(16)
          }
          if(!this.careProductId&&this.replyProductIds.length&&OlayDiscoveryRepository.allRecords().some((p:OlayDiscoveryItem)=>p.id===this.replyProductIds[0])){
            Button(this.tr('查看这款资料')).fontSize(11).fontColor('#E5EEFA')
              .backgroundColor('#344E6B').borderRadius(14)
              .onClick(()=>{this.libraryProductId=this.replyProductIds[0];this.libraryOpen=true;})
          }
          if(this.candidateReady){Text(this.tr('✧ 数字预览 · {count} 处 · 非产品实测效果').replace('{count}',String(this.selectionCount)))
            .fontSize(11).fontColor('#B9CDE4')}
          if(this.question){Text(this.question).fontSize(14).fontColor('#DDEAFF').maxLines(2)}
          if(this.choices.length>0){Row({space:7}){ForEach(this.choices,(choice:string)=>{
            Button(choice).fontSize(12).fontColor('#EAF3FF').backgroundColor('#344C68AA').borderRadius(15).onClick(()=>this.submit(choice))
          },(choice:string)=>choice)}}
          if(this.consentOffer&&this.consentIntent==='edit'){
            Text(CloudConsentStore.introduction(this.language))
              .fontSize(12).fontColor('#BED0E6').maxLines(8)
            Row({space:8}){
              Button(this.tr('开启对话')).fontSize(13).fontColor('#F5F8FF').backgroundColor('#496581').borderRadius(17)
                .onClick(()=>this.acceptCloudIntroduction())
              Button(this.tr('现在先不用')).fontSize(13).fontColor('#D2E1F1').backgroundColor('#253B54').borderRadius(17)
                .onClick(()=>this.declineCloudIntroduction())
            }
          }else{
            TextInput({text:this.input,placeholder:this.tr(this.selectionCount>1?'例如：第一处淡一些，第二处暖一点':'想对这里说些什么？')})
              .fontSize(14).fontColor('#F4F7FF').placeholderColor('#AFC2D7').backgroundColor('#233A55DD')
              .borderRadius(17).height(42).onChange((value:string)=>this.input=value)
              .onFocus(()=>this.keyboardOpen=true).onBlur(()=>this.keyboardOpen=false)
            Row({space:8}){
              Button(this.waiting?this.tr('在想…'):this.tr('发送')).enabled(!this.waiting)
                .fontSize(13).fontColor('#F5F8FF').backgroundColor('#496581').borderRadius(17).onClick(()=>this.submit(this.input))
              if(this.candidateReady){Button(this.tr('试在面容上')).fontSize(13).fontColor('#F5F8FF')
                .backgroundColor('#6879A0').borderRadius(17).onClick(()=>this.confirm())}
            }
            if(this.selectionCount>0){Row({space:8}){
              if(this.selectionCount<4){Button(this.tr('另圈一处')).fontSize(12).fontColor('#DCEAFF')
                .backgroundColor('#243D59').borderRadius(15).onClick(()=>this.appendSelection())}
              Button(this.tr('清空圈选')).fontSize(12).fontColor('#DCEAFF')
                .backgroundColor('#243D59').borderRadius(15).onClick(()=>this.clearSelection())
            }}
          }
        }.padding(14).width(Math.min(330,this.viewportWidth-36)).backgroundColor('#D91A2D47')
          .border({width:1,color:'#657F9D'}).borderRadius(23)
          .position({x:this.bubbleLeft(),y:Math.max(58,Math.min(this.viewportHeight-
            (this.careProductId?260:168)-this.replyLines.length*22-(this.careExpanded?42:0)-
             (this.question?52:0)-(this.choices.length?40:0)-
             (this.consentOffer&&this.consentIntent==='edit'?145:0),this.anchorY*this.viewportHeight-92))})
          .transition({opacity:0,scale:{x:.92,y:.92},translate:{y:12}}).zIndex(8)
      }
      if(this.ready&&this.tool!=='lasso'){
        Column({space:3}){
          if(this.storyOpen){
            Column({space:8}){
            Row({space:9}){
              Text('✦').fontSize(17).fontColor('#D3DCFF')
              Text(this.tr('这一刻的 SELF')).fontSize(14)
                .fontWeight(FontWeight.Medium).fontColor('#F2F6FF').layoutWeight(1)
              Button(this.storyNotesOpen?this.tr('对话'):this.tr('记录'))
                .fontSize(11).fontColor('#C9DBF1').backgroundColor('#263C59').borderRadius(14)
                .onClick(()=>this.storyNotesOpen=!this.storyNotesOpen)
              StarCloseButton({diameter:30,label:this.tr('收起对话'),onClose:()=>this.closeStory()})
            }.width('100%')
            Scroll(){
              Column({space:10}){
                if(this.storyNotesOpen){
                  if(this.storyObservations.length===0){Text(this.tr('还没有留下文字。'))
                    .fontSize(13).fontColor('#C5D4EA')}
                  ForEach(this.storyObservations,(record:StoryObservation)=>{
                    Row({space:8}){
                      Text(record.userQuote).fontSize(13).lineHeight(19).fontColor('#E9F1FF').layoutWeight(1)
                      StarCloseButton({diameter:27,label:this.tr('删除这句话'),
                        onClose:()=>this.deleteObservation(record.recordId)})
                    }.padding(10).width('100%').backgroundColor('#344861B8').borderRadius(15)
                  },(record:StoryObservation)=>record.recordId)
                }else{
                  Text(this.storyReply).fontSize(14).lineHeight(21).fontColor('#EDF3FF').width('100%')
                  if(this.storyProductIds.length&&OlayDiscoveryRepository.allRecords().some((p:OlayDiscoveryItem)=>p.id===this.storyProductIds[0])){
                    Button(this.tr('看看这款资料')).fontSize(12).fontColor('#EAF2FF')
                      .backgroundColor('#304B68').borderRadius(16)
                      .onClick(()=>{this.libraryProductId=this.storyProductIds[0];this.libraryOpen=true;})
                  }
                  if(this.storyKind==='edit_entry'){
                    Button(this.tr('去圈选、再确认')).fontSize(12).fontColor('#F3F2FF')
                      .backgroundColor('#665A8E').borderRadius(17)
                      .onClick(()=>this.enterExistingEdit(this.storyLastQuote))
                  }
                  if(this.storyKind==='real_effect_boundary'){
                    Row({space:7}){
                      Button(this.tr('说说具体产品')).fontSize(12).fontColor('#EAF2FF')
                        .backgroundColor('#304B68').borderRadius(16)
                        .onClick(()=>this.storyInput=this.tr('想了解这款 OLAY 的哪一代、哪种规格？'))
                      Button(this.tr('另试数字预览')).fontSize(12).fontColor('#F2EEFF')
                        .backgroundColor('#665A8E').borderRadius(16)
                        .onClick(()=>this.enterExistingEdit(this.tr('我想试一份独立的通用数字试色，不按产品真实效果。')))
                    }
                  }
                  if(this.storyLastQuote&&this.storyKind!=='closing'){
                    Button(this.tr('留下这一刻')).fontSize(11).fontColor('#DDEBFF')
                      .backgroundColor('#344E6B').borderRadius(16).onClick(()=>this.saveStoryQuote())
                  }
                }
              }.alignItems(HorizontalAlign.Start).width('100%')
            }.width('100%').layoutWeight(1).scrollBar(BarState.Off)
            if(this.consentOffer&&this.consentIntent==='story'){
              Text(CloudConsentStore.introduction(this.language))
                .fontSize(11).lineHeight(16).fontColor('#C8D9EF')
              Row({space:8}){
                Button(this.tr('开启对话')).fontSize(12).fontColor('#F4F7FF')
                  .backgroundColor('#4B6283').borderRadius(16)
                  .onClick(()=>this.acceptCloudIntroduction())
                Button(this.tr('现在先不用')).fontSize(12).fontColor('#C9D8EB')
                  .backgroundColor('#2A4059').borderRadius(16)
                  .onClick(()=>this.declineCloudIntroduction())
              }
            }
            if(this.storyWaiting){Button(this.tr('停下这次回应')).fontSize(12)
              .fontColor('#D9E8F5').backgroundColor('#30465E').borderRadius(16)
              .onClick(()=>{this.storyGeneration++;this.storyClient.cancel();this.storyWaiting=false;
                this.storyReply=this.tr('好，这次先停在这里。');})}
            }.padding(12).width('100%').height(this.replyPanelHeight())
              .backgroundColor('#B3182D47')
              .border({width:1,color:'#708BAD'}).borderRadius(22)
              .transition({opacity:0,scale:{x:.98,y:.9},translate:{y:10}})
          }
          Row({space:8}){
            Text('✦').fontSize(17).fontColor('#CFD9FF')
            Stack({alignContent:Alignment.TopStart}){
              TextInput({text:this.storyInput,placeholder:'',controller:this.storyInputController})
                .id('personal-story-input').width('100%').height(42).fontSize(13)
                .fontColor('#F4F7FF').backgroundColor('#00000000')
                .maxLength(500).keyboardAppearance(KeyboardAppearance.DARK_IMMERSIVE)
                .onChange((value:string)=>this.storyInput=value)
                .onFocus(()=>{this.getUIContext().setKeyboardAvoidMode(KeyboardAvoidMode.NONE);
                  this.keyboardOpen=true;})
                .onBlur(()=>{this.keyboardOpen=false;
                  this.getUIContext().setKeyboardAvoidMode(this.previousKeyboardAvoidMode);})
              if(!this.storyInput&&!this.keyboardOpen){
                Row({space:0}){
                  ForEach(this.storyHint().split(''),(letter:string,index:number)=>{
                    Text(letter).fontSize(12).fontColor('#AABAD4')
                      .opacity(index<this.storyHintVisible?.73:0)
                      .blur(index<this.storyHintVisible?0:5)
                      .animation({duration:180,curve:Curve.EaseOut})
                  },(_letter:string,index:number)=>this.storyHint()+'-'+index.toString())
                }.padding({left:12}).height(42).alignItems(VerticalAlign.Center)
                  .hitTestBehavior(HitTestMode.None)
              }
            }.layoutWeight(1).height(42)
            Button(){
              if(this.storyWaiting){Text('···').fontSize(18).fontColor('#F4F7FF')}
              else{Image($rawfile('ui/story_send.svg')).width(21).height(21)}
            }.id('personal-story-send').width(42).height(42)
              .enabled(!this.storyWaiting).backgroundColor('#53698E').borderRadius(21)
              .stateStyles({pressed:{.scale({x:.91,y:.91})},normal:{.scale({x:1,y:1})}})
              .animation({duration:170,curve:Curve.EaseOut})
              .onClick(()=>{this.storyInputController.stopEditing();this.openStory();this.sendStory(this.storyInput);})
              .accessibilityText(this.tr('发送此刻的话'))
          }.padding({left:10,right:7,top:5,bottom:5}).width('100%')
            .backgroundColor('#DC1A2B45')
            .border({width:1,color:'#708BAD'}).borderRadius(27)
            .shadow({radius:10,color:'#3C10203E',offsetY:3})
        }
          .width(Math.min(this.viewportWidth-32,this.viewportWidth>=840?540:440))
          .height(this.composerHeight())
          .position({x:Math.max(16,(this.viewportWidth-Math.min(this.viewportWidth-32,this.viewportWidth>=840?540:440))/2),
            y:Math.max(75,this.composerBottom()-this.composerHeight())})
          .transition({opacity:0,scale:{x:.91,y:.84},translate:{y:12}}).zIndex(11)
      }
      if(this.composerDust){
        ForEach([0,1,2,3,4,5,6,7],(index:number)=>{
          Circle().width(2+index%3).height(2+index%3).fill(index%3===0?'#DBE6FF':'#A7BDD9')
            .opacity(this.composerDustSpread?0:.75)
            .position({x:this.viewportWidth*.5+(this.composerDustSpread?(index-3.5)*38:(index-3.5)*8),
              y:this.viewportHeight-67+(this.composerDustSpread?((index%3)-1)*23:0)})
            .hitTestBehavior(HitTestMode.None).zIndex(12)
        },(index:number)=>index.toString())
      }
      if(this.historyOpen){
        Stack(){
          List({space:9}){
            ListItem(){Column({space:4}){
              Text(this.tr('这颗星辰的变化')).fontSize(18).fontWeight(FontWeight.Medium).fontColor('#F1F6FF')
              Text(this.tr('轻轻展开，看看每一步')).fontSize(11).fontColor('#A9C2DF')
            }.alignItems(HorizontalAlign.Start).padding({right:45})}
            if(this.applied){ListItem(){Row({space:9}){
              Button(this.comparing?this.tr('看变化'):this.tr('看原样'))
                .id('personal-gs-compare').fontSize(12).fontColor('#EAF2FF')
                .backgroundColor('#385675B8').border({width:1,color:'#7697B7'}).borderRadius(17)
                .onClick(()=>this.compare())
              Button(this.tr('撤回上一步')).id('personal-gs-undo')
                .fontSize(12).fontColor('#EAF2FF').backgroundColor('#385675B8')
                .border({width:1,color:'#7697B7'}).borderRadius(17).onClick(()=>this.undo())
            }.width('100%')}}
            if(this.historyDisplay.length===0){
              ListItem(){Text(this.tr('这里还没有新的变化')).fontSize(13).fontColor('#BBD0E6').padding(12)}
            }
            ForEach(this.historyDisplay,(group:GsHistoryDisplay)=>{
              ListItem(){Column({space:9}){
                Text(group.label||this.tr('一次尝试')).fontSize(14).fontWeight(FontWeight.Medium)
                  .fontColor('#F1F6FF').maxLines(2).width('100%')
                Row({space:8}){
                  Button(this.tr('看这组')).fontSize(12).fontColor('#EEF6FF')
                    .backgroundColor('#365574').borderRadius(16).onClick(()=>this.previewHistory(group.groupId))
                  Button(this.tr('移除整组')).fontSize(12).fontColor('#D8E9FA')
                    .backgroundColor('#29425D').borderRadius(16).onClick(()=>this.deleteGroup(group.groupId))
                }.width('100%')
                ForEach(group.items,(item:GsHistoryItem,index:number)=>{
                  Row({space:7}){
                    Text((index+1)+' · '+(item.preset==='rose'?this.tr('柔玫瑰'):this.tr('暖陶棕')))
                      .fontSize(12).fontColor('#C8D9ED').layoutWeight(1)
                    Button(this.tr('对比')).fontSize(11).fontColor('#EAF3FF').backgroundColor('#365574')
                      .borderRadius(15).onClick(()=>this.previewHistory(item.layerId))
                    StarCloseButton({diameter:27,label:this.tr('移除这一项'),onClose:()=>this.deleteLayer(item.layerId)})
                  }.width('100%')
                },(item:GsHistoryItem)=>item.layerId)
                if(group.careGuide&&this.careProduct(group.careGuide.productId)){
                  Row({space:8}){
                    Image(OlayPhotoRepository.thumbnail(group.careGuide.productId)).width(42).height(42).objectFit(ImageFit.Contain)
                    Column({space:3}){
                      Text((this.careProduct(group.careGuide.productId) as OlayDiscoveryItem).name).fontSize(12).fontColor('#EBF3FF').maxLines(1)
                      Text(this.tr('✧ 养护小记')).fontSize(10).fontColor('#AFC9E3')
                    }.alignItems(HorizontalAlign.Start).layoutWeight(1)
                    Text(this.expandedCareGroup===group.groupId?'⌃':'⌄').fontSize(16).fontColor('#C6DDF4')
                  }.padding({left:4,right:6,top:6,bottom:6}).width('100%')
                    .onClick(()=>this.getUIContext().animateTo({duration:210,curve:Curve.EaseOut},()=>{
                      this.expandedCareGroup=this.expandedCareGroup===group.groupId?'':group.groupId;}))
                  if(this.expandedCareGroup===group.groupId){
                    Text(group.careGuide.whyHere).fontSize(12).lineHeight(18).fontColor('#DCEAF8')
                    Text(group.careGuide.howToUse).fontSize(12).lineHeight(18).fontColor('#DCEAF8')
                    Text(this.tr('日常护理与屏幕里的数字色彩是两件事。'))
                      .fontSize(10).fontColor('#AFC6DE')
                  }
                }else{
                  Text(this.tr('这一步先留住光色；护理小记，等遇见合适的一款再写。'))
                    .fontSize(11).fontColor('#AFC5DB')
                }
              }.padding(12).width('100%').backgroundColor('#29435CC9').border({width:1,color:'#7091B0'}).borderRadius(20)}
            },(group:GsHistoryDisplay)=>group.groupId)
            if(this.applied){ListItem(){Button(this.tr('看全部变化')).fontSize(12).fontColor('#EAF3FF')
              .backgroundColor('#365574').borderRadius(18).onClick(()=>this.previewHistory(''))}}
          }.padding(16).width('100%').height('100%').scrollBar(BarState.Off).edgeEffect(EdgeEffect.Spring)
          StarCloseButton({diameter:36,label:this.tr('关闭'),onClose:()=>{this.historyOpen=false;this.previewHistory('');}})
            .position({x:this.historyPanelWidth()-52,y:16})
        }.width(this.historyPanelWidth()).height(this.historyPanelHeight()).backgroundColor('#E912253D')
          .border({width:1,color:'#5D7998'}).borderRadius(28).shadow({radius:26,color:'#66030813',offsetY:8})
          .position({x:this.viewportWidth>=840?18:12,
            y:Math.max(80,this.viewportHeight-this.historyPanelHeight()-90)})
          .transition({opacity:0,scale:{x:.94,y:.94},translate:{y:12}}).zIndex(9)
      }
      if(this.ready&&!this.libraryOpen){
        if(!this.historyOpen){
          Button({type:ButtonType.Circle,stateEffect:false}){
            Image($rawfile('ui/portrait_history.svg')).width(29).height(29)
          }.id('personal-gs-history').width(48).height(48).borderRadius(24)
            .backgroundColor(this.historyPressed?'#DA426687':'#C8253D5B')
            .border({width:1,color:this.historyPressed?'#DFEFFF':'#7193B4'})
            .shadow({radius:this.historyPressed?13:5,color:this.historyPressed?'#7EB8DC':'#243D5B'})
            .scale({x:this.historyPressed?.93:1,y:this.historyPressed?.93:1})
            .animation({duration:170,curve:Curve.EaseOut})
            .accessibilityText(this.tr('变化记录'))
            .onTouch((event:TouchEvent)=>{this.historyPressed=event.type===TouchType.Down;})
            .onClick(()=>{this.getUIContext().animateTo({duration:210,curve:Curve.EaseOut},()=>{
              this.historyOpen=true;this.bubble=false;});})
            .position({x:18,y:Math.max(120,Math.min(this.viewportHeight*.36,
              this.viewportHeight-this.historyPanelHeight()-20))}).zIndex(7)
        }
        if(!this.historyOpen){
          Button({type:ButtonType.Capsule,stateEffect:false}){
            Row({space:8}){
              Image($rawfile('ui/portrait_care.svg')).width(24).height(24)
              Text(this.tr('护理星图')).fontSize(13).fontColor('#E8F2FF')
                .fontWeight(FontWeight.Medium)
            }
          }.id('personal-olay-library').height(52).padding({left:14,right:17})
            .backgroundColor('#D3253C59').border({width:1,color:'#7896B4'}).borderRadius(26)
            .shadow({radius:6,color:'#263D57',offsetY:2})
            .stateStyles({pressed:{.scale({x:.96,y:.96})},normal:{.scale({x:1,y:1})}})
            .animation({duration:180,curve:Curve.EaseOut})
            .onClick(()=>{this.bubble=false;this.historyOpen=false;
              this.getUIContext().animateTo({duration:220,curve:Curve.EaseOut},()=>{this.libraryOpen=true;});})
            .position({x:18,y:Math.max(150,this.viewportHeight-(this.viewportWidth>=840?160:228))}).zIndex(7)
        }
        if(!this.historyOpen){
          Button({type:ButtonType.Capsule,stateEffect:false}){
            Stack({alignContent:Alignment.Center}){
              Row({space:10}){
                Image($rawfile('ui/portrait_move.svg')).width(30).height(30)
                Text(this.tr('移动')).fontSize(15).fontWeight(FontWeight.Medium).fontColor('#F6F3FF')
              }.opacity(this.tool==='move'?1:0).scale({x:this.tool==='move'?1:.88,y:this.tool==='move'?1:.88})
                .animation({duration:220,curve:Curve.EaseOut})
              Row({space:10}){
                Image($rawfile('ui/portrait_lasso.svg')).width(30).height(30)
                Text(this.tr('圈选')).fontSize(15).fontWeight(FontWeight.Medium).fontColor('#FAF5FF')
              }.opacity(this.tool==='lasso'?1:0).scale({x:this.tool==='lasso'?1:.88,y:this.tool==='lasso'?1:.88})
                .animation({duration:220,curve:Curve.EaseOut})
            }.width(136).height(56)
          }.id('personal-gs-tool').width(136).height(56)
            .backgroundColor(this.tool==='lasso'?'#7957B3':'#294764')
            .linearGradient({angle:145,colors:this.tool==='lasso'?
              [['#EAAE91E0',0],['#E17E5DBD',.52],['#EB47377E',1]]:
              [['#DA597794',0],['#E0365272',.52],['#EC1C304B',1]]})
            .backgroundBlurStyle(BlurStyle.COMPONENT_ULTRA_THIN)
            .border({width:1,color:this.tool==='lasso'?'#E5D1FF':'#9DBAD6'}).borderRadius(28)
            .shadow({radius:this.tool==='lasso'?12:7,color:this.tool==='lasso'?'#7352A0':'#294563',offsetY:3})
            .scale({x:this.toolPressed?.96:1,y:this.toolPressed?.96:1})
            .animation({duration:190,curve:Curve.EaseOut})
            .onTouch((event:TouchEvent)=>{this.toolPressed=event.type===TouchType.Down;})
            .onClick(()=>this.toggleTool())
            .accessibilityText(this.tool==='lasso'?this.tr('当前圈选，点按切换移动'):
              this.tr('当前移动，点按切换圈选'))
            .position({x:Math.max(18,this.viewportWidth-154),
              y:Math.max(150,this.viewportHeight-(this.viewportWidth>=840?164:230))}).zIndex(7)
        }
      }
      if(this.libraryOpen){
        OlayLibrary({language:this.language,viewportWidth:this.viewportWidth,viewportHeight:this.viewportHeight,initialProductId:this.libraryProductId,
          onClose:()=>this.getUIContext().animateTo({duration:200,curve:Curve.EaseOut},()=>{this.libraryOpen=false;})})
          .position({x:this.viewportWidth>=840?18:12,
            y:Math.max(80,this.viewportHeight-(this.viewportHeight>this.viewportWidth?
              Math.min(this.viewportHeight*.74,900):Math.min(this.viewportHeight*.62,520))-90)})
          .transition({opacity:0,scale:{x:.94,y:.94},translate:{y:12}}).zIndex(12)
      }
    }.width('100%').height('100%')
  }
}
