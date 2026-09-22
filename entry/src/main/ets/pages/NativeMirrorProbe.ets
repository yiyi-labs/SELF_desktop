import { Scene, Camera, Node, NodeType, Quaternion, Geometry, EnvironmentBackgroundType } from '@kit.ArkGraphics3D';

@Entry
@Component
struct NativeMirrorProbe {
  @State status: string = '正在检查原生 3D 环境…';
  @State loaded: boolean = false;
  @State options: SceneOptions = {};
  private scene: Scene | undefined = undefined;
  private camera: Camera | undefined = undefined;
  private model: Node | undefined = undefined;
  private generation: number = 0;
  private timeout: number = -1;
  private yaw: number = 0;
  private pitch: number = 0;
  private startYaw: number = 0;
  private startPitch: number = 0;
  private distance: number = 16;
  private startDistance: number = 16;

  aboutToAppear(): void { this.load(); }
  aboutToDisappear(): void {
    this.generation++;
    if(this.timeout>=0)clearTimeout(this.timeout);
    this.loaded=false;this.camera=undefined;this.model=undefined;
    this.scene?.destroy();this.scene=undefined;
  }
  private findMesh(node: Node): Node | undefined {
    if(node.nodeType===NodeType.GEOMETRY)return node;
    for(let i=0;i<node.children.count();i++){
      const child=node.children.get(i);
      if(child){const mesh=this.findMesh(child);if(mesh)return mesh;}
    }
    return undefined;
  }
  private async load(): Promise<void> {
    const token=++this.generation;
    try{
      if(!canIUse('SystemCapability.ArkUi.Graphics3D'))throw new Error('设备未声明原生 3D 能力');
      this.timeout=setTimeout(()=>{
        if(token!==this.generation||this.loaded)return;
        this.generation++;
        this.status='原生 3D 加载超时；这台环境尚未通过验证。';
        console.error('SELF_NATIVE_TIMEOUT');
      },15000);
      const scene=await Scene.load($rawfile('assets/sample-head.glb'));
      if(token!==this.generation){scene?.destroy();return;}
      if(!scene||!scene.root)throw new Error('原生引擎未返回有效场景');
      this.scene=scene;
      this.model=this.findMesh(scene.root);
      if(!this.model)throw new Error('未找到模型网格');
      // Preserve the imported unlit material; do not compensate for renderer errors by changing face color.
      const geometry=this.model as Geometry;
      const original=geometry.mesh.subMeshes[0].material;
      console.info('SELF_NATIVE_MATERIAL '+original.materialType);
      if(original.materialType!==3)throw new Error('未保留 GLB 的无光照材质');
      this.camera=await scene.getResourceFactory().createCamera({name:'self-observation-camera'});
      if(token!==this.generation){scene.destroy();this.scene=undefined;return;}
      this.camera.position={x:0,y:0,z:this.distance};
      this.camera.rotation={x:0,y:0,z:0,w:1};
      this.camera.fov=35*Math.PI/180;
      this.camera.nearPlane=.1;this.camera.farPlane=100;this.camera.enabled=true;
      this.camera.postProcess={vignette:{intensity:0},colorFringe:{intensity:0}};
      this.camera.clearColor={r:.85499,g:.81485,b:.76815,a:1};
      scene.environment.backgroundType=EnvironmentBackgroundType.BACKGROUND_NONE;
      this.options={scene,modelType:ModelType.TEXTURE};
      this.loaded=true;
      this.status='场景已加载，等待目视核对纹理与朝向。拖动观察，双指缩放。';
      clearTimeout(this.timeout);this.timeout=-1;
      console.info('SELF_NATIVE_SCENE_LOADED sample-lee; visual verification still required');
    }catch(error){
      if(token!==this.generation)return;
      if(this.timeout>=0)clearTimeout(this.timeout);this.timeout=-1;
      this.status='此环境未能加载原生 3D。'+String(error);
      console.error('SELF_NATIVE_FAILED '+String(error));
      this.scene?.destroy();this.scene=undefined;this.model=undefined;this.camera=undefined;
    }
  }
  private updateModelRotation(): void {
    if(!this.model)return;
    const cy=Math.cos(this.yaw/2),sy=Math.sin(this.yaw/2),cx=Math.cos(this.pitch/2),sx=Math.sin(this.pitch/2);
    const rotation: Quaternion={x:cy*sx,y:sy*cx,z:-sy*sx,w:cy*cx};
    this.model.rotation=rotation;
    console.info('SELF_NATIVE_VIEW '+this.yaw+' '+this.pitch+' '+this.distance);
  }
  private reset(): void {
    this.yaw=0;this.pitch=0;this.distance=16;this.updateModelRotation();
    if(this.camera)this.camera.position={x:0,y:0,z:this.distance};
  }
  build(){
    Column({space:14}){
      Text('SELF · 原生验证').fontSize(24).fontColor('#50445F')
      Text('示例扫描面容 · 不是个人重建').fontSize(13).fontColor('#81758D')
      Stack(){
        if(this.loaded){
          Component3D(this.options).width('100%').height('100%')
            .gesture(GestureGroup(GestureMode.Exclusive,
              PinchGesture({fingers:2}).onActionStart(()=>{this.startDistance=this.distance;})
                .onActionUpdate((event:GestureEvent)=>{if(!this.camera)return;this.distance=Math.max(9,Math.min(30,this.startDistance/event.scale));this.camera.position={x:0,y:0,z:this.distance};}),
              PanGesture({fingers:1}).onActionStart(()=>{this.startYaw=this.yaw;this.startPitch=this.pitch;})
                .onActionUpdate((event:GestureEvent)=>{this.yaw=this.startYaw+event.offsetX*.008;this.pitch=Math.max(-.7,Math.min(.7,this.startPitch+event.offsetY*.008));this.updateModelRotation();})
            ))
        }else{Text(this.status).fontSize(17).fontColor('#50445F').padding(24)}
      }.layoutWeight(1).width('100%').backgroundColor('#EEE9E3').borderRadius(24).clip(true)
      if(this.loaded){Text(this.status).fontSize(14).fontColor('#50445F')}
      Row({space:12}){
        Button('左侧').height(48).enabled(this.loaded).onClick(()=>{this.yaw=-.7;this.updateModelRotation();})
        Button('回正').height(48).enabled(this.loaded).onClick(()=>this.reset())
        Button('右侧').height(48).enabled(this.loaded).onClick(()=>{this.yaw=.7;this.updateModelRotation();})
      }
      Text('本入口仅验证原生加载与观察。拍摄建模、圈选试色及作品 PNG 导出尚未迁移。').fontSize(13).fontColor('#81758D')
    }.padding(22).width('100%').height('100%').backgroundColor('#F3F1F5')
  }
}
