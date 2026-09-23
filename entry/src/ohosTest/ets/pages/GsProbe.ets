import { Scene, Camera } from '@kit.ArkGraphics3D';
import { spatialRender, spatialEdit } from '@kit.SpatialReconKit';
import { common } from '@kit.AbilityKit';
import { fileIo as fs } from '@kit.CoreFileKit';
import { image } from '@kit.ImageKit';
import native from 'libself_native.so';
interface ProbeReport {
  recordedAt:number;
  phase:string; reconstruction:string; renderingDeclared:boolean; editingDeclared:boolean;
  pluginLoaded:boolean; nodeLoaded:boolean; editHandle:boolean; maskCall:boolean; saveCall:boolean;
  selectionOcclusionVerified:boolean; selectionPersistenceVerified:boolean; personalReconstructionValidated:boolean;
  error:string; output:string;
}
@Entry
@Component
struct GsProbe {
  @State options:SceneOptions={};
  @State phase:string='checking';
  private scene:Scene|undefined=undefined;
  private camera:Camera|undefined=undefined;
  private node:spatialRender.GSNode|undefined=undefined;
  private disposed:boolean=false;
  private report:ProbeReport={recordedAt:0,phase:'checking',reconstruction:'',renderingDeclared:false,editingDeclared:false,
    pluginLoaded:false,nodeLoaded:false,editHandle:false,maskCall:false,saveCall:false,selectionOcclusionVerified:false,
    selectionPersistenceVerified:false,personalReconstructionValidated:false,error:'',output:''};
  private store():void {
    this.report.phase=this.phase;
    this.report.recordedAt=Date.now();
    const context=this.getUIContext().getHostContext() as common.UIAbilityContext;
    const f=fs.openSync(context.filesDir+'/gs-sdk-probe.json',fs.OpenMode.CREATE|fs.OpenMode.READ_WRITE|fs.OpenMode.TRUNC);
    try{fs.writeSync(f.fd,JSON.stringify(this.report));}finally{fs.closeSync(f);}
    console.info('SELF_GS_SDK_PROBE '+JSON.stringify(this.report));
  }
  aboutToAppear():void{this.run();}
  aboutToDisappear():void{this.disposed=true;this.node=undefined;this.camera=undefined;this.scene?.destroy();this.scene=undefined;}
  private async run():Promise<void> {
    try{
      this.report.reconstruction=(await native.reconstruct('{"op":"probe"}')).json;
      this.report.renderingDeclared=canIUse('SystemCapability.Graphics.SpatialRender');
      this.report.editingDeclared=canIUse('SystemCapability.Graphics.SpatialEdit');
      if(!this.report.renderingDeclared||!this.report.editingDeclared){this.phase='unavailable';this.store();return;}
      const context=this.getUIContext().getHostContext() as common.UIAbilityContext;
      const source=context.filesDir+'/gs-occlusion-source.ply';
      const bytes=await context.resourceManager.getRawFileContent('gs-probe/occlusion.ply');
      const f=fs.openSync(source,fs.OpenMode.CREATE|fs.OpenMode.READ_WRITE|fs.OpenMode.TRUNC);
      try{fs.writeSync(f.fd,bytes.buffer as ArrayBuffer);}finally{fs.closeSync(f);}
      const scene=await Scene.load();if(this.disposed){scene.destroy();return;}this.scene=scene;
      // SDK26 places loadPlugin on RenderContext, despite a stale GSPlugin comment naming Scene.
      const renderContext=Scene.getDefaultRenderContext();
      if(!renderContext)throw new Error('No default render context');
      this.report.pluginLoaded=await renderContext.loadPlugin(spatialRender.GSPlugin.PLUGIN_ID);
      if(!this.report.pluginLoaded)throw new Error('GS plugin returned false');
      this.node=await spatialRender.GSPlugin.loadGSNode(scene,{uri:'file://'+source},scene.root);this.report.nodeLoaded=!!this.node;
      this.camera=await scene.getResourceFactory().createCamera({name:'gs-contract-camera'});
      this.camera.position={x:0,y:0,z:1};this.camera.rotation={x:0,y:0,z:0,w:1};
      this.camera.nearPlane=.01;this.camera.farPlane=10;this.camera.fov=35*Math.PI/180;this.camera.enabled=true;
      this.options={scene,modelType:ModelType.TEXTURE};this.phase='loaded';this.store();
      await new Promise<void>((resolve:()=>void)=>setTimeout(resolve,750));
      if(!this.disposed)await this.selectAndExport();
    }catch(error){this.report.error=String(error);this.phase='failed';this.store();}
  }
  private async selectAndExport():Promise<void> {
    if(!this.node||this.phase!=='loaded')return;
    let mask:image.PixelMap|undefined=undefined;
    try{
      const edit=spatialEdit.GSEdit.editGSNode(this.node);this.report.editHandle=!!edit;
      if(!edit)throw new Error('GS node is not editable');
      // Test-only paint of synthetic points. No planner bypass exists in the production editor.
      const rgba=new Uint8Array(512*512*4);
      for(let y=192;y<320;y++)for(let x=192;x<320;x++)rgba.fill(255,(y*512+x)*4,(y*512+x)*4+4);
      mask=await image.createPixelMap(rgba.buffer as ArrayBuffer,{size:{width:512,height:512},pixelFormat:image.PixelMapFormat.RGBA_8888});
      edit.clearSelection();edit.selectBy2DMask(mask);this.report.maskCall=true;
      edit.paint({r:1,g:0,b:0,a:1},spatialEdit.PaintMode.REPLACE);
      const context=this.getUIContext().getHostContext() as common.UIAbilityContext;
      this.report.output=context.filesDir+'/gs-occlusion-painted.ply';
      this.report.saveCall=await edit.saveToPLY('file://'+this.report.output);
      // Save/call success is not proof of front-only selection or stable correspondence.
      // Native/source comparison and rotated pixel evidence are separate acceptance gates.
      this.phase=this.report.saveCall?'exported-unverified':'failed';this.store();
    }catch(error){this.report.error=String(error);this.phase='failed';this.store();}
    finally{await mask?.release();}
  }
  build(){
    Column({space:12}){
      Text('SELF · Synthetic GS SDK probe').fontSize(18)
      if(this.report.renderingDeclared&&this.node&&(this.phase==='loaded'||this.phase==='exported-unverified')){
        Component3D(this.options).width(this.getUIContext().px2vp(512)).height(this.getUIContext().px2vp(512)).backgroundColor('#30343A')
      }
      Text(this.phase).id('gs-probe-phase')
      Button('Probe mask and save').id('gs-probe-select').enabled(this.phase==='loaded').onClick(()=>this.selectAndExport())
    }.width('100%').height('100%').justifyContent(FlexAlign.Center).backgroundColor('#F2F0EB')
  }
}
