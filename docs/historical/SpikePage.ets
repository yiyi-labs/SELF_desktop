import { webview } from '@kit.ArkWeb';
import { common } from '@kit.AbilityKit';
import { fileIo as fs } from '@kit.CoreFileKit';
import { RendererBridge, Envelope, RenderOperation } from '../bridge/RendererBridge';

@Entry
@Component
struct SelfMirrorPage {
  @State subtitle: string = '示例面容 · 数字表达，非产品实测';
  @State ready: boolean = false;
  @State selectionReady: boolean = false;
  @State applied: boolean = false;
  @State tool: string = 'NAVIGATE';
  private controller: webview.WebviewController = new webview.WebviewController();
  private bridge: RendererBridge = new RendererBridge();
  private context: common.UIAbilityContext = this.getUIContext().getHostContext() as common.UIAbilityContext;
  private operations: RenderOperation[] = [];
  private pending: RenderOperation[] | undefined = undefined;
  private requestId: string = '';
  aboutToAppear(): void {
    webview.WebviewController.setWebDebuggingAccess(true);
    this.bridge.onMessage = (m: Envelope) => {
      console.info('SELF_EVENT ' + JSON.stringify(m));
      if (m.type === 'INITIALIZED') { this.loadSample(); }
      if (m.type === 'ASSET_REGISTERED') { this.ready = true; }
      if (m.type === 'RENDER_SUCCEEDED' && m.requestId === this.requestId && this.pending) {
        this.operations = this.pending; this.pending = undefined; this.applied = this.operations.length > 0;
        this.subtitle = this.applied ? '已应用数字表达 · 其他地方保持原样' : '已回到原始示例';
      }
      if (m.type === 'RENDER_FAILED') { this.pending = undefined; this.subtitle = m.payload.message || '没有完成修改，保留上一有效版本'; }
    };
    this.bridge.onBytes = (kind: string, bytes: ArrayBuffer) => {
      if (kind === 'selection') {
        if (bytes.byteLength !== 1024*1024) { return; }
        this.atomicWrite('selection.mask', bytes);
        this.bridge.sendBytes('mask:selection', new Uint8Array(bytes)); this.selectionReady = true;
        this.subtitle = '已圈选可见表面；点“局部试色”才会修改';
      }
      if (kind === 'png') {
        const data = new Uint8Array(bytes);
        if (data[0] !== 137 || data[1] !== 80 || data[2] !== 78 || data[3] !== 71) { this.subtitle = '导出格式错误'; return; }
        this.atomicWrite('self-export.png', bytes); this.subtitle = 'PNG 已保存到应用私有目录';
        console.info('SELF_EXPORT_SAVED ' + bytes.byteLength);
      }
      if (kind === 'echo') {
        const data = new Uint8Array(bytes); const valid = data.length === 65539 && data.every((v:number,i:number)=>v===i%256);
        console.info('SELF_BINARY_ROUNDTRIP ' + valid);
      }
    };
  }
  private atomicWrite(name: string, bytes: ArrayBuffer): void {
    const path = this.context.filesDir + '/' + name;
    const file = fs.openSync(path + '.tmp', fs.OpenMode.CREATE | fs.OpenMode.READ_WRITE | fs.OpenMode.TRUNC);
    try { const written = fs.writeSync(file.fd, bytes); if (written !== bytes.byteLength) { throw new Error('Short write'); } fs.fsyncSync(file.fd); }
    finally { fs.closeSync(file); }
    fs.renameSync(path + '.tmp', path);
  }
  private async loadSample(): Promise<void> {
    const r = this.context.resourceManager;
    this.bridge.sendBytes('glb', await r.getRawFileContent('assets/sample-head.glb'));
    for (const name of ['lip','editable','protectionTest']) {
      this.bridge.sendBytes('mask:' + name, await r.getRawFileContent('assets/' + name + '.mask'));
    }
    this.bridge.send('ECHO', {text:'中文 "引号" \u0000 结束'});
    const data = new Uint8Array(65539); for (let i=0;i<data.length;i++) { data[i]=i%256; }
    this.bridge.sendBytes('echo',data);
  }
  private apply(region: string): void {
    if (!this.ready || this.pending) { return; }
    const op: RenderOperation = {operationId:'tint-' + Date.now(),regionId:region,color:[0.66,0.12,0.3],absoluteStrength:0.25};
    this.pending = [op]; this.requestId = 'plan-' + Date.now(); this.bridge.revision++;
    this.bridge.send('RENDER_AUTHORIZED_PLAN', {operations:this.pending}, this.requestId);
  }
  aboutToDisappear(): void { this.bridge.dispose(); }
  build() {
    Column() {
      Row() { Text('SELF').fontSize(23).fontWeight(FontWeight.Medium); Blank(); Text('示例面容').fontSize(14); }.padding(20).width('100%')
      Web({src:$rawfile('renderer/index.html'),controller:this.controller})
        .javaScriptAccess(true).domStorageAccess(false).fileAccess(true).onlineImageAccess(false)
        .onPageEnd(() => { this.bridge.attach(this.controller); })
        .onLoadIntercept((event) => { const url=event?.data.getRequestUrl() || ''; return !url.startsWith('resource://rawfile/renderer/'); })
        .onConsole((event) => { console.info('SELF_WEB ' + event?.message.getMessage()); return false; })
        .layoutWeight(1).width('100%')
      Text(this.subtitle).fontSize(14).maxLines(2).padding({left:20,right:20,top:8,bottom:8})
      Row({space:8}) {
        Button(this.tool === 'LASSO' ? '结束圈选' : '圈选').height(48).onClick(() => { this.tool=this.tool==='LASSO'?'NAVIGATE':'LASSO';this.bridge.send('SET_TOOL',{tool:this.tool}); }).enabled(this.ready)
        Button('对照').height(48).onClick(() => { this.tool=this.tool==='COMPARE'?'NAVIGATE':'COMPARE';this.bridge.send('SET_TOOL',{tool:this.tool}); }).enabled(this.ready)
        Button('导出 PNG').height(48).onClick(() => { if(!this.pending)this.bridge.send('EXPORT_REQUEST',{width:768,height:1024}); }).enabled(this.ready)
      }.padding({bottom:8})
      Row({space:8}) {
        Button('试一下轻唇色').height(48).onClick(() => this.apply('lip')).enabled(this.ready)
        if(this.selectionReady){ Button('局部试色').height(48).onClick(() => this.apply('selection')); }
        if(this.applied){ Button('原始').height(48).onClick(() => {this.pending=[];this.requestId='reset-'+Date.now();this.bridge.revision++;this.bridge.send('RENDER_AUTHORIZED_PLAN',{operations:[]},this.requestId);}); }
      }.padding({bottom:18})
    }.width('100%').height('100%').backgroundColor('#eee9e3')
  }
}
