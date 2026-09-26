import { common } from '@kit.AbilityKit';
import { fileIo as fs } from '@kit.CoreFileKit';
import { util } from '@kit.ArkTS';
import { GaussianPortraitSurface, GsSelection } from './GaussianPortraitSurface';
import { PlannerClient, CloudResponse, CloudSnapshot, CloudRegion, DialogueTurn, CloudCareGuide } from '../services/PlannerClient';
import { GsRenderLayer } from '../bridge/RendererBridge';
import { AssetStore } from '../services/AssetStore';
import { OlayLibrary } from './OlayLibrary';
import { OlayDiscoveryRepository,OlayDiscoveryItem } from '../services/OlayDiscoveryRepository';
import { OlayPhotoRepository } from '../services/OlayPhotoRepository';
import { StarCloseButton } from './StarCloseButton';

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
  @Prop cloudEnabled:boolean=false;
  @Prop backendAddress:string='http://127.0.0.1:8787';
  @Prop backendToken:string='';
  @Prop viewportWidth:number=400;
  @Prop viewportHeight:number=600;
  onReady:()=>void=()=>{};
  onFailure:(message:string)=>void=()=>{};
  onInteraction:()=>void=()=>{};
  onEnableCloud:()=>void=()=>{};
  onBackgroundTone:(light:boolean)=>void=()=>{};
  private context:common.UIAbilityContext=this.getUIContext().getHostContext() as common.UIAbilityContext;
  private assets:AssetStore=new AssetStore(this.context);
  private planner:PlannerClient=new PlannerClient();
  private selections:SelectedGsRegion[]=[];
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
  @State ready:boolean=false;
  @State tool:string='move';
  @State toolPressed:boolean=false;
  @State bubble:boolean=false;
  @State selected:boolean=false;
  @State waiting:boolean=false;
  @State consentOffer:boolean=false;
  @State candidateReady:boolean=false;
  @State applied:boolean=false;
  @State comparing:boolean=false;
  @State keyboardOpen:boolean=false;
  @State historyOpen:boolean=false;
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

  private label(zh:string,en:string):string{return this.language==='en'?en:zh;}
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
        groups:[{groupId:'legacy',label:this.label('原有试色','Previous tint'),createdAt:0,layers:[layer]}]};
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
    this.pendingHistory=next;this.renderHistory(next);
  }
  private editFailed(message:string):void{
    this.waiting=false;
    if(this.pendingHistory){this.pendingHistory=undefined;if(this.history)this.renderHistory(this.history);}
    this.pendingComparison=undefined;
    this.responseText=message;this.bubble=true;
  }
  private viewerReady():void{
    this.ready=true;this.restore();this.onReady();
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
    this.selected=true;this.candidateReady=false;
    this.anchorX=Math.max(.1,Math.min(.9,info.x));this.anchorY=Math.max(.15,Math.min(.7,info.y));
    const firstPrompts=['这一处已留下。再画可重选，也可以说说想法。',
      '光落在这里了。想换一处，直接再画一圈。','这处会跟着你的面容；想微调，还可以重画。'];
    this.bubble=true;this.responseText=existing>=0?
      this.label('这一处已经换成刚画的范围。','This area now follows your new selection.'):
      this.selections.length===1?
        this.label(firstPrompts[(this.history?.groups.length||0)%firstPrompts.length],
          'This area follows your portrait. Draw again to replace it, or tell me what you think.'):
      this.label('已经圈出'+this.selections.length+'处。可以一起告诉我每处想试的变化。',
        this.selections.length+' areas selected. Tell me what you would like for each.');
    this.question='';this.choices=[];this.revision++;this.onInteraction();
  }
  private appendSelection():void{
    if(!this.ready||this.waiting||this.selectionCount>=4)return;
    this.getUIContext().animateTo({duration:200,curve:Curve.EaseOut},()=>{this.tool='lasso';this.bubble=false;});
    this.command('ARM_APPEND');this.onInteraction();
  }
  private toggleTool():void{
    if(!this.ready||this.waiting)return;
    if(this.comparing)this.previewHistory('');
    this.getUIContext().animateTo({duration:240,curve:Curve.EaseOut},()=>{
      this.tool=this.tool==='move'?'lasso':'move';
    });
    this.command('TOOL',this.tool);
    if(this.tool==='lasso'){this.bubble=false;this.responseText=this.label('顺着想看的地方画一圈。','Circle an area you want to explore.');}
    this.onInteraction();
  }
  private submit(value:string):void{
    const text=value.trim();
    if(!text||this.waiting)return;
    if(!this.selected){this.responseText=this.label('先轻轻圈出面容上的一处吧。','First, circle an area on your portrait.');return;}
    this.requestText=text;this.input='';this.pending=undefined;this.pendingSnapshot=undefined;this.candidateReady=false;this.question='';this.choices=[];
    this.carePreviewToken++;
    if(this.careWeek>0)this.command('CARE_PREVIEW','','',0);
    this.careWeek=0;this.careProductId='';this.careWhy='';this.careHow='';
    if(!this.cloudEnabled){this.consentOffer=true;return;}
    this.capture();
  }
  private capture():void{
    this.consentOffer=false;this.waiting=true;
    this.responseText=this.label('我陪你看看这些地方…','Let me look at these areas with you…');
    this.command('CAPTURE');
  }
  private async captured(clean:ArrayBuffer,annotated:ArrayBuffer,width:number,height:number):Promise<void>{
    if(!this.waiting||this.selections.length===0)return;
    const rev=this.revision;
    const id='gs-'+Date.now()+'-'+Math.floor(Math.random()*1000000);
    const snapshot:CloudSnapshot={
      schemaVersion:1,requestId:id,snapshotId:'snapshot-'+id,assetId:this.assetId,assetVersion:this.assetId,
      textureVersion:'gs-original-v1',sceneRevision:rev,regionVersion:rev,viewRevision:0,
      view:{yaw:0,pitch:0,distance:1,panX:0,panY:0},userText:this.requestText,
      regions:this.selections.map((item:SelectedGsRegion,index:number)=>{
        const region:CloudRegion={regionId:item.info.regionId,
          description:'用户在个人立体面容上手工圈定的第'+(index+1)+'处可见表面；只支持数字颜色预览，不代表品牌产品实测效果',semantic:'manual'};
        return region;
      }),
      layers:[],
      protectedRegionIds:[],productContextIds:[],uploadAuthorized:true,
      imageWidth:width,imageHeight:height,annotatedRegionId:this.selections.length===1?this.selections[0].info.regionId:'',
      annotatedRegionIds:this.selections.map((item:SelectedGsRegion)=>item.info.regionId),
      dialogue:this.dialogue.slice(-3),responseLanguage:this.language,careAdviceRequested:true
    };
    this.planner.endpoint=this.backendAddress.trim();this.planner.token=this.backendToken.trim();
    try{
      const reply=await this.planner.propose(snapshot,[clean,annotated]);
      if(!this.waiting||this.revision!==rev)return;
      console.info('SELF_GS_PLAN '+reply.plan.decision+' '+reply.modelEvidence.returnedModel);
      this.responseText='✧ '+reply.plan.shortMessage;this.question=reply.plan.question;this.choices=reply.plan.choices||[];
      const guide=reply.plan.careGuide;
      if(guide&&this.careProduct(guide.productId)){
        this.careProductId=guide.productId;this.careWhy=guide.whyHere;this.careHow=guide.howToUse;
        this.careExpanded=false;this.careWeek=0;
      }
      this.dialogue.push({userText:this.requestText,reply:reply.plan.question||reply.plan.shortMessage,choices:this.choices.slice()});
      this.dialogue=this.dialogue.slice(-3);
      if(reply.plan.decision==='edit'){this.pending=reply;this.pendingSnapshot=snapshot;this.candidateReady=true;}
    }catch(error){
      console.warn('SELF_GS_PLAN_FAILED '+String(error));
      this.responseText=/olay|玉兰油|小白瓶|超红瓶|护肤|产品/i.test(this.requestText)?
        this.label('这款产品还没有核验过的上脸标定，不能把普通试色当作它的真实效果。','This product has no verified appearance calibration, so a digital tint cannot stand in for its real effect.'):
        this.label('这次还没能准备好建议，面容仍保持原样。','I could not prepare a suggestion this time. Your portrait is unchanged.');
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
      this.responseText=this.label('这颗星辰的变化记录已满；可以先整理旧记录。','This portrait has reached its edit history limit.');return;
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
        this.history=this.pendingHistory;this.pendingHistory=undefined;
        try{this.save();}
        catch(error){this.history=previous;if(previous)this.renderHistory(previous);throw new Error(String(error));}
        this.applied=this.history.groups.length>0;this.comparing=false;this.comparisonTarget='';this.refreshHistoryDisplay();
        this.selections=[];this.selectionCount=0;this.selected=false;
        this.command('CLEAR_SELECTION');this.revision++;
        this.responseText=this.label('这组变化已留在你的星辰里。转动看看，也可以逐项对比。',
          'These changes are saved with your portrait. Turn and compare each one.');
      }else if(this.pendingComparison!==undefined){
        this.comparisonTarget=this.pendingComparison;this.comparing=!!this.comparisonTarget;
        this.pendingComparison=undefined;
      }
      console.info('SELF_GS_HISTORY_APPLIED '+this.history?.groups.length);
    }catch(error){this.pendingHistory=undefined;this.responseText=this.label('变化未能稳妥保存，已回到上一次记录。','Could not save this change; the previous history is restored.');console.warn('SELF_GS_EDIT_SAVE_FAILED '+String(error));}
  }
  private undo():void{
    this.planner.cancel();this.waiting=false;this.candidateReady=false;this.pending=undefined;
    if(this.history&&this.history.groups.length){this.deleteGroup(this.history.groups[this.history.groups.length-1].groupId);}
    else this.responseText=this.label('现在仍是原来的模样。','Your portrait is still unchanged.');
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
    this.waiting=false;this.consentOffer=false;this.question='';this.choices=[];
    this.careProductId='';this.careWhy='';this.careHow='';this.careWeek=0;
    this.command('CLEAR_SELECTION');this.bubble=false;this.revision++;
  }
  aboutToDisappear():void{this.planner.cancel();this.replyToken++;}

  build(){
    Stack(){
      GaussianPortraitSurface({gaussianPath:this.gaussianPath,viewPath:this.viewPath,editCommand:this.editCommand,
        onReady:()=>this.viewerReady(),onFailure:(message:string)=>{this.waiting=false;this.onFailure(message);},
        onEditFailure:(message:string)=>this.editFailed(message),
        onInteraction:()=>this.onInteraction(),
        onBackgroundTone:(light:boolean)=>this.onBackgroundTone(light),
        onSelection:(info:GsSelection,mask:ArrayBuffer)=>this.selectedRegion(info,mask),
        onCapture:(clean:ArrayBuffer,annotated:ArrayBuffer,width:number,height:number)=>{this.captured(clean,annotated,width,height);},
        onApplied:(action:string)=>this.appliedResult(action)}).width('100%').height('100%')
      if(this.bubble){
        Column({space:8}){
          Row(){Text('✦ SELF').fontSize(12).letterSpacing(2).fontColor('#BFD8F3').layoutWeight(1);
            StarCloseButton({diameter:30,label:this.label('关闭','Close'),onClose:()=>this.clearSelection()})}
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
                  Text(this.label('日常一小步','A small care step')).fontSize(10).fontColor('#B8D2EC')
                }.alignItems(HorizontalAlign.Start).layoutWeight(1)
                Text(this.careExpanded?'⌃':'⌄').fontSize(17).fontColor('#E1EBFF')
              }.width('100%').onClick(()=>this.getUIContext().animateTo({duration:240,curve:Curve.EaseOut},()=>{
                this.careExpanded=!this.careExpanded;}))
              Text(this.careWhy).fontSize(11).lineHeight(16).fontColor('#D9E7F7')
              if(this.careExpanded){Text(this.careHow).fontSize(11).lineHeight(16).fontColor('#E5EEFA')}
              Text(this.label('面容观察 · '+(this.careWeek===0?'现在':'第 '+this.careWeek+' 周'),
                'Portrait scenario · '+(this.careWeek===0?'now':'week '+this.careWeek)))
                .fontSize(11).fontColor('#C6D8F0')
              Slider({value:this.careWeek,min:0,max:8,step:1}).blockColor('#DEE8FF').selectedColor('#8C8CCB')
                .onChange((value:number)=>this.setCareWeek(Math.round(value)))
              Text(this.label('仅是可撤销的情景示意，不预测这款产品的疗效或时间。',
                'Reversible visual scenario, not a prediction of this product’s effect or timing.'))
                .fontSize(10).fontColor('#B4C7DC').maxLines(2)
            }.padding(9).width('100%').backgroundColor('#263C58D9')
              .border({width:1,color:'#7896BA'}).borderRadius(16)
          }
          if(this.candidateReady){Text(this.label('✧ 数字预览 · '+this.selectionCount+' 处 · 非产品实测效果',
            '✧ Digital preview · '+this.selectionCount+' areas · not a product effect'))
            .fontSize(11).fontColor('#B9CDE4')}
          if(this.question){Text(this.question).fontSize(14).fontColor('#DDEAFF').maxLines(2)}
          if(this.choices.length>0){Row({space:7}){ForEach(this.choices,(choice:string)=>{
            Button(choice).fontSize(12).fontColor('#EAF3FF').backgroundColor('#344C68AA').borderRadius(15).onClick(()=>this.submit(choice))
          },(choice:string)=>choice)}}
          if(this.consentOffer){
            Text(this.label('这次会发送当前静态模型画面给 DeepSeek；原模型不上传。','This sends the current still view to DeepSeek. The model file stays here.'))
              .fontSize(12).fontColor('#BED0E6').maxLines(3)
            Row({space:8}){
              Button(this.label('允许这次发送','Send this view')).fontSize(13).fontColor('#F5F8FF').backgroundColor('#496581').borderRadius(17)
                .onClick(()=>{this.onEnableCloud();this.capture();})
              Button(this.label('先不发送','Not now')).fontSize(13).fontColor('#D2E1F1').backgroundColor('#253B54').borderRadius(17)
                .onClick(()=>{this.consentOffer=false;this.responseText=this.label('好，画面留在这里。','Okay. The portrait stays here.');})
            }
          }else{
            TextInput({text:this.input,placeholder:this.label(this.selectionCount>1?'例如：第一处淡一些，第二处暖一点':'想对这里说些什么？',
              this.selectionCount>1?'For example: softer on one, warmer on two':'What would you like to try?')})
              .fontSize(14).fontColor('#F4F7FF').placeholderColor('#AFC2D7').backgroundColor('#233A55DD')
              .borderRadius(17).height(42).onChange((value:string)=>this.input=value)
              .onFocus(()=>this.keyboardOpen=true).onBlur(()=>this.keyboardOpen=false)
            Row({space:8}){
              Button(this.waiting?this.label('在想…','Thinking…'):this.label('发送','Send')).enabled(!this.waiting)
                .fontSize(13).fontColor('#F5F8FF').backgroundColor('#496581').borderRadius(17).onClick(()=>this.submit(this.input))
              if(this.candidateReady){Button(this.label('试在面容上','Preview on portrait')).fontSize(13).fontColor('#F5F8FF')
                .backgroundColor('#6879A0').borderRadius(17).onClick(()=>this.confirm())}
            }
            if(this.selectionCount>0){Row({space:8}){
              if(this.selectionCount<4){Button(this.label('另圈一处','Add another')).fontSize(12).fontColor('#DCEAFF')
                .backgroundColor('#243D59').borderRadius(15).onClick(()=>this.appendSelection())}
              Button(this.label('清空圈选','Clear selections')).fontSize(12).fontColor('#DCEAFF')
                .backgroundColor('#243D59').borderRadius(15).onClick(()=>this.clearSelection())
            }}
          }
        }.padding(14).width(Math.min(330,this.viewportWidth-36)).backgroundColor('#D91A2D47')
          .border({width:1,color:'#657F9D'}).borderRadius(23)
          .position({x:this.bubbleLeft(),y:Math.max(58,Math.min(this.viewportHeight-
            (this.careProductId?342:168)-this.replyLines.length*22-(this.careExpanded?42:0)-
            (this.question?52:0)-(this.choices.length?40:0),this.anchorY*this.viewportHeight-92))})
          .transition({opacity:0,scale:{x:.92,y:.92},translate:{y:12}}).zIndex(8)
      }
      if(this.historyOpen){
        Stack(){
          List({space:9}){
            ListItem(){Column({space:4}){
              Text(this.label('这颗星辰的变化','Changes on this portrait')).fontSize(18).fontWeight(FontWeight.Medium).fontColor('#F1F6FF')
              Text(this.label('轻轻展开，看看每一步','Open a moment to see more')).fontSize(11).fontColor('#A9C2DF')
            }.alignItems(HorizontalAlign.Start).padding({right:45})}
            if(this.applied){ListItem(){Row({space:9}){
              Button(this.comparing?this.label('看变化','Show changes'):this.label('看原样','Show original'))
                .id('personal-gs-compare').fontSize(12).fontColor('#EAF2FF')
                .backgroundColor('#385675B8').border({width:1,color:'#7697B7'}).borderRadius(17)
                .onClick(()=>this.compare())
              Button(this.label('撤回上一步','Undo last')).id('personal-gs-undo')
                .fontSize(12).fontColor('#EAF2FF').backgroundColor('#385675B8')
                .border({width:1,color:'#7697B7'}).borderRadius(17).onClick(()=>this.undo())
            }.width('100%')}}
            if(this.historyDisplay.length===0){
              ListItem(){Text(this.label('这里还没有新的变化','No changes yet')).fontSize(13).fontColor('#BBD0E6').padding(12)}
            }
            ForEach(this.historyDisplay,(group:GsHistoryDisplay)=>{
              ListItem(){Column({space:9}){
                Text(group.label||this.label('一次尝试','One exploration')).fontSize(14).fontWeight(FontWeight.Medium)
                  .fontColor('#F1F6FF').maxLines(2).width('100%')
                Row({space:8}){
                  Button(this.label('看这组','View group')).fontSize(12).fontColor('#EEF6FF')
                    .backgroundColor('#365574').borderRadius(16).onClick(()=>this.previewHistory(group.groupId))
                  Button(this.label('移除整组','Remove group')).fontSize(12).fontColor('#D8E9FA')
                    .backgroundColor('#29425D').borderRadius(16).onClick(()=>this.deleteGroup(group.groupId))
                }.width('100%')
                ForEach(group.items,(item:GsHistoryItem,index:number)=>{
                  Row({space:7}){
                    Text((index+1)+' · '+(item.preset==='rose'?this.label('柔玫瑰','Muted pink'):this.label('暖陶棕','Warm clay')))
                      .fontSize(12).fontColor('#C8D9ED').layoutWeight(1)
                    Button(this.label('对比','Compare')).fontSize(11).fontColor('#EAF3FF').backgroundColor('#365574')
                      .borderRadius(15).onClick(()=>this.previewHistory(item.layerId))
                    StarCloseButton({diameter:27,label:this.label('移除这一项','Remove layer'),onClose:()=>this.deleteLayer(item.layerId)})
                  }.width('100%')
                },(item:GsHistoryItem)=>item.layerId)
                if(group.careGuide&&this.careProduct(group.careGuide.productId)){
                  Row({space:8}){
                    Image(OlayPhotoRepository.thumbnail(group.careGuide.productId)).width(42).height(42).objectFit(ImageFit.Contain)
                    Column({space:3}){
                      Text((this.careProduct(group.careGuide.productId) as OlayDiscoveryItem).name).fontSize(12).fontColor('#EBF3FF').maxLines(1)
                      Text(this.label('✧ 养护小记','✧ Care notes')).fontSize(10).fontColor('#AFC9E3')
                    }.alignItems(HorizontalAlign.Start).layoutWeight(1)
                    Text(this.expandedCareGroup===group.groupId?'⌃':'⌄').fontSize(16).fontColor('#C6DDF4')
                  }.padding({left:4,right:6,top:6,bottom:6}).width('100%')
                    .onClick(()=>this.getUIContext().animateTo({duration:210,curve:Curve.EaseOut},()=>{
                      this.expandedCareGroup=this.expandedCareGroup===group.groupId?'':group.groupId;}))
                  if(this.expandedCareGroup===group.groupId){
                    Text(group.careGuide.whyHere).fontSize(12).lineHeight(18).fontColor('#DCEAF8')
                    Text(group.careGuide.howToUse).fontSize(12).lineHeight(18).fontColor('#DCEAF8')
                    Text(this.label('日常护理与屏幕里的数字色彩是两件事。','Daily care and the digital colour are separate.'))
                      .fontSize(10).fontColor('#AFC6DE')
                  }
                }else{
                  Text(this.label('这一步先留住光色；护理小记，等遇见合适的一款再写。',
                    'This step keeps the colour; a care note can wait for the right match.'))
                    .fontSize(11).fontColor('#AFC5DB')
                }
              }.padding(12).width('100%').backgroundColor('#29435CC9').border({width:1,color:'#7091B0'}).borderRadius(20)}
            },(group:GsHistoryDisplay)=>group.groupId)
            if(this.applied){ListItem(){Button(this.label('看全部变化','Show all')).fontSize(12).fontColor('#EAF3FF')
              .backgroundColor('#365574').borderRadius(18).onClick(()=>this.previewHistory(''))}}
          }.padding(16).width('100%').height('100%').scrollBar(BarState.Off).edgeEffect(EdgeEffect.Spring)
          StarCloseButton({diameter:36,label:this.label('关闭','Close'),onClose:()=>{this.historyOpen=false;this.previewHistory('');}})
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
            .accessibilityText(this.label('变化记录','Changes'))
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
              Text(this.label('护理星图','Care atlas')).fontSize(13).fontColor('#E8F2FF')
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
                Text(this.label('移动','Move')).fontSize(15).fontWeight(FontWeight.Medium).fontColor('#F6F3FF')
              }.opacity(this.tool==='move'?1:0).scale({x:this.tool==='move'?1:.88,y:this.tool==='move'?1:.88})
                .animation({duration:220,curve:Curve.EaseOut})
              Row({space:10}){
                Image($rawfile('ui/portrait_lasso.svg')).width(30).height(30)
                Text(this.label('圈选','Select')).fontSize(15).fontWeight(FontWeight.Medium).fontColor('#FAF5FF')
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
            .accessibilityText(this.tool==='lasso'?this.label('当前圈选，点按切换移动','Selection mode, tap to move'):
              this.label('当前移动，点按切换圈选','Move mode, tap to select'))
            .position({x:Math.max(18,this.viewportWidth-154),
              y:Math.max(150,this.viewportHeight-(this.viewportWidth>=840?164:230))}).zIndex(7)
        }
      }
      if(this.libraryOpen){
        OlayLibrary({language:this.language,viewportWidth:this.viewportWidth,viewportHeight:this.viewportHeight,
          onClose:()=>this.getUIContext().animateTo({duration:200,curve:Curve.EaseOut},()=>{this.libraryOpen=false;})})
          .position({x:this.viewportWidth>=840?18:12,
            y:Math.max(80,this.viewportHeight-(this.viewportHeight>this.viewportWidth?
              Math.min(this.viewportHeight*.74,900):Math.min(this.viewportHeight*.62,520))-90)})
          .transition({opacity:0,scale:{x:.94,y:.94},translate:{y:12}}).zIndex(12)
      }
    }.width('100%').height('100%')
  }
}
