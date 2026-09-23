import { Scene, Camera } from '@kit.ArkGraphics3D';
import { spatialRender, spatialEdit } from '@kit.SpatialReconKit';
import { common } from '@kit.AbilityKit';
import { fileIo as fs } from '@kit.CoreFileKit';
import { image } from '@kit.ImageKit';
import { BusinessError } from '@kit.BasicServicesKit';
import native from 'libself_native.so';
interface ProbeReport {
  recordedAt:number;
  phase:string; reconstruction:string; renderingDeclared:boolean; editingDeclared:boolean;
  pluginLoaded:boolean; nodeLoaded:boolean; editHandle:boolean; maskCall:boolean; saveCall:boolean;
  selectionOcclusionVerified:boolean; selectionPersistenceVerified:boolean; personalReconstructionValidated:boolean;
  error:string; errorCode:number; stage:string; output:string;
  snapshotBefore:boolean; snapshotAfter:boolean; snapshotControl:boolean; controlPaintCall:boolean; snapshotError:string;
}
@Entry
@Component
struct GsProbe {
  @State options:SceneOptions={};
  @State phase:string='checking';
  @State sceneReady:boolean=false;
  private scene:Scene|undefined=undefined;
  private camera:Camera|undefined=undefined;
  private node:spatialRender.GSNode|undefined=undefined;
  private disposed:boolean=false;
  private editing:boolean=false;
  private exportTimer:number=-1;
  private report:ProbeReport={recordedAt:0,phase:'checking',reconstruction:'',renderingDeclared:false,editingDeclared:false,
    pluginLoaded:false,nodeLoaded:false,editHandle:false,maskCall:false,saveCall:false,selectionOcclusionVerified:false,
    selectionPersistenceVerified:false,personalReconstructionValidated:false,error:'',errorCode:0,stage:'capability-query',output:'',
    snapshotBefore:false,snapshotAfter:false,snapshotControl:false,controlPaintCall:false,snapshotError:''};
  private recordError(error:BusinessError):void {
    this.report.errorCode=error.code??-1;
    this.report.error=error.message??String(error);
    this.phase='failed';this.store();
  }
  private step(stage:string):void {this.report.stage=stage;this.store();}
  private async snapshot(name:string):Promise<boolean> {
    try {
      const pixel=await this.getUIContext().getComponentSnapshot().get('gs-probe-surface');
      const packer=image.createImagePacker();
      try {
        const data=await packer.packing(pixel,{format:'image/png',quality:100});
        const context=this.getUIContext().getHostContext() as common.UIAbilityContext;
        const f=fs.openSync(context.filesDir+'/'+name,fs.OpenMode.CREATE|fs.OpenMode.READ_WRITE|fs.OpenMode.TRUNC);
        try{fs.writeSync(f.fd,data);}finally{fs.closeSync(f);}
      } finally {await packer.release();await pixel.release();}
      return true;
    } catch(error) {this.report.snapshotError=(error as BusinessError).message??String(error);return false;}
  }
  private store():void {
    this.report.phase=this.phase;
    this.report.recordedAt=Date.now();
    const context=this.getUIContext().getHostContext() as common.UIAbilityContext;
    const f=fs.openSync(context.filesDir+'/gs-sdk-probe.json',fs.OpenMode.CREATE|fs.OpenMode.READ_WRITE|fs.OpenMode.TRUNC);
    try{fs.writeSync(f.fd,JSON.stringify(this.report));}finally{fs.closeSync(f);}
    console.info('SELF_GS_SDK_PROBE '+JSON.stringify(this.report));
  }
  aboutToAppear():void{this.run();}
  aboutToDisappear():void{this.disposed=true;if(this.exportTimer>=0)clearTimeout(this.exportTimer);this.sceneReady=false;this.node=undefined;this.camera=undefined;this.scene?.destroy();this.scene=undefined;}
  private async run():Promise<void> {
    try{
      this.report.reconstruction=(await native.reconstruct('{"op":"probe"}')).json;
      this.report.renderingDeclared=canIUse('SystemCapability.Graphics.SpatialRender');
      this.report.editingDeclared=canIUse('SystemCapability.Graphics.SpatialEdit');
      if(!this.report.renderingDeclared||!this.report.editingDeclared){this.phase='unavailable';this.store();return;}
      this.step('copy-fixture');
      const context=this.getUIContext().getHostContext() as common.UIAbilityContext;
      const source=context.filesDir+'/gs-occlusion-source.ply';
      // This asset belongs to the signed test feature HAP, not the production entry HAP.
      const testResources=context.createModuleContext('entry_test').resourceManager;
      const bytes=await testResources.getRawFileContent('gs-probe/occlusion.ply');
      const f=fs.openSync(source,fs.OpenMode.CREATE|fs.OpenMode.READ_WRITE|fs.OpenMode.TRUNC);
      try{fs.writeSync(f.fd,bytes.buffer as ArrayBuffer);}finally{fs.closeSync(f);}
      // SDK26 places loadPlugin on RenderContext, despite a stale GSPlugin comment naming Scene.
      this.step('get-render-context');
      const renderContext=Scene.getDefaultRenderContext();
      if(!renderContext)throw new Error('No default render context');
      this.step('load-gs-plugin');
      this.report.pluginLoaded=await renderContext.loadPlugin(spatialRender.GSPlugin.PLUGIN_ID);
      if(!this.report.pluginLoaded)throw new Error('GS plugin returned false');
      // Official SpatialRender examples register the plugin before creating its Scene.
      this.step('create-scene');
      const scene=await Scene.load();if(this.disposed){scene.destroy();return;}this.scene=scene;
      this.step('load-ply');
      this.node=await spatialRender.GSPlugin.loadGSNode(scene,{uri:'file://'+source,offset:0},scene.root);this.report.nodeLoaded=!!this.node;
      this.step('create-camera');
      this.camera=await scene.getResourceFactory().createCamera({name:'gs-contract-camera'});
      this.camera.position={x:0,y:0,z:1};this.camera.rotation={x:0,y:0,z:0,w:1};
      this.camera.nearPlane=.01;this.camera.farPlane=10;this.camera.fov=35*Math.PI/180;this.camera.enabled=true;
      this.options={scene,modelType:ModelType.TEXTURE};this.sceneReady=true;this.phase='loaded';this.store();
      await new Promise<void>((resolve:()=>void)=>setTimeout(resolve,750));
      if(!this.disposed){
        this.step('snapshot-before');this.report.snapshotBefore=await this.snapshot('gs-before.png');
        await this.selectAndExport();
      }
    }catch(error){this.recordError(error as BusinessError);}
  }
  private async selectAndExport():Promise<void> {
    if(!this.node||this.phase!=='loaded'||this.editing||this.disposed)return;
    this.editing=true;
    let mask:image.PixelMap|undefined=undefined;
    try{
      this.step('create-edit-handle');
      const edit=spatialEdit.GSEdit.editGSNode(this.node);this.report.editHandle=!!edit;
      if(!edit)throw new Error('GS node is not editable');
      // Test-only paint of synthetic points. No planner bypass exists in the production editor.
      const rgba=new Uint8Array(512*512*4);
      for(let y=192;y<320;y++)for(let x=192;x<320;x++)rgba.fill(255,(y*512+x)*4,(y*512+x)*4+4);
      mask=await image.createPixelMap(rgba.buffer as ArrayBuffer,{size:{width:512,height:512},pixelFormat:image.PixelMapFormat.RGBA_8888});
      this.step('select-mask');
      edit.clearSelection();edit.selectBy2DMask(mask);this.report.maskCall=true;
      this.step('paint');
      edit.paint({r:1,g:0,b:0,a:1},spatialEdit.PaintMode.REPLACE);
      this.scene?.renderFrame({alwaysRender:true});
      await new Promise<void>((resolve:()=>void)=>setTimeout(resolve,750));
      if(this.disposed)return;
      this.step('snapshot-after');this.report.snapshotAfter=await this.snapshot('gs-after.png');
      // Independent positive control: select every known synthetic point.
      // This does not validate mask semantics, visibility or persistent indices.
      this.step('control-select-all-indices');
      const indices:number[]=[];
      for(let i=0;i<162;i++)indices.push(i);
      edit.clearSelection();edit.selectByIndex(indices);
      edit.paint({r:1,g:0,b:0,a:1},spatialEdit.PaintMode.REPLACE);
      this.report.controlPaintCall=true;
      this.scene?.renderFrame({alwaysRender:true});
      await new Promise<void>((resolve:()=>void)=>setTimeout(resolve,750));
      if(this.disposed)return;
      this.step('snapshot-control');this.report.snapshotControl=await this.snapshot('gs-control.png');
      const context=this.getUIContext().getHostContext() as common.UIAbilityContext;
      this.report.output=context.filesDir+'/gs-probe-edited.ply';
      this.step('save-ply');
      this.exportTimer=setTimeout(()=>{
        if(this.disposed)return;
        this.report.error='saveToPLY did not finish within 15 seconds';
        this.report.errorCode=-1;this.phase='failed';this.store();
      },15000);
      // Unlike the GS import URI, the official export example uses a sandbox path.
      const saved=await edit.saveToPLY(this.report.output);
      clearTimeout(this.exportTimer);this.exportTimer=-1;
      if(this.disposed||this.report.errorCode!==0)return;
      this.report.saveCall=saved;
      // Save/call success is not proof of front-only selection or stable correspondence.
      // Native/source comparison and rotated pixel evidence are separate acceptance gates.
      this.phase=this.report.saveCall?'exported-unverified':'failed';this.store();
    }catch(error){this.recordError(error as BusinessError);}
    finally{if(this.exportTimer>=0)clearTimeout(this.exportTimer);this.exportTimer=-1;await mask?.release();this.editing=false;}
  }
  build(){
    Column({space:12}){
      Text('SELF · Synthetic GS SDK probe').fontSize(18)
      // The condition must observe state from the first render. Short-circuiting
      // on the non-observed report prevented Component3D from ever mounting.
      if(this.sceneReady){
        Component3D(this.options).id('gs-probe-surface').width(this.getUIContext().px2vp(512)).height(this.getUIContext().px2vp(512)).backgroundColor('#30343A')
      }
      Text(this.phase).id('gs-probe-phase')
      Text('自动验证中，无需操作').fontSize(14)
    }.width('100%').height('100%').justifyContent(FlexAlign.Center).backgroundColor('#F2F0EB')
  }
}
