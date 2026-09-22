import { NativeMirrorSurface } from './NativeMirrorSurface';
import { NativeRendererPort } from '../bridge/NativeRendererPort';
import { PlannerClient, CloudResponse, CloudSnapshot } from '../services/PlannerClient';
import { common } from '@kit.AbilityKit';
import { Envelope } from '../bridge/RendererBridge';
import { SessionStore } from '../domain/SessionStore';
import { EditOperation, RegionRecord } from '../domain/EditPlan';
import { AssetStore } from '../services/AssetStore';
import { WorkspaceStore, WorkItem } from '../services/WorkspaceStore';
import { PlannerService } from '../services/PlannerService';
import { ProductRepository, ProductRecord } from '../services/ProductRepository';
import { AmbientAudio } from '../services/AmbientAudio';
import { AmbiencePreference } from '../services/AmbiencePreference';

@Extend(Button)
function softButton(){
  .height(48).padding({left:8,right:8}).fontSize(15).fontColor('#50445F').backgroundColor('#B8FFFFFF').borderRadius(24).border({width:1,color:'#D6FFFFFF'})
}

@Entry
@Component
struct SelfMirrorPage {
  @State @Watch('replyChanged') subtitle: string = '慢慢看看，按自己的节奏。每一种样子，都可以由你选择。';
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
  private planner:PlannerClient=new PlannerClient();
  @State cloudWaiting:boolean=false;
  @State backendAddress:string='http://127.0.0.1:8787';
  @State backendToken:string='';
  private pendingCloudText:string='';
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
          const id='region-'+Date.now();const fileName=this.assets.saveMask(id,bytes);
          const r:RegionRecord={regionId:id,assetId:this.session.assetId,assetVersion:this.session.assetVersion,width:this.session.width,height:this.session.height,semantic:'manual',fileName};
          this.session.regions.push(r);this.session.regionVersion++;this.session.sceneRevision++;this.bridge.sendBytes('mask:'+id,new Uint8Array(bytes));this.selected=id;
          this.subtitle='圈选已完成。可在工具中选择局部试色或“这里别动”。';console.info('SELF_SELECTION_SAVED '+id+' '+bytes.byteLength);
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
    if(this.cloudWaiting||!this.pendingCloudText)return;
    const input=this.pendingCloudText;this.pendingCloudText='';this.planner.endpoint=this.backendAddress.trim();this.planner.token=this.backendToken.trim();
    this.close();this.cloudWaiting=true;this.subtitle='正在理解这次请求。你仍可以转动面容，作品不会自动改变。';
    const snapshot=this.planner.snapshot(this.session,input);
    try{const regionId=this.selected||(this.session.sourceKind==='MESH'?'lip':'');const capture=await this.bridge.capture(regionId);snapshot.view=capture.view;snapshot.imageWidth=capture.width;snapshot.imageHeight=capture.height;snapshot.annotatedRegionId=regionId;
      if(this.session.sceneRevision!==snapshot.sceneRevision||this.session.regionVersion!==snapshot.regionVersion)throw new Error('作品状态已改变，请重新提出请求');
      const response=await this.planner.propose(snapshot,capture.images);
      if(!this.cloudWaiting)return;
      if(this.session.pending||this.session.assetId!==snapshot.assetId||this.session.assetVersion!==snapshot.assetVersion||this.session.sceneRevision!==snapshot.sceneRevision||this.session.regionVersion!==snapshot.regionVersion)throw new Error('等待期间作品或规则已改变，这份候选不会执行');
      this.subtitle=response.plan.shortMessage;
      if(response.plan.decision==='edit'){
        const op=response.plan.operations[0];
        const region=this.session.regions.find((r:RegionRecord)=>r.regionId===op.regionId);
        const plan=this.session.propose(region?.semantic==='confirmed-lips'?'lipTint':'localTint',op.regionId,op.presetId,PlannerClient.strength(op.intensityLevel));
        plan.targetLayerId=op.layerId;plan.removeLayer=op.operation==='remove_effect';plan.plannerSource='DeepSeek · '+response.modelEvidence.returnedModel;plan.snapshotId=snapshot.snapshotId;
        this.candidate=response.plan.shortMessage+(this.session.protection?' · 将保留已保护的范围':'');
        // A precise adjustment to an existing authorized layer needs no repeated confirmation.
        if(op.operation==='set_effect_level'&&op.layerId&&!this.session.protection&&/淡一点|浅一点|降低|深一点|浓一点/.test(input))this.applyCandidate();
      }else if(response.plan.question){this.subtitle=response.plan.question;}
    }catch(e){this.subtitle=String(e)+'。可继续使用工具中的本地试色。';}
    finally{this.cloudWaiting=false;}
  }
  private receive(m:Envelope):void{
    if(this.context.applicationInfo.debug)console.info('SELF_EVENT '+JSON.stringify(m));
    if(m.type==='INITIALIZED')this.loadSource().catch((e:Error)=>this.fail(e.message));
    if(m.type==='VIEW_CHANGED'&&m.payload.view){const v=m.payload.view;if([v.yaw,v.pitch,v.distance,v.panX,v.panY].every((n:number)=>Number.isFinite(n))){this.session.view=v;this.session.viewRevision++;}}
    if(m.type==='ASSET_REGISTERED'){this.session.width=m.payload.width||1024;this.session.height=m.payload.height||1024;this.previousSession=undefined;}
    if(m.type==='RENDER_SUCCEEDED'){
      if(this.session.succeeded(m.requestId,m.revision)){this.busy=false;this.subtitle='已应用通用数字表达 · 非产品实测';this.labels();}
      if(m.requestId===this.restoreRequest){this.busy=false;this.ready=true;this.restoreRequest='';this.labels();if(this.restoreNotice){this.subtitle=this.restoreNotice;this.restoreNotice='';}}
    }
    if(m.type==='RENDER_FAILED'){
      if(this.previousSession){this.assets.discardTemporary(this.session.assetId);this.session=this.previousSession;this.previousSession=undefined;this.bridge.assetId=this.session.assetId;this.bridge.assetVersion=this.session.assetVersion;this.bridge.revision=this.session.revision;this.identity=this.session.sourceKind==='PHOTO'?'个人照片 · 本地处理':'示例面容';this.bridge.send('INIT',{});}
      this.session.failed();this.fail(m.payload.message||'未完成修改，保留上一有效作品');
    }
    if(m.type==='RESTORE_REQUEST')this.sendSnapshot();
  }
  private async loadSource():Promise<void>{
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
    this.bridge.send('RENDER_AUTHORIZED_PLAN',{operations:this.session.pending?this.session.pending.operations:this.session.operations,protectionId:protection?.regionId,protectionRuleId:this.session.protectionKey(),anchorOperations:protection?.anchorOperations||[]},request);
  }
  private labels():void{
    this.applied=this.session.operations.length>0;
    this.bill=this.session.operations.map((o:EditOperation)=>(o.kind==='lipTint'?'唇色':'局部颜色')+' · '+o.presetId+' · '+Math.round(o.absoluteStrength*100)+'% · '+(o.plannerSource||'本地操作'));
    this.protectedLabel=this.session.protection?(this.session.protection.anchorOperations.length?'保护已确认的当前效果':'保护原始外观')+(this.session.protection.persistent?' · 长期':' · 本次'):'';
  }
  private suggest(lip:boolean):void{
    try{const regionId=lip&&this.session.sourceKind==='MESH'?'lip':this.selected;
      this.session.propose(lip?'lipTint':'localTint',regionId);this.candidate=lip?'在已确认唇区试轻一点的颜色，其他地方不动':'在刚才圈选范围试一点颜色';this.subtitle=this.candidate;
    }catch(e){this.fail(String(e));}
  }
  private applyCandidate(allowProtectedOnce:boolean=false):void{
    try{if(!this.session.candidate)return;this.session.authorize(this.session.candidate.planId,allowProtectedOnce);this.candidate='';this.busy=true;this.sendSnapshot();}catch(e){this.fail(String(e));}
  }
  private adjust(lighter:boolean):void{
    try{const last=this.session.operations[this.session.operations.length-1];if(!last)throw new Error('先试一个颜色，再调整');
      this.session.propose(last.kind,last.regionId,lighter?last.presetId:last.presetId==='rose'?'terracotta':'rose',lighter?Math.max(0,last.absoluteStrength-.08):last.absoluteStrength,true);this.applyCandidate();
    }catch(e){this.fail(String(e));}
  }
  private command():void{
    const input=this.text.trim();if(!input)return;this.lastUtterance=input;const intent=PlannerService.plan(input);this.text='';
    const mood=this.followChat?AmbiencePreference.fromText(input):undefined;
    if(mood){this.palette=mood;this.setAtmosphere();if(this.musicOn)this.audio.configure(true,mood);}
    if(!['musicOn','musicOff','apply','undo','redo','reset','protect','preference','products','observe','cancel','supportOffer','urgentSupport'].includes(intent.action)){this.pendingCloudText=input;this.open('云端理解');return;}
    if(intent.action==='urgentSupport'){this.session.candidate=undefined;this.candidate='';this.support='';this.subtitle=intent.text;this.open('求助支持');}
    else if(intent.action==='musicOn'){this.toggleMusic(true);this.subtitle='留一点轻柔的声音陪你。随时可以关闭，也可以自己选一种氛围。';}
    else if(intent.action==='musicOff'){this.toggleMusic(false);this.subtitle='音乐已关闭。按你舒服的方式来。';}
    else if(intent.action==='observe'){this.session.candidate=undefined;this.candidate='';this.subtitle='可以转一转，看看不同角度的自己。保留现在的样子，也是完整的选择。';}
    else if(intent.action==='suggestLip')this.suggest(true);
    else if(intent.action==='apply')this.applyCandidate();
    else if(intent.action==='lighter')this.adjust(true);
    else if(intent.action==='changeColor')this.adjust(false);
    else if(intent.action==='undo')this.undo(-1);
    else if(intent.action==='redo')this.undo(1);
    else if(intent.action==='reset')this.reset();
    else if(intent.action==='cancel'){this.planner.cancel();this.cloudWaiting=false;this.pendingCloudText='';this.session.candidate=undefined;this.candidate='';this.subtitle=intent.text;}
    else if(intent.action==='protect'||intent.action==='preference')this.open('保护');
    else if(intent.action==='products')this.open('产品资料');
    else if(intent.action==='supportOffer'){this.support='offered';this.subtitle=intent.text;}
    else this.subtitle=mood?'收到。我们把节奏放轻一点，你可以先看看，也可以说说想尝试什么。':intent.text;
  }
  private toggleMusic(enabled:boolean):void{this.musicOn=enabled;this.audio.configure(enabled,this.palette);}
  private setAtmosphere():void{if(this.bridge.ready)this.bridge.send('SET_ATMOSPHERE',{motion:this.motion&&this.foreground,palette:this.palette});}
  private chooseAtmosphere(mode:string):void{this.palette=mode;this.setAtmosphere();if(this.musicOn)this.audio.configure(true,mode);}
  private foregroundChanged():void{this.bridge.foreground(this.foreground);this.audio.visibility(this.foreground);this.setAtmosphere();if(!this.foreground&&this.timer>=0){clearInterval(this.timer);this.timer=-1;this.playing=false;}}
  private replyChanged():void{if(!this.motion)return;this.replyScale=.98;this.replyOpacity=.75;this.getUIContext().animateTo({duration:320,curve:Curve.EaseOut},()=>{this.replyScale=1;this.replyOpacity=1;});}
  private undo(direction:number):void{try{this.session.replay(direction);this.busy=true;this.sendSnapshot();}catch(e){this.fail(String(e));}}
  private reset():void{try{this.session.reset();this.busy=true;this.sendSnapshot();}catch(e){this.fail(String(e));}}
  private switchTool(next:string):void{if(this.busy)return;this.tool=this.tool===next?'NAVIGATE':next;this.bridge.send('SET_TOOL',{tool:this.tool});}
  private open(name:string):void{if(this.busy)return;this.previousTool=this.tool;this.detail=name;this.bridge.send('SET_TOOL',{tool:'DETAIL'});this.workItems=this.works.list();this.note=this.works.readNote();}
  private close():void{if(this.timer>=0)clearInterval(this.timer);this.timer=-1;this.playing=false;this.detail='';this.tool=this.previousTool;this.bridge.send('SET_TOOL',{tool:this.tool});}
  private protect(current:boolean,persistent:boolean):void{
    try{this.session.protect(this.selected,current,persistent);this.sendSnapshot();this.labels();this.close();
      if(persistent)this.works.savePreference(this.session).then(()=>{this.subtitle='已明确保存长期偏好';this.labels();}).catch((e:Error)=>this.fail(e.message));
      else this.subtitle=current?'仅本次保留这里当前的效果':'仅本次保留这里原始的样子';
    }catch(e){this.fail(String(e));}
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
  onBackPress():boolean{if(this.detail){this.close();return true;}if(this.tool!=='NAVIGATE'){this.switchTool(this.tool);return true;}return false;}
  @Builder
  details(){
    Scroll(){Column({space:12}){
      Text(this.detail).fontSize(24).fontWeight(FontWeight.Medium).fontColor('#41364E').width('100%')
      if(this.detail==='云端理解'){
        Text('只在你确认后，发送这次输入和无界面的当前面容图给你配置的后端，由 DeepSeek 理解并提出候选。圈选不代表修改授权。').fontSize(16).fontColor('#665A72')
        Text('后端不保存照片；第三方处理与留存依其条款。拒绝发送仍可使用工具中的本地编辑。').fontSize(14).fontColor('#766C80')
        TextInput({text:this.backendAddress,placeholder:'自己的后端地址'}).onChange((v:string)=>this.backendAddress=v)
        TextInput({text:this.backendToken,placeholder:'后端访问口令（不是 DeepSeek 密钥）'}).type(InputType.Password).onChange((v:string)=>this.backendToken=v)
        if(this.pendingCloudText){
          Text('这次请求：'+this.pendingCloudText).fontSize(15)
          Button('仅本次发送图像并理解').softButton().enabled(!this.cloudWaiting).onClick(()=>this.requestCloud())
          Button('暂不发送，继续本地编辑').softButton().onClick(()=>{this.pendingCloudText='';this.close();this.subtitle='没有发送图像。可从工具选择局部试色。';})
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
        Text('关闭后保留静态氛围。圈选、对照和操作详情时，人像轻转自动停止。').fontSize(13).fontColor('#766C80')
      }
      if(this.detail==='工具'){
        Button('选择一张照片').softButton().onClick(()=>this.importPhoto())
        Button('保存当前画面 PNG').softButton().onClick(()=>{this.close();this.exportPNG();})
        if(this.session.sourceKind==='PHOTO'){Button('删除这份个人面容').softButton().onClick(()=>this.detail='删除个人面容')}
        if(this.session.sourceKind==='MESH'){Button('建议轻唇色').softButton().onClick(()=>{this.close();this.suggest(true);})}
        if(this.session.sourceKind==='PHOTO'){
          Text('照片唇区需自己精细圈出，只包括嘴唇，避开口腔、牙齿与皮肤；可以重圈再确认。').fontSize(14)
          Button('确认这块只含嘴唇').softButton().enabled(this.selected.length>0).onClick(()=>{const region=this.session.regions.find((r:RegionRecord)=>r.regionId===this.selected);if(region){region.semantic='confirmed-lips';this.session.regionVersion++;this.session.sceneRevision++;this.session.candidate=undefined;this.candidate='';this.close();this.subtitle='已记录手工确认的唇区，可从工具试唇色。';}})
          Button('在确认的唇区试色').softButton().enabled(this.selected.length>0).onClick(()=>{this.close();this.suggest(true);})
        }
        Button('局部试色').softButton().enabled(this.selected.length>0).onClick(()=>{this.close();this.suggest(false);})
        Button('这里别动').softButton().enabled(this.selected.length>0).onClick(()=>this.detail='保护')
        Button('颜色淡一点').softButton().enabled(this.applied).onClick(()=>{this.close();this.adjust(true);})
        Button('换一种颜色').softButton().enabled(this.applied).onClick(()=>{this.close();this.adjust(false);})
        Button('重做').softButton().onClick(()=>{this.close();this.undo(1);})
        Button('回到原始').softButton().onClick(()=>{this.close();this.reset();})
        Button('作品与记录').softButton().onClick(()=>this.detail='作品与记录')
        Button('产品资料').softButton().onClick(()=>this.detail='产品资料')
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
      if(this.detail==='产品资料'){
        Text(ProductRepository.status()).fontSize(17)
        ForEach(ProductRepository.records(),(p:ProductRecord)=>{
          Text(p.brand+' · '+p.name+' · '+p.specification).fontSize(18)
          Text(p.region+' · '+p.evidenceType).fontSize(14)
          Text(p.formulaVersion).fontSize(14)
          Text(p.usageSummary).fontSize(15)
          Text('来源：'+p.source+'\n核对日期：'+p.retrievedAt).fontSize(12).copyOption(CopyOptions.LocalDevice)
        })
        Text('编辑参数示意').fontSize(20)
        Text('在已授权范围内混合数字颜色，保留纹理明暗。此示意不表示剂量、修复过程或品牌功效。').fontSize(16)
        Row(){Text('原颜色');Blank();Text('数字颜色')}.width('100%')
        Progress({value:this.animationValue,total:100,type:ProgressType.Linear}).width('100%').color('#965269')
        Stack(){Rect().fill('#bd9b88').width('100%').height(64);Rect().fill('#965269').opacity(this.animationValue/100).width('100%').height(64)}.width('100%').height(64)
        Text('数字混合权重：'+Math.round(this.animationValue)+'%').fontSize(14)
        Button(this.playing?'停止示意':'播放参数示意').softButton().onClick(()=>this.animate())
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
    }.padding(24).width('100%').alignItems(HorizontalAlign.Start)}.width('100%').height('100%').backgroundColor('#EAF5F2F8').backgroundBlurStyle(BlurStyle.COMPONENT_REGULAR).borderRadius(28).transition({opacity:0,translate:{y:20}})
  }
  build(){
    Column(){
      Row({space:10}){
        Column({space:2}){Text('SELF').fontSize(23).letterSpacing(4).fontWeight(FontWeight.Medium).fontColor('#42374E');Text('自在此刻').fontSize(10).letterSpacing(2).fontColor('#887A93')}.alignItems(HorizontalAlign.Start)
        Blank()
        Button(this.audioState==='loading'?'准备中':this.musicOn?'音乐开':'音乐关').softButton().width(76).onClick(()=>this.toggleMusic(!this.musicOn)).accessibilityDescription('开启或关闭舒缓背景音乐')
        Button('氛围').softButton().width(64).enabled(this.ready&&!this.busy).onClick(()=>this.open('氛围'))
      }.padding({left:22,right:22,top:10,bottom:8}).width('100%')
      Stack({alignContent:Alignment.Bottom}){
        NativeMirrorSurface({port:this.bridge,interactionEnabled:!this.busy&&!this.detail}).width('100%').height('100%')
        if(!this.detail){
          Text(this.identity+' · 数字表达').fontSize(11).fontColor('#7D7188').padding({left:12,right:12,top:6,bottom:6}).backgroundColor('#9EFFFFFF').borderRadius(14).position({x:20,y:12})
          Row({space:8}){
            Text(!this.ready?'镜面尚未就绪':this.tool==='LASSO'?'沿想保留或试色的位置，轻轻圈一圈':this.session.sourceKind==='MESH'?'拖动转身 · 双指靠近':'拖动平移 · 双指缩放').fontSize(11).fontColor('#81758D').layoutWeight(1)
            Button('回正').softButton().width(60).enabled(this.ready&&!this.busy).onClick(()=>{this.bridge.send('VIEW_SET',{view:{yaw:0,pitch:0,distance:16,panX:0,panY:0}});})
            if(this.session.sourceKind==='MESH'){Button('轻转').softButton().width(60).enabled(this.ready&&!this.busy&&this.motion).onClick(()=>{this.tool='NAVIGATE';this.bridge.send('VIEW_ORBIT',{});})}
          }.width('100%').padding({left:22,right:22,bottom:4}).align(Alignment.Bottom)
        }
        if(this.detail){this.details()}
      }.layoutWeight(1).width('100%')
      if(!this.detail){
        Column({space:7}){
          Row(){Text('✧  SELF 陪你').fontSize(11).fontColor('#8B789E');Blank();Text(this.cloudWaiting?'DeepSeek 理解中':'本地 · 隐私设置').fontSize(10).fontColor('#988BA3').onClick(()=>this.open('云端理解'))}.width('100%')
          if(this.lastUtterance){Text('你说 · '+this.lastUtterance).fontSize(12).fontColor('#8E819A').maxLines(1).width('100%')}
          Text(this.subtitle).fontSize(15).lineHeight(23).fontColor('#52465F').maxLines(3).width('100%')
          if(this.cloudWaiting){Button('取消本次云请求').softButton().onClick(()=>{this.planner.cancel();this.cloudWaiting=false;this.subtitle='已停止等待，当前作品不变；已经发出的图像无法保证从第三方撤回。';})}
          if(this.candidate){
            Row({space:10}){Button('试一下').softButton().layoutWeight(1).backgroundColor('#7C698F').fontColor('#FFFFFF').onClick(()=>this.applyCandidate()).enabled(!this.busy);Button('保留现在').softButton().layoutWeight(1).onClick(()=>{this.session.candidate=undefined;this.candidate='';this.subtitle='好的，留在你喜欢的这一刻。';})}
            if(this.protectedLabel){Text('默认避开保护区。也可只为这项表达允许一次例外，长期偏好不变。').fontSize(12).fontColor('#81758D');Button('仅这项允许修改重叠的保护区').softButton().enabled(!this.busy).onClick(()=>this.applyCandidate(true))}
          }
          else if(this.support==='offered'){Row({space:8}){Button('愿意聊聊').softButton().onClick(()=>{this.support='accepted';this.subtitle='可以保留，也可以尝试改变；选择由你决定。';});Button('先试色').softButton().onClick(()=>this.support='')}}
          else if(this.support==='accepted'){Button('自愿留一句话').softButton().onClick(()=>this.open('留一句话'))}
          else if(this.applied){Button('导出 PNG').softButton().width('100%').onClick(()=>this.exportPNG()).enabled(!this.busy)}
        }.padding(16).width('90%').backgroundColor('#9FFFFFFF').backgroundBlurStyle(BlurStyle.COMPONENT_REGULAR).border({width:1,color:'#CCFFFFFF'}).borderRadius(26).shadow({radius:18,color:'#0D756087',offsetY:6}).scale({x:this.replyScale,y:this.replyScale}).opacity(this.replyOpacity)
        Row({space:6}){
          Button(this.tool==='LASSO'?'结束':'圈选').softButton().layoutWeight(1).backgroundColor(this.tool==='LASSO'?'#E1D8EE':'#70FFFFFF').onClick(()=>this.switchTool('LASSO')).enabled(this.ready&&!this.busy)
          Button('对照').softButton().layoutWeight(1).backgroundColor(this.tool==='COMPARE'?'#E1D8EE':'#70FFFFFF').onClick(()=>this.switchTool('COMPARE')).enabled(this.ready&&!this.busy)
          Button('撤销').softButton().layoutWeight(1).onClick(()=>this.undo(-1)).enabled(this.applied&&!this.busy)
          Button('工具').softButton().layoutWeight(1).onClick(()=>this.open('工具')).enabled(this.ready&&!this.busy)
        }.width('90%').margin({top:10})
        Row({space:8}){TextInput({text:this.text,placeholder:'此刻，想说些什么…'}).id('conversation-input').layoutWeight(1).height(50).fontSize(15).backgroundColor('#C7FFFFFF').borderRadius(26).enabled(this.ready&&!this.busy).onChange((v:string)=>this.text=v).onSubmit(()=>this.command());Button('发送').softButton().width(68).backgroundColor('#7C698F').fontColor('#FFFFFF').onClick(()=>this.command()).enabled(this.ready&&!this.busy)}.padding({left:20,right:20,top:10,bottom:8})
        Text('每一种样子，都值得被看见 · 非产品实测').fontSize(9).fontColor('#9B8DA5').padding({bottom:8})
      }
    }.width('100%').height('100%').backgroundColor('#F3F1F5').linearGradient({angle:145,colors:[['#EDF0F8',0],['#F8F0E9',.6],['#F3F1F5',1]]})
  }
}


