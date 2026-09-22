import { NativeMirrorSurface } from './NativeMirrorSurface';
import { CameraCaptureView } from './CameraCaptureView';
import { ProductCard } from './ProductCard';
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
import { AmbiencePreference } from '../services/AmbiencePreference';

@Extend(Button)
function softButton(){
  .height(48).padding({left:8,right:8}).fontSize(15).fontColor('#50445F').backgroundColor('#B8FFFFFF').borderRadius(24).border({width:1,color:'#D6FFFFFF'})
}

@Entry
@Component
struct SelfMirrorPage {
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
  @State cameraLive:boolean=false;
  @State showBeginning:boolean=true;
  @State replySources:string[]=[];
  @State productOpen:boolean=false;
  @State productSelection:ProductRecord=ProductRepository.records()[0];
  @State musicOn:boolean=false;
  @State audioState:string='off';
  @State motion:boolean=true;
  @State palette:string='quiet';
  @State followChat:boolean=true;
  @State lastUtterance:string='';
  @State replyScale:number=1;
  @State replyOpacity:number=1;
  @StorageLink('selfForeground') @Watch('foregroundChanged') foreground:boolean=true;
  @State ready: boolean = false;
  @State selected: string = '';
  @State applied: boolean = false;
  @State busy: boolean = false;
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
  @State uploadOffer:boolean=false;
  @State choices:string[]=[];
  @State replyQuestion:string='';
  private replyQuestionKey:string='';
  private dialogue:DialogueTurn[]=[];
  private cloudGeneration:number=0;
  @State backendAddress:string='http://127.0.0.1:8787';
  @State backendToken:string='';
  private pendingCloudText:string='';
  private lastModelProductIds:string[]=[];
  private bridge: NativeRendererPort = new NativeRendererPort();
  private context: common.UIAbilityContext = this.getUIContext().getHostContext() as common.UIAbilityContext;
  private assets: AssetStore = new AssetStore(this.context);
  private works: WorkspaceStore = new WorkspaceStore(this.context,this.assets);
  private audio:AmbientAudio=new AmbientAudio(this.context);
  private session: SessionStore = new SessionStore();
  private previousTool: string = 'NAVIGATE';
  private timer: number = -1;
  private restoreRequest: string = '';
  private restoreNotice:string='';
  private previousSession: SessionStore | undefined = undefined;

  aboutToAppear(): void {
    this.bridge.onSelectionAnchor=(x:number,y:number,halfWidth:number)=>{this.focusX=x;this.focusY=y;this.focusHalfWidth=halfWidth;};
    this.bridge.onToolChanged=(name:string)=>{this.tool=name;this.focusOpen=false;};
    this.audio.onStatus=(state:string)=>{this.audioState=state;if(this.context.applicationInfo.debug)console.info('SELF_AUDIO_STATE '+state);if(state==='error'){this.musicOn=false;this.subtitle='音乐暂时无法播放，你可以继续安静地使用镜面。';}};

    this.assets.registerRaw('sample-lee','assets/sample-head.glb');
    for(const name of ['lip','editable','protectionTest']){
      this.assets.registerRaw(name,'assets/'+name+'.mask');
      const r:RegionRecord={regionId:name,assetId:this.session.assetId,assetVersion:this.session.assetVersion,width:1024,height:1024,semantic:name==='lip'?'confirmed-lips':'manual',fileName:name+'.mask'};
      this.session.regions.push(r);
    }
    this.works.loadPreference(this.session);this.labels();
    this.bridge.onMessage=(m:Envelope)=>this.receive(m);
    this.bridge.onBytes=(kind:string,bytes:ArrayBuffer)=>{
      try{
        if(kind==='selection'){
          if(bytes.byteLength!==this.session.width*this.session.height)throw new Error('蒙版尺寸不一致');
          if(!new Uint8Array(bytes).some((v:number)=>v>0))throw new Error('这里没有选到面容，请在可见区域重新圈画');
          const id='region-'+Date.now();const fileName=this.assets.saveMask(id,bytes);
          const r:RegionRecord={regionId:id,assetId:this.session.assetId,assetVersion:this.session.assetVersion,width:this.session.width,height:this.session.height,semantic:'manual',fileName};
          this.session.regions.push(r);this.session.regionVersion++;this.session.sceneRevision++;this.bridge.sendBytes('mask:'+id,new Uint8Array(bytes));this.selected=id;
          this.showBeginning=false;this.dialogue=[];this.choices=[];this.uploadOffer=false;this.pendingCloudText='';this.productOpen=false;this.replySources=[];this.lastModelProductIds=[];this.getUIContext().animateTo({duration:this.motion?280:0,curve:Curve.EaseOut},()=>{this.focusOpen=true;});this.tool='NAVIGATE';this.bridge.send('SET_TOOL',{tool:'NAVIGATE'});this.subtitle='想说说这里，还是试一点变化？也可以就这样。';console.info('SELF_SELECTION_SAVED '+id+' '+bytes.byteLength);
        }
        if(kind==='png'){
          const p=new Uint8Array(bytes);if(p[0]!==137||p[1]!==80||p[2]!==78||p[3]!==71)throw new Error('PNG 数据无效');
          this.assets.writeAtomic(this.context.filesDir+'/self-export.png',bytes);this.busy=false;this.subtitle='PNG 已保存到应用私有目录';console.info('SELF_EXPORT_SAVED '+bytes.byteLength);
        }
        if(kind==='echo'){const p=new Uint8Array(bytes);console.info('SELF_BINARY_ROUNDTRIP '+(p.length===65539&&p.every((v:number,i:number)=>v===i%256)));}
      }catch(e){this.fail(String(e));}
    };
  }
  private fail(message:string):void{this.busy=false;this.subtitle=message;console.error('SELF_ERROR '+message);}
  private async requestCloud():Promise<void>{
    if(this.cloudWaiting||!this.pendingCloudText||!this.cloudSessionEnabled)return;
    const generation=++this.cloudGeneration;const input=this.pendingCloudText;this.pendingCloudText='';this.planner.endpoint=this.backendAddress.trim();this.planner.token=this.backendToken.trim();
    if(this.detail)this.close();this.uploadOffer=false;this.cloudWaiting=true;this.subtitle='让我想想，怎么更贴近你的想法…';
    const snapshot=this.planner.snapshot(this.session,input);snapshot.productContextIds=this.lastModelProductIds.slice();
    snapshot.dialogue=this.dialogue.slice(-3);
    if(/^[1-3]$/.test(input)&&this.choices.length>=Number(input))snapshot.resolvedChoice=this.choices[Number(input)-1];
    else if(this.choices.includes(input))snapshot.resolvedChoice=input;
    this.choices=[];
    try{const regionId=this.selected||(this.session.sourceKind==='MESH'?'lip':'');const capture=await this.bridge.capture(regionId);snapshot.view=capture.view;snapshot.imageWidth=capture.width;snapshot.imageHeight=capture.height;snapshot.annotatedRegionId=regionId;
      snapshot.regions=snapshot.regions.filter((r)=>r.regionId===regionId||snapshot.layers.some((l)=>l.regionId===r.regionId)||snapshot.protectedRegionIds.includes(r.regionId));
      if(this.session.sceneRevision!==snapshot.sceneRevision||this.session.regionVersion!==snapshot.regionVersion)throw new Error('作品状态已改变，请重新提出请求');
      const response=await this.planner.propose(snapshot,capture.images);
      if(!this.cloudWaiting||generation!==this.cloudGeneration)return;
      if(this.session.pending||this.session.assetId!==snapshot.assetId||this.session.assetVersion!==snapshot.assetVersion||this.session.sceneRevision!==snapshot.sceneRevision||this.session.regionVersion!==snapshot.regionVersion)throw new Error('等待期间作品或规则已改变，这份候选不会执行');
      this.subtitle=response.plan.shortMessage;this.replySources=response.plan.explanationRefs;this.lastModelProductIds=response.plan.explanationRefs.slice();
      this.choices=response.plan.choices||[];
      this.replyQuestion=response.plan.question;this.replyQuestionKey=response.plan.shortMessage;
      this.dialogue.push({userText:input,reply:response.plan.question||response.plan.shortMessage,choices:this.choices.slice()});this.dialogue=this.dialogue.slice(-3);
      if(this.replySources.length>0)this.showProduct(this.replySources[0]);
      if(response.plan.decision==='edit'){
        const op=response.plan.operations[0];
        const region=this.session.regions.find((r:RegionRecord)=>r.regionId===op.regionId);
        const plan=this.session.propose(region?.semantic==='confirmed-lips'?'lipTint':'localTint',op.regionId,op.presetId,PlannerClient.strength(op.intensityLevel));
        plan.targetLayerId=op.layerId;plan.removeLayer=op.operation==='remove_effect';plan.plannerSource='DeepSeek · '+response.modelEvidence.returnedModel;plan.snapshotId=snapshot.snapshotId;
        this.candidate=response.plan.shortMessage+(this.session.protection?' · 将保留已保护的范围':'');
        // A precise adjustment to an existing authorized layer needs no repeated confirmation.
        if(op.operation==='set_effect_level'&&op.layerId&&!this.session.protection&&/淡一点|浅一点|降低|深一点|浓一点/.test(input))this.applyCandidate();
      }
    }catch(e){if(generation!==this.cloudGeneration)return;console.warn('SELF_CLOUD_FAILED '+String(e));this.subtitle='这次没能准备好建议，我们稍后再试。画面还好好地留着。';}
    finally{if(generation===this.cloudGeneration)this.cloudWaiting=false;}
  }
  private receive(m:Envelope):void{
    if(this.context.applicationInfo.debug)console.info('SELF_EVENT '+JSON.stringify(m));
    if(m.type==='INITIALIZED')this.loadSource().catch((e:Error)=>this.fail(e.message));
    if(m.type==='VIEW_CHANGED'&&m.payload.view){const v=m.payload.view;if([v.yaw,v.pitch,v.distance,v.panX,v.panY].every((n:number)=>Number.isFinite(n))){this.session.view=v;this.session.viewRevision++;}}
    if(m.type==='ASSET_REGISTERED'){this.session.width=m.payload.width||1024;this.session.height=m.payload.height||1024;this.previousSession=undefined;}
    if(m.type==='RENDER_SUCCEEDED'){
      if(this.session.succeeded(m.requestId,m.revision)){this.busy=false;this.subtitle='这一点变化已经做好了，喜欢就留下。';this.labels();}
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
    this.productOpen=false;this.replySources=[];
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
    this.bill=this.session.operations.map((o:EditOperation)=>(o.kind==='lipTint'?'唇色':'局部颜色')+' · '+(o.presetId==='rose'?'柔玫瑰':'暖陶棕')+' · '+Math.round(o.absoluteStrength*100)+'% · '+(o.plannerSource||'本地操作'));
    this.protectedLabel=this.session.protection?(this.session.protection.anchorOperations.length?'保护已确认的当前效果':'保护原始外观')+(this.session.protection.persistent?' · 长期':' · 本次'):'';
  }
  private askModel(input:string,regionId:string=''):void{
    if(this.busy||this.cloudWaiting)return;
    this.productOpen=false;this.replySources=[];
    if(regionId&&regionId!==this.selected){this.selected=regionId;this.dialogue=[];this.choices=[];this.lastModelProductIds=[];}
    this.session.candidate=undefined;this.candidate='';this.pendingCloudText=input;this.lastUtterance=input;
    if(this.cloudSessionEnabled)this.requestCloud();else this.uploadOffer=true;
  }
  private suggest(lip:boolean):void{
    const id=lip&&this.session.sourceKind==='MESH'?'lip':this.selected;
    if(!id){this.subtitle='可以先轻轻圈出这里，再告诉我你的想法。';return;}
    this.askModel(lip?'我想在已确认的嘴唇范围尝试轻柔的唇色，请提出一个候选。':'我想看看圈出的这里有什么轻柔的变化。先问我一个简单的问题，不默认上色，不推荐产品。',id);
  }
  private applyCandidate(allowProtectedOnce:boolean=false):void{
    try{if(!this.session.candidate)return;this.session.authorize(this.session.candidate.planId,allowProtectedOnce);this.candidate='';this.busy=true;this.sendSnapshot();}catch(e){this.fail(String(e));}
  }
  private adjust(lighter:boolean):void{
    const last=this.session.operations[this.session.operations.length-1];
    if(!last){this.subtitle='等你选好想尝试的变化，我们再慢慢调整。';return;}
    this.askModel(lighter?'请把最后一项已生效的颜色调淡一级，保持区域和预设不变。':'请为最后一项颜色提议另一个柔和预设，范围不变。',last.regionId);
  }
  private command():void{
    this.showBeginning=false;const input=this.text.trim();if(!input)return;this.getUIContext().getFocusController().clearFocus();this.productOpen=false;this.replySources=[];this.lastUtterance=input;const intent=PlannerService.plan(input);this.text='';
    const mood=this.followChat?AmbiencePreference.fromText(input):undefined;
    if(mood){this.palette=mood;this.setAtmosphere();if(this.musicOn)this.audio.configure(true,mood);}
    if(!['musicOn','musicOff','apply','undo','redo','reset','protect','preference','products','observe','cancel','urgentSupport'].includes(intent.action)){this.askModel(input);return;}
    if(intent.action==='urgentSupport'){this.session.candidate=undefined;this.candidate='';this.support='';this.subtitle=intent.text;this.open('求助支持');}
    else if(intent.action==='musicOn'){this.toggleMusic(true);this.subtitle='留一点轻柔的声音陪你。随时可以关闭，也可以自己选一种氛围。';}
    else if(intent.action==='musicOff'){this.toggleMusic(false);this.subtitle='音乐已关闭。按你舒服的方式来。';}
    else if(intent.action==='observe'){this.session.candidate=undefined;this.candidate='';this.subtitle='可以转一转，看看不同角度的自己。保留现在的样子，也是完整的选择。';}
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
  private toggleMusic(enabled:boolean):void{this.musicOn=enabled;this.audio.configure(enabled,this.palette);}
  private setAtmosphere():void{if(this.bridge.ready)this.bridge.send('SET_ATMOSPHERE',{motion:this.motion&&this.foreground,palette:this.palette});}
  private chooseAtmosphere(mode:string):void{this.palette=mode;this.setAtmosphere();if(this.musicOn)this.audio.configure(true,mode);}
  private foregroundChanged():void{this.bridge.foreground(this.foreground);this.audio.visibility(this.foreground);this.setAtmosphere();if(!this.foreground&&this.timer>=0){clearInterval(this.timer);this.timer=-1;this.playing=false;}}
  private replyChanged():void{if(!this.motion)return;this.replyScale=.98;this.replyOpacity=.75;this.getUIContext().animateTo({duration:320,curve:Curve.EaseOut},()=>{this.replyScale=1;this.replyOpacity=1;});}
  private undo(direction:number):void{this.lastModelProductIds=[];this.productOpen=false;this.replySources=[];try{this.session.replay(direction);this.busy=true;this.sendSnapshot();}catch(e){this.fail(String(e));}}
  private reset():void{this.lastModelProductIds=[];this.productOpen=false;this.replySources=[];try{this.session.reset();this.busy=true;this.sendSnapshot();}catch(e){this.fail(String(e));}}
  private switchTool(next:string):void{if(this.busy)return;this.showBeginning=false;this.tool=this.tool===next?'NAVIGATE':next;this.bridge.send('SET_TOOL',{tool:this.tool});}
  private showProduct(id:string=''):void{if(!id||!this.replySources.includes(id)){this.askModel('我想了解与我关注的问题相关的OLAY产品，请先询问我的具体需求，不要默认推荐产品或修改面容。');return;}if(this.detail)this.close();const found=ProductRepository.records().find((p:ProductRecord)=>p.productId===id);if(found)this.productSelection=found;this.getUIContext().animateTo({duration:this.motion?300:0,curve:Curve.EaseOut},()=>{this.productOpen=true;});}
  private chooseProduct(direction:number):void{const all=ProductRepository.records().filter((p:ProductRecord)=>this.replySources.includes(p.productId));if(!all.length)return;const index=all.findIndex((p:ProductRecord)=>p.productId===this.productSelection.productId);this.productSelection=all[(index+direction+all.length)%all.length];}
  private open(name:string):void{if(this.busy)return;if(name==='产品资料'){this.showProduct();return;}this.previousTool=this.tool;this.detail=name;if(name==='拍摄面容')this.captures=new CaptureService(this.context).list();this.bridge.send('SET_TOOL',{tool:'DETAIL'});this.workItems=this.works.list();this.note=this.works.readNote();}
  private close():void{this.cameraLive=false;if(this.timer>=0)clearInterval(this.timer);this.timer=-1;this.playing=false;this.detail='';this.tool=this.previousTool;this.bridge.send('SET_TOOL',{tool:this.tool});}
  private protect(current:boolean,persistent:boolean):void{
    try{this.session.protect(this.selected,current,persistent);this.sendSnapshot();this.labels();this.close();
      if(persistent)this.works.savePreference(this.session).then(()=>{this.subtitle='已明确保存长期偏好';this.labels();}).catch((e:Error)=>this.fail(e.message));
      else this.subtitle=current?'仅本次保留这里当前的效果':'仅本次保留这里原始的样子';
    }catch(e){this.fail(String(e));}
  }
  private async recordCapture():Promise<void>{
    try{this.captureStatus='正在打开系统相机…';const capture=await new CaptureService(this.context).record();this.captures=new CaptureService(this.context).list();this.captureStatus=capture?'视频已私密保存。尚未生成个人3D模型，原作品保持不变。':'已取消拍摄，没有更换当前作品。';}
    catch(e){this.captureStatus='相机暂未完成：'+(e as Error).message;}
  }
  private async checkReconstruction():Promise<void>{
    try{this.captureStatus=await this.bridge.reconstructionSupport();}catch(e){this.captureStatus='设备能力检查失败：'+String(e);}
  }
  private async importPhoto():Promise<void>{
    try{const photo=await this.assets.pickPhoto();if(!photo){this.subtitle='已取消导入，当前作品不变';return;}
      const s=new SessionStore();s.assetId=photo.id;s.assetVersion=photo.id+'-v1';s.sourceKind='PHOTO';s.sourceFile=photo.path;s.textureVersion=s.assetVersion;
      this.previousSession=this.session;this.session=s;this.bridge.assetId=s.assetId;this.bridge.assetVersion=s.assetVersion;this.bridge.revision=0;this.ready=false;this.busy=true;this.selected='';this.candidate='';this.identity='个人照片 · 本地处理';this.close();this.labels();this.bridge.send('INIT',{});this.subtitle='原图保留；先圈选，再试局部颜色';
    }catch(e){this.fail(String(e));}
  }
  private async saveWork():Promise<void>{try{this.session.view=await this.bridge.currentView();const item=await this.works.save(this.session);this.workItems=this.works.list();this.subtitle='作品已保存，可从记录重开或删除';console.info('SELF_WORK_SAVED '+item.id);}catch(e){this.fail(String(e));}}
  private reopen(id:string):void{
    try{const saved=this.works.open(id);const restored=new SessionStore();restored.restore(saved);if(restored.protection?.persistent)restored.protection=undefined;this.works.loadPreference(restored);this.session=restored;this.identity=saved.sourceKind==='PHOTO'?'个人照片 · 本地处理':'示例面容';this.selected='';this.candidate='';this.bridge.assetId=saved.assetId;this.bridge.assetVersion=saved.assetVersion;this.bridge.revision=this.session.revision;this.close();this.restoreNotice=saved.renderPipelineVersion?'已恢复保存的作品与视角':'已保留旧作品文件，并按原操作重算；新旧引擎像素一致性尚未逐作品验证。另存会创建新作品。';this.bridge.send('INIT',{});this.labels();this.subtitle='正在恢复已保存作品';}catch(e){this.fail(String(e));}
  }
  private animate():void{if(this.timer>=0){clearInterval(this.timer);this.timer=-1;this.playing=false;return;}this.playing=true;this.animationValue=0;this.timer=setInterval(()=>{this.animationValue=(this.animationValue+2)%101;},50);}
  private exportPNG():void{if(!this.busy){this.busy=true;this.bridge.send('EXPORT_REQUEST',{width:768,height:1024});}}
  private deleteFace():void{
    try{this.works.deletePersonalAsset(this.session.assetId);this.session=new SessionStore();
      for(const name of ['lip','editable','protectionTest'])this.session.regions.push({regionId:name,assetId:this.session.assetId,assetVersion:this.session.assetVersion,width:1024,height:1024,semantic:name==='lip'?'confirmed-lips':'manual',fileName:name+'.mask'});
      this.works.loadPreference(this.session);this.bridge.assetId=this.session.assetId;this.bridge.assetVersion=this.session.assetVersion;this.bridge.revision=0;this.identity='示例面容';this.selected='';this.candidate='';this.ready=false;this.close();this.labels();this.bridge.send('INIT',{});this.subtitle='已删除这张照片的应用内源文件、作品、蒙版和私有导出；私密文字保留';
    }catch(e){this.fail(String(e));}
  }
  aboutToDisappear():void{this.planner.cancel();if(this.timer>=0)clearInterval(this.timer);this.audio.dispose();this.bridge.dispose();this.assets.cleanupTemporary();}
  onBackPress():boolean{if(this.detail){this.close();return true;}if(this.productOpen){this.productOpen=false;return true;}if(this.tool!=='NAVIGATE'){this.switchTool(this.tool);return true;}return false;}
  @Builder
  details(){
    Scroll(){Column({space:12}){
      Text(this.detail).fontSize(24).fontWeight(FontWeight.Medium).fontColor('#41364E').width('100%')
      if(this.detail==='完整回复'){Text(this.subtitle).fontSize(17).lineHeight(28)}
      if(this.detail==='云端理解'){
        Text('开启后，每次主动发送会附上当前静态面容图和最近三轮问答，由配置的后端交给 DeepSeek 理解。不会上传相机视频；修改仍需确认。').fontSize(16).fontColor('#665A72')
        Text('后端不保存照片；第三方处理与留存依其条款。授权仅本次打开有效，可随时关闭。').fontSize(14).fontColor('#766C80')
        Toggle({type:ToggleType.Switch,isOn:this.cloudSessionEnabled}).id('cloud-session-toggle').onChange((v:boolean)=>{this.cloudSessionEnabled=v;if(!v){this.cloudGeneration++;this.planner.cancel();this.cloudWaiting=false;this.pendingCloudText='';this.uploadOffer=false;this.dialogue=[];this.choices=[];}})
        TextInput({text:this.backendAddress,placeholder:'自己的后端地址'}).onChange((v:string)=>this.backendAddress=v)
        TextInput({text:this.backendToken,placeholder:'后端访问口令（不是 DeepSeek 密钥）'}).type(InputType.Password).onChange((v:string)=>this.backendToken=v)
        if(this.pendingCloudText){
          Text('这次请求：'+this.pendingCloudText).fontSize(15)
          Button('开启并发送').softButton().enabled(!this.cloudWaiting).onClick(()=>{this.cloudSessionEnabled=true;this.requestCloud();})
          Button('暂不发送，保留现在').softButton().onClick(()=>{this.pendingCloudText='';this.close();this.subtitle='没有发送图像，当前作品保持不变。';})
        }
      }
      if(this.detail==='氛围'){
        Text('让空间陪着你，节奏由你决定。').fontSize(17).fontColor('#665A72')
        Button(this.musicOn?'关闭音乐':'开启舒缓音乐').softButton().onClick(()=>this.toggleMusic(!this.musicOn))
        Text('当前：'+AmbiencePreference.label(this.palette)+(this.audioState==='playing'?' · 正在播放':this.audioState==='loading'?' · 准备中':'')).fontSize(14)
        Row({space:8}){Button('微光').softButton().onClick(()=>this.chooseAtmosphere('quiet'));Button('暖阳').softButton().onClick(()=>this.chooseAtmosphere('warm'));Button('清透').softButton().onClick(()=>this.chooseAtmosphere('clear'))}
        Row(){Text('随我的话语调整氛围').fontSize(16).layoutWeight(1);Toggle({type:ToggleType.Switch,isOn:this.followChat}).id('follow-chat').selectedColor('#9382AC').onChange((v:boolean)=>this.followChat=v)}.height(52)
        Text('只响应你主动说出的“我有点累”“我很开心”等表达；本地处理，不做心理判断。音乐不会因此自动开启。').fontSize(13).fontColor('#766C80')
        Row(){Text('柔和运动与粒子').fontSize(16).layoutWeight(1);Toggle({type:ToggleType.Switch,isOn:this.motion}).id('ambience-motion').selectedColor('#9382AC').onChange((v:boolean)=>{this.motion=v;this.setAtmosphere();})}.height(52)
        if(this.session.sourceKind==='MESH'){Button('缓慢转动人像').softButton().onClick(()=>{this.close();this.bridge.send('VIEW_ORBIT',{});})}
        Text('关闭后保留静态氛围。圈选、对照和操作详情时，人像轻转自动停止。').fontSize(13).fontColor('#766C80')
      }
      if(this.detail==='拍摄面容'){
        Text('从真实的你开始').fontSize(19).fontColor('#52465F')
        Text('先采集多个视角。个人3D重建尚未接通，视频不会替换成示例模型。').fontSize(14).fontColor('#81758D')
        if(this.cameraLive){CameraCaptureView({onSaved:()=>{this.captures=new CaptureService(this.context).list();}})}
        if(this.captureStatus){Text(this.captureStatus).fontSize(14)}
        if(!this.cameraLive){Button('打开相机 · 拍摄视频').softButton().onClick(()=>{this.cameraLive=true;this.showBeginning=false;})}
        Button('检查设备重建能力').softButton().onClick(()=>this.checkReconstruction())
        ForEach(this.captures,(clip:CaptureRecord)=>{Row(){Text('私密视频 · '+Math.round(clip.bytes/1024)+' KB').fontSize(14).layoutWeight(1);Button('删除视频').softButton().onClick(()=>{new CaptureService(this.context).delete(clip.name);this.captures=new CaptureService(this.context).list();this.captureStatus='已删除所选视频及采集记录。';})}},(clip:CaptureRecord)=>clip.name)
      }
      if(this.detail==='工具'){
        Button('拍摄面容视频').softButton().onClick(()=>{this.detail='拍摄面容';this.captures=new CaptureService(this.context).list();})
        Button('选择一张照片').softButton().onClick(()=>this.importPhoto())
        Button('保存当前画面 PNG').softButton().onClick(()=>{this.close();this.exportPNG();})
        if(this.session.sourceKind==='PHOTO'){Button('删除这份个人面容').softButton().onClick(()=>this.detail='删除个人面容')}
        if(this.session.sourceKind==='MESH'){Button('让模型规划唇色').softButton().onClick(()=>{this.close();this.suggest(true);})}
        if(this.session.sourceKind==='PHOTO'){
          Text('照片唇区需自己精细圈出，只包括嘴唇，避开口腔、牙齿与皮肤；可以重圈再确认。').fontSize(14)
          Button('确认这块只含嘴唇').softButton().enabled(this.selected.length>0).onClick(()=>{const region=this.session.regions.find((r:RegionRecord)=>r.regionId===this.selected);if(region){region.semantic='confirmed-lips';this.session.regionVersion++;this.session.sceneRevision++;this.session.candidate=undefined;this.candidate='';this.close();this.subtitle='已记录手工确认的唇区，可从工具试唇色。';}})
          Button('让模型规划唇色').softButton().enabled(this.selected.length>0).onClick(()=>{this.close();this.suggest(true);})
        }
        Button('让模型规划这里').softButton().enabled(this.selected.length>0).onClick(()=>{this.close();this.suggest(false);})
        Button('这里别动').softButton().enabled(this.selected.length>0).onClick(()=>this.detail='保护')
        Button('颜色淡一点').softButton().enabled(this.applied).onClick(()=>{this.close();this.adjust(true);})
        Button('换一种颜色').softButton().enabled(this.applied).onClick(()=>{this.close();this.adjust(false);})
        Button('重做').softButton().onClick(()=>{this.close();this.undo(1);})
        Button('回到原始').softButton().onClick(()=>{this.close();this.reset();})
        Button('作品与记录').softButton().onClick(()=>this.detail='作品与记录')
        Button('产品资料').softButton().onClick(()=>this.showProduct())
      }
      if(this.detail==='保护'){
        Text(this.protectedLabel||'默认只对本次生效。保留原貌与保留当前效果是不同选择。').fontSize(16)
        if(!this.protectedLabel){
          Button('本次保留原貌').softButton().enabled(this.selected.length>0).onClick(()=>this.protect(false,false))
          Button('本次保留当前效果').softButton().enabled(this.selected.length>0).onClick(()=>this.protect(true,false))
          Button('以后也保留原貌').softButton().enabled(this.selected.length>0&&this.session.sourceKind==='MESH').onClick(()=>this.protect(false,true))
        }else{Button('明确移除这处保护').softButton().onClick(()=>{if(this.session.protection?.persistent)this.works.deletePreference();this.session.protection=undefined;this.session.sceneRevision++;this.sendSnapshot();this.labels();this.subtitle='已按你的选择移除保护';})}
        Text('本版一次支持一处保护范围。当前效果的保护与作品一起保存。').fontSize(14)
      }
      if(this.detail==='作品与记录'){
        Button('保存当前作品').softButton().onClick(()=>this.saveWork())
        Text('实际成功的操作').fontSize(17)
        ForEach(this.bill,(line:string)=>{Text(line).fontSize(15).width('100%')})
        ForEach(this.workItems,(item:WorkItem)=>{Row({space:8}){Button(item.label).id('open-'+item.id).softButton().onClick(()=>this.reopen(item.id));Button('删除作品').id('delete-'+item.id).softButton().onClick(()=>{this.works.delete(item.id);this.workItems=this.works.list();this.subtitle='已删除该作品的私有文件与记录';})}},(item:WorkItem)=>item.id)
        if(this.note.length>0){Text(this.note).fontSize(16);Button('修改那句话').softButton().onClick(()=>this.detail='留一句话');Button('删除那句话').softButton().onClick(()=>{this.works.deleteNote();this.note='';})}
      }
      if(this.detail==='删除个人面容'){
        Text('删除这张照片在 SELF 中的源文件、关联作品、蒙版、临时数据和当前私有导出。你另存到外部的文件不受影响。私密文字单独管理。').fontSize(16)
        Button('确认删除这份面容').softButton().onClick(()=>this.deleteFace())
      }
      if(this.detail==='求助支持'){
        Text(this.subtitle).fontSize(18)
        Text('也可以联系医生、心理健康专业人员或身边可信任的人。此处不提供诊断或治疗。').fontSize(16)
        Text('参考：WHO Suicide Q&A\nhttps://www.who.int/news-room/questions-and-answers/item/suicide').fontSize(12).copyOption(CopyOptions.LocalDevice)
      }
      if(this.detail==='留一句话'){
        Text('自愿、私密、可修改和删除。只保存你确认的文字。').fontSize(16)
        TextArea({text:this.note,placeholder:'写给自己的话'}).height(180).maxLength(2000).onChange((v:string)=>this.note=v)
        Button('私密保存这句话').softButton().onClick(()=>{this.works.saveNote(this.note);this.close();this.subtitle='已私密保存，可在记录中修改或删除';})
        Button('跳过').softButton().onClick(()=>this.close())
      }
      Button('关闭').softButton().onClick(()=>this.close())
    }.padding(24).width('100%').alignItems(HorizontalAlign.Start)}.align(Alignment.TopStart).width('100%').height('100%').backgroundColor('#EAF5F2F8').backgroundBlurStyle(BlurStyle.COMPONENT_REGULAR).borderRadius(28).transition({opacity:0,translate:{y:20}})
  }
  @Builder
  conversation(){
    Column({space:10}){
      Row(){Text(this.focusOpen?'从这里开始':'✧  SELF 陪你').fontSize(13).fontColor('#89759C');Blank();Text(this.cloudWaiting?'正在理解':this.cloudSessionEnabled?'云端已开启':'隐私设置').fontSize(11).fontColor('#95879F').onClick(()=>this.open('云端理解'))}.width('100%')
      if(this.uploadOffer){
        Text('开启本次对话后，发送文字时会附上当前静态面容图和最近问答给 DeepSeek。可随时在隐私设置关闭。').fontSize(12).fontColor('#756380')
        Row({space:8}){Button('开启并发送').id('cloud-enable-send').softButton().layoutWeight(1).onClick(()=>{this.cloudSessionEnabled=true;this.requestCloud();});Button('暂不发送').softButton().onClick(()=>{this.uploadOffer=false;this.pendingCloudText='';})}
      }
      if(this.lastUtterance&&(!this.productOpen||this.wide)){Text('你说 · '+this.lastUtterance).fontSize(12).fontColor('#8E819A').maxLines(2).width('100%')}
      Text(this.subtitle).fontSize(15).lineHeight(23).fontColor('#52465F').maxLines(this.productOpen?2:this.wide?5:3).width('100%')
      if(this.replyQuestion&&this.replyQuestionKey===this.subtitle){Text(this.replyQuestion).fontSize(15).lineHeight(23).fontColor('#685571').width('100%')}
      if(this.choices.length>0&&!this.cloudWaiting&&!this.uploadOffer){Flex({wrap:FlexWrap.Wrap}){ForEach(this.choices,(choice:string,index:number)=>{Button((index+1)+' · '+choice).softButton().fontSize(13).margin(3).onClick(()=>this.askModel(choice))},(choice:string)=>choice)}}
      if(this.subtitle.length>70){Button('完整回复').softButton().height(this.productOpen?30:48).fontSize(12).onClick(()=>this.open('完整回复'))}
      if(this.replySources.length>0&&!this.productOpen){Button('看看这款').softButton().fontSize(12).onClick(()=>this.showProduct(this.replySources[0]))}
      if(this.focusOpen&&!this.candidate&&!this.cloudWaiting){
        Flex({wrap:FlexWrap.Wrap}){
          Button('想试一点变化').softButton().fontSize(13).margin(3).onClick(()=>this.suggest(false))
          Button('就这样也好').softButton().fontSize(13).margin(3).onClick(()=>this.open('保护'))
          Button('说说这里').softButton().fontSize(13).margin(3).onClick(()=>this.askModel('请和我聊聊圈出的这里，先不要提出编辑。'))
        }
      }
      if(this.support==='offered'){Row({space:8}){Button('愿意聊聊').softButton().layoutWeight(1).onClick(()=>{this.support='accepted';this.subtitle='愿意说说，是什么让你在意这里吗？我在听。';});Button('先看看就好').softButton().layoutWeight(1).onClick(()=>{this.support='';this.subtitle='好的，按你的节奏来。';})}}
      if(this.support==='accepted'){Button('给自己留句话').softButton().onClick(()=>this.open('留一句话'))}
      if(this.cloudWaiting){Button('取消这次请求').softButton().onClick(()=>{this.cloudGeneration++;this.planner.cancel();this.cloudWaiting=false;this.subtitle='好，先不等了。我们保留现在。';})}
      if(this.candidate){
        Row({space:8}){Button('试一下').id('apply-candidate').softButton().layoutWeight(1).backgroundColor('#7C698F').fontColor('#FFFFFF').onClick(()=>this.applyCandidate()).enabled(!this.busy);Button('保留现在').softButton().layoutWeight(1).onClick(()=>{this.session.candidate=undefined;this.candidate='';this.subtitle='好，就保留你现在的样子。';})}
        if(this.protectedLabel){Button('仅这项允许修改保护区').softButton().fontSize(12).enabled(!this.busy).onClick(()=>this.applyCandidate(true))}
      }
      if(this.applied&&!this.candidate){Row({space:6}){Button('淡一点').softButton().fontSize(13).layoutWeight(1).onClick(()=>this.adjust(true));Button('换个颜色').softButton().fontSize(13).layoutWeight(1).onClick(()=>this.adjust(false));Button('去掉这项').softButton().fontSize(13).layoutWeight(1).onClick(()=>this.askModel('请移除最后一项已生效的编辑层。'))}}
      if(this.wide){this.composer()}
    }.id('conversation-card').padding(18).width('100%').backgroundColor('#E8FFFFFF').backgroundBlurStyle(BlurStyle.COMPONENT_REGULAR).border({width:1,color:'#DDFFFFFF'}).borderRadius(28).shadow({radius:24,color:'#1575608C',offsetY:6}).scale({x:this.replyScale,y:this.replyScale}).opacity(this.replyOpacity)
  }
  @Builder composer(){
    Row({space:8}){TextInput({text:this.text,placeholder:this.focusOpen?'关于这里，想说些什么…':'此刻，想说些什么…'}).id('conversation-input').layoutWeight(1).height(48).fontSize(15).backgroundColor('#C7FFFFFF').borderRadius(24).enabled(this.ready&&!this.busy&&!this.cloudWaiting).onChange((v:string)=>this.text=v).onSubmit(()=>this.command());Button('发送').softButton().width(62).backgroundColor('#7C698F').fontColor('#FFFFFF').onClick(()=>this.command()).enabled(this.ready&&!this.busy&&!this.cloudWaiting)}.width('100%')
  }
  @Builder product(){
    ProductCard({product:this.productSelection,motion:this.motion,suggestionCount:this.replySources.length,onClose:()=>{this.getUIContext().animateTo({duration:this.motion?260:0,curve:Curve.EaseOut},()=>{this.productOpen=false;});},onChoose:(direction:number)=>this.chooseProduct(direction),onAsk:(_id:string)=>this.askModel('请简短介绍 OLAY '+this.productSelection.name+' 的关键资料，不推断配方或效果，也不要编辑面容。')})
  }
  @Builder canvasActions(){
    Row({space:8}){
      Button(this.tool==='LASSO'?'结束圈画':'圈画').id('lasso-tool').softButton().width(80).backgroundColor(this.tool==='LASSO'?'#DDCCE9':'#DCFFFFFF').onClick(()=>{this.focusOpen=false;this.switchTool('LASSO');}).enabled(this.ready&&!this.busy)
      Button('对照').softButton().width(66).onClick(()=>this.switchTool('COMPARE')).enabled(this.ready&&!this.busy)
      Button('撤销').softButton().width(66).onClick(()=>this.undo(-1)).enabled(this.applied&&!this.busy)
      if(this.wide){Button('唇色想法').softButton().width(96).onClick(()=>this.suggest(true)).enabled(this.ready&&!this.busy&&!this.cloudWaiting)}
      if(this.wide){
        Button('照片').softButton().width(66).onClick(()=>this.importPhoto())
        Button('拍摄').softButton().width(66).onClick(()=>this.open('拍摄面容'))
        Button('护理想法').softButton().width(90).onClick(()=>this.open('产品资料'))
        Button('作品').softButton().width(66).onClick(()=>this.open('作品与记录'))
        Button('导出').softButton().width(66).onClick(()=>this.exportPNG()).enabled(this.ready&&!this.busy)
      }else{Button('工具').softButton().width(66).onClick(()=>this.open('工具')).enabled(this.ready&&!this.busy)}
    }.padding({left:12,right:12,top:8,bottom:8})
  }
  build(){
    Column(){
      Row({space:10}){
        Column({space:2}){Text('SELF').fontSize(23).letterSpacing(4).fontWeight(FontWeight.Medium).fontColor('#42374E');Text('自在此刻').fontSize(10).letterSpacing(2).fontColor('#887A93')}.alignItems(HorizontalAlign.Start)
        if(this.wide){Text('每一种样子，都值得被看见').fontSize(13).fontColor('#998AA4').margin({left:22})}
        Blank()
        Button(this.audioState==='loading'?'准备中':this.musicOn?'音乐开':'音乐关').softButton().width(76).onClick(()=>this.toggleMusic(!this.musicOn))
        Button('氛围').softButton().width(64).enabled(this.ready&&!this.busy).onClick(()=>this.open('氛围'))
      }.padding({left:22,right:22,top:10,bottom:8}).width('100%')
      Stack({alignContent:Alignment.Bottom}){
        NativeMirrorSurface({port:this.bridge,interactionEnabled:!this.busy&&!this.detail,motion:this.motion}).width('100%').height('100%')
        if(!this.detail){
          Text(this.identity+' · 数字表达').fontSize(11).fontColor('#7D7188').padding({left:12,right:12,top:6,bottom:6}).backgroundColor('#BFFFFFFF').borderRadius(14).position({x:20,y:12})
          if(this.showBeginning&&this.wide){Column({space:12}){
            Text('从你的面容开始').fontSize(22).fontColor('#51415F')
            Text('拍摄自己，留下多个真实视角。').fontSize(14).fontColor('#75617F')
            Button('拍摄我的面容').id('begin-capture').softButton().backgroundColor('#7C698F').fontColor('#FFFFFF').onClick(()=>this.open('拍摄面容'))
            Text('从相机开始 · 个人3D重建尚未接通').fontSize(11).fontColor('#81758D')
            Button('先看示例').softButton().height(36).fontSize(12).onClick(()=>{this.showBeginning=false;if(this.motion)this.bridge.send('VIEW_ORBIT',{});})
          }.alignItems(HorizontalAlign.Start).padding(22).width(290).backgroundColor('#CAFFFFFF').backgroundBlurStyle(BlurStyle.COMPONENT_REGULAR).borderRadius(28).position({x:24,y:62}).transition({opacity:0,translate:{y:12}})}
          Row({space:8}){Text(!this.ready?'镜面准备中':this.tool==='LASSO'?'轻轻圈画一个范围，松手后聊聊':this.wide?'拖动转身 · 双指缩放 · 手写笔直接圈画':'拖动转身 · 双指缩放').fontSize(11).fontColor('#81758D').layoutWeight(1);Button('回正').softButton().width(60).onClick(()=>this.bridge.send('VIEW_SET',{view:{yaw:0,pitch:0,distance:16,panX:0,panY:0}})).enabled(this.ready&&!this.busy)}.width(this.wide?'48%':'100%').padding(16).position({x:0,y:this.surfaceHeight-(this.wide?142:72)})
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
        if(this.detail){Column(){this.details()}.width(this.wide?Math.min(600,this.windowWidth*.6):'100%').height('100%').align(Alignment.End)}
      }.layoutWeight(1).width('100%').onAreaChange((_old:Area,area:Area)=>{this.surfaceWidth=parseFloat(String(area.width));this.surfaceHeight=parseFloat(String(area.height));})
      if(!this.wide&&!this.detail){
        if(this.showBeginning){Button('从拍摄我的面容开始').softButton().onClick(()=>this.open('拍摄面容'))}
        if(!this.focusOpen||this.productOpen){Column(){this.conversation()}.width('92%')}
        Scroll(){this.canvasActions()}.scrollable(ScrollDirection.Horizontal).scrollBar(BarState.Off).width('100%').height(66)
        Column(){this.composer()}.padding({left:20,right:20,top:4,bottom:12}).width('100%')
      }
    }.width('100%').height('100%').backgroundColor('#F3F1F5').onAreaChange((_old:Area,area:Area)=>{this.windowWidth=parseFloat(String(area.width));this.wide=this.windowWidth>=840;if(this.context.applicationInfo.debug)console.info('SELF_WINDOW '+JSON.stringify({width:this.windowWidth,wide:this.wide}));}).linearGradient({angle:145,colors:[['#EDF0F8',0],['#F8F0E9',.6],['#F3F1F5',1]]})
  }
}
