import * as T from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {vertexShader,fragmentShader} from '../effects/tint.ts';
import {innerFeather,validatePolygon,polygonMask,type Point} from '../selection/polygon.ts';
import {visibleMask} from '../selection/visible-mask.ts';
export type RenderOperation={id:string,mask:Uint8Array,color:number[],strength:number};
export type SceneView={yaw:number,pitch:number,distance:number,panX:number,panY:number};
export class MirrorRenderer {
  readonly renderer:T.WebGLRenderer;
  readonly scene=new T.Scene();
  readonly camera=new T.PerspectiveCamera(35,1,.1,100);
  readonly masks=new Map<string,Uint8Array>();
  mesh:T.Mesh|null=null; material:T.ShaderMaterial|null=null;
  kind:'MESH'|'PHOTO'='MESH';width=1024;height=1024;
  operations:RenderOperation[]=[];tool='NAVIGATE';compare=.5;busy=false;disposed=false;
  private raf=0;private generation=0;private observer:ResizeObserver;private textures:T.Texture[]=[];
  private originalMap:T.Texture|null=null;private pointers=new Map<number,Point>();private stroke:Point[]=[];
  private previous:Point|null=null;private pinchDistance=0;private savedTool='NAVIGATE';
  private orbit=false;private orbitStart=0;private orbitYaw=0;private lastFrame=0;
  private reducedMotion=matchMedia('(prefers-reduced-motion: reduce)');
  private motionChanged=()=>{if(this.reducedMotion.matches)this.freezeView();};
  private handlers:Map<string,EventListener>=new Map();
  onSelection:(bytes:Uint8Array)=>void=()=>{};onError:(message:string)=>void=()=>{};onReady:()=>void=()=>{};
  onView:(view:SceneView)=>void=()=>{};onPointer:(x:number,y:number)=>void=()=>{};
  constructor(readonly canvas:HTMLCanvasElement,readonly overlay:HTMLCanvasElement){
    let creationError='';
    const onCreationError=(event:Event)=>{creationError=(event as WebGLContextEvent).statusMessage;};
    canvas.addEventListener('webglcontextcreationerror',onCreationError);
    const gl=canvas.getContext('webgl2',{alpha:true,antialias:true,preserveDrawingBuffer:false});
    canvas.removeEventListener('webglcontextcreationerror',onCreationError);
    if(!gl){
      console.error('SELF_WEBGL_UNAVAILABLE '+creationError);
      throw Error(/disabled by enterprise policy or commandline switch/i.test(creationError)
        ?'当前模拟器或设备限制了 3D 图形，暂时无法显示面容。请使用支持 WebGL2 的运行环境。'
        :'当前环境无法启动 3D 镜面，请检查设备的 WebGL2 支持。');
    }
    this.renderer=new T.WebGLRenderer({canvas,context:gl,alpha:true,antialias:true});
    this.renderer.outputColorSpace=T.SRGBColorSpace;this.renderer.toneMapping=T.NoToneMapping;
    this.renderer.setPixelRatio(Math.min(devicePixelRatio,2));this.renderer.setClearColor(0xeee9e3,0);
    this.camera.position.set(0,0,16);
    this.observer=new ResizeObserver(()=>{this.cancelStroke();this.resize();});this.observer.observe(canvas);
    for(const type of ['pointerdown','pointermove','pointerup','pointercancel','lostpointercapture'])this.listen(type,((e:PointerEvent)=>this.pointer(e)) as EventListener);
    this.listen('wheel',((e:WheelEvent)=>{if(this.tool!=='NAVIGATE'||this.busy)return;e.preventDefault();this.zoom(Math.exp(e.deltaY*.001));})as EventListener);
    this.listen('webglcontextlost',((e:Event)=>{e.preventDefault();this.cancelStroke();cancelAnimationFrame(this.raf);this.raf=0;this.onError('图形上下文中断，恢复后重绘有效版本');})as EventListener);
    this.listen('webglcontextrestored',(()=>{this.renderer.setClearColor(0xeee9e3,0);this.draw();this.onReady();})as EventListener);
    document.addEventListener('visibilitychange',this.visibility);this.reducedMotion.addEventListener('change',this.motionChanged);this.resize();
  }
  private listen(type:string,listener:EventListener){this.handlers.set(type,listener);this.canvas.addEventListener(type,listener,{passive:false});}
  private visibility=()=>{if(document.hidden){this.freezeView();cancelAnimationFrame(this.raf);this.raf=0;this.cancelStroke();}else this.draw();};
  resize(){const r=this.canvas.getBoundingClientRect();if(!r.width||!r.height)return;this.renderer.setSize(r.width,r.height,false);this.overlay.width=r.width;this.overlay.height=r.height;this.camera.aspect=r.width/r.height;this.camera.updateProjectionMatrix();this.draw();}
  private maskTexture(bytes:Uint8Array):T.DataTexture{const t=new T.DataTexture(bytes,this.width,this.height,T.RedFormat,T.UnsignedByteType);t.minFilter=t.magFilter=T.NearestFilter;t.generateMipmaps=false;t.flipY=false;t.needsUpdate=true;this.textures.push(t);return t;}
  private operationTextures(ops:RenderOperation[]):T.DataTexture[]{
    const groups=[new Uint8Array(this.width*this.height*4),new Uint8Array(this.width*this.height*4)];
    ops.forEach((op,i)=>{const mask=innerFeather(op.mask,this.width,this.height);for(let p=0;p<mask.length;p++)groups[Math.floor(i/4)][p*4+i%4]=mask[p];});
    return groups.map(bytes=>{const t=new T.DataTexture(bytes,this.width,this.height,T.RGBAFormat,T.UnsignedByteType);t.minFilter=t.magFilter=T.NearestFilter;t.generateMipmaps=false;t.flipY=false;t.needsUpdate=true;this.textures.push(t);return t;});
  }
  private createMaterial(map:T.Texture){
    const empty=this.maskTexture(new Uint8Array(this.width*this.height));
    this.material=new T.ShaderMaterial({vertexShader,fragmentShader,uniforms:{baseMap:{value:map},masks:{value:this.operationTextures([])},colors:{value:Array.from({length:8},()=>new T.Color())},strengths:{value:Array(8).fill(0)},count:{value:0},protection:{value:empty},protectedSnapshot:{value:0},anchorMasks:{value:this.operationTextures([])},anchorColors:{value:Array.from({length:8},()=>new T.Color())},anchorStrengths:{value:Array(8).fill(0)},anchorCount:{value:0},original:{value:false}},side:T.FrontSide});
    this.originalMap=map;return this.material;
  }
  private clearAsset(){this.orbit=false;this.generation++;this.scene.clear();this.mesh?.geometry.dispose();this.material?.dispose();if(this.originalMap?.image instanceof ImageBitmap)this.originalMap.image.close();this.originalMap?.dispose();for(const t of this.textures)t.dispose();this.textures=[];this.operations=[];this.masks.clear();this.mesh=null;}
  async loadGLB(bytes:ArrayBuffer){
    this.clearAsset();const token=this.generation;
    const loader=new GLTFLoader();loader.manager.setURLModifier(url=>{if(url.startsWith('blob:')||url.startsWith('data:'))return url;throw Error('External GLB resource denied');});
    const gltf=await loader.parseAsync(bytes,'');if(token!==this.generation)throw Error('Stale asset');
    const meshes:T.Mesh[]=[];gltf.scene.traverse(o=>{if((o as T.Mesh).isMesh)meshes.push(o as T.Mesh);});
    if(meshes.length!==1)throw Error('Only registered single primitive static asset supported');
    const mesh=meshes[0],old=mesh.material as T.MeshBasicMaterial;
    if(!old.map||!mesh.geometry.getAttribute('uv')||!mesh.geometry.index)throw Error('Missing embedded texture or UV');
    this.kind='MESH';this.width=this.height=1024;old.map.minFilter=T.LinearFilter;old.map.generateMipmaps=false;
    mesh.material=this.createMaterial(old.map);old.dispose();mesh.rotation.set(0,0,0);mesh.position.set(0,0,0);mesh.scale.set(1,1,1);
    this.mesh=mesh;this.scene.add(mesh);this.camera.position.set(0,0,16);this.camera.lookAt(0,0,0);this.draw();
  }
  async loadPhoto(bytes:Uint8Array,mime:string){
    if(!['image/jpeg','image/png'].includes(mime))throw Error('先使用 JPEG 或 PNG');
    const bitmap=await createImageBitmap(new Blob([bytes as BlobPart],{type:mime}),{imageOrientation:'from-image'});
    if(bitmap.width>4096||bitmap.height>4096){bitmap.close();throw Error('请先将照片最长边缩小到 4096 像素以内');}
    this.clearAsset();this.kind='PHOTO';this.width=bitmap.width;this.height=bitmap.height;
    const texture=new T.Texture(bitmap);texture.colorSpace=T.SRGBColorSpace;texture.flipY=false;texture.needsUpdate=true;texture.minFilter=T.LinearFilter;texture.generateMipmaps=false;
    const geo=new T.PlaneGeometry(8*this.width/this.height,8);const uv=geo.getAttribute('uv');for(let i=0;i<uv.count;i++)uv.setY(i,1-uv.getY(i));
    this.mesh=new T.Mesh(geo,this.createMaterial(texture));this.scene.add(this.mesh);this.camera.position.set(0,0,16);this.camera.lookAt(0,0,0);
    this.masks.set('editable',new Uint8Array(this.width*this.height).fill(255));this.draw();
    // ImageBitmap must remain alive for context restoration; close it on dispose/load replacement.
  }
  apply(ops:RenderOperation[],protection?:Uint8Array,protectedSnapshot=0,anchorOps:RenderOperation[]=[]){
    if(!this.material||ops.length>8)throw Error('No asset or operation budget exceeded');
    if(ops.some(op=>op.mask.length!==this.width*this.height||!Number.isFinite(op.strength)||op.strength<0||op.strength>.65||op.color.length!==3||op.color.some(v=>!Number.isFinite(v)||v<0||v>1)))throw Error('Invalid render plan');
    if(anchorOps.length>8||anchorOps.some(o=>o.mask.length!==this.width*this.height||!Number.isFinite(o.strength)))throw Error('Invalid snapshot anchor');
    if(protection&&protection.length!==this.width*this.height)throw Error('Invalid protection');
    const u=this.material.uniforms;for(const t of this.textures)t.dispose();this.textures=[];
    const empty=this.maskTexture(new Uint8Array(this.width*this.height));
    u.masks.value=this.operationTextures(ops);u.colors.value=Array.from({length:8},()=>new T.Color());u.strengths.value=Array(8).fill(0);
    for(let i=0;i<ops.length;i++){u.colors.value[i]=new T.Color().setRGB(...ops[i].color as [number,number,number],T.SRGBColorSpace);u.strengths.value[i]=ops[i].strength;}
    u.anchorMasks.value=this.operationTextures(anchorOps);u.anchorColors.value=Array.from({length:8},()=>new T.Color());u.anchorStrengths.value=Array(8).fill(0);u.anchorCount.value=anchorOps.length;
    for(let i=0;i<anchorOps.length;i++){u.anchorColors.value[i]=new T.Color().setRGB(...anchorOps[i].color as [number,number,number],T.SRGBColorSpace);u.anchorStrengths.value[i]=anchorOps[i].strength;}
    u.protection.value=protection?this.maskTexture(protection):empty;u.protectedSnapshot.value=protectedSnapshot;u.count.value=ops.length;this.operations=ops.map(o=>({...o}));this.draw();
  }
  setTool(tool:string){if(!['NAVIGATE','LASSO','COMPARE','DETAIL'].includes(tool))throw Error('Unknown tool');this.freezeView();this.cancelStroke();if(tool==='COMPARE')this.savedTool=this.tool;this.tool=tool;this.draw();}
  endCompare(){this.setTool(this.savedTool==='LASSO'?'LASSO':'NAVIGATE');}
  view():SceneView{return {yaw:this.mesh?.rotation.y||0,pitch:this.mesh?.rotation.x||0,distance:this.camera.position.z,panX:this.mesh?.position.x||0,panY:this.mesh?.position.y||0};}
  setView(v:SceneView){if(!this.mesh||![v.yaw,v.pitch,v.distance,v.panX,v.panY].every(Number.isFinite)||Math.abs(v.yaw)>Math.PI||Math.abs(v.pitch)>.6||v.distance<10||v.distance>25||Math.abs(v.panX)>20||Math.abs(v.panY)>20)throw Error('Invalid view');this.freezeView();this.mesh.rotation.set(this.kind==='MESH'?v.pitch:0,this.kind==='MESH'?v.yaw:0,0);this.mesh.position.set(this.kind==='PHOTO'?v.panX:0,this.kind==='PHOTO'?v.panY:0,0);this.camera.position.z=v.distance;this.onView(this.view());this.draw();}
  startOrbit(){if(this.kind!=='MESH'||this.tool!=='NAVIGATE'||this.reducedMotion.matches)return;this.orbit=true;this.orbitStart=performance.now();this.orbitYaw=this.mesh?.rotation.y||0;this.draw();}
  freezeView(){if(this.orbit){this.orbit=false;this.onView(this.view());}}
  draw(){if(this.disposed||document.hidden||this.raf)return;this.raf=requestAnimationFrame(now=>{this.raf=0;if(!this.orbit||now-this.lastFrame>=33){if(this.orbit&&this.mesh)this.mesh.rotation.y=T.MathUtils.euclideanModulo(this.orbitYaw+Math.sin((now-this.orbitStart)/12000)*.16+Math.PI,Math.PI*2)-Math.PI;this.render();this.lastFrame=now;}if(this.orbit)this.draw();});}
  render(){
    if(!this.material||this.renderer.getContext().isContextLost())return;
    const size=this.renderer.getSize(new T.Vector2());this.renderer.setRenderTarget(null);this.renderer.setViewport(0,0,size.x,size.y);this.renderer.setScissorTest(false);
    this.material.uniforms.original.value=false;this.renderer.render(this.scene,this.camera);
    if(this.tool==='COMPARE'){this.renderer.setScissorTest(true);this.renderer.setScissor(0,0,Math.floor(size.x*this.compare),size.y);this.material.uniforms.original.value=true;this.renderer.render(this.scene,this.camera);}
    this.material.uniforms.original.value=false;this.renderer.setScissorTest(false);
  }
  async exportPNG(width=768,height=1024):Promise<Uint8Array>{
    this.freezeView();
    if(!this.material||this.busy||width<1||height<1||width>4096||height>4096)throw Error('Cannot export');
    const target=new T.WebGLRenderTarget(width,height,{type:T.UnsignedByteType,format:T.RGBAFormat,depthBuffer:true});
    // Target is explicitly sRGB; renderer's output conversion follows target texture's color space.
    target.texture.colorSpace=T.SRGBColorSpace;
    const oldAspect=this.camera.aspect,oldTarget=this.renderer.getRenderTarget(),oldViewport=this.renderer.getViewport(new T.Vector4()),oldScissor=this.renderer.getScissor(new T.Vector4()),oldTest=this.renderer.getScissorTest();
    try{
      this.camera.aspect=width/height;this.camera.updateProjectionMatrix();this.material.uniforms.original.value=false;this.renderer.setClearColor(0xeee9e3,1);
      // setViewport() takes logical pixels and multiplies DPR, even with an offscreen target.
      // Target viewport is already expressed in physical texels; use it directly.
      target.viewport.set(0,0,width,height);this.renderer.setRenderTarget(target);this.renderer.setScissorTest(false);this.renderer.render(this.scene,this.camera);
      const rgba=new Uint8Array(width*height*4);this.renderer.readRenderTargetPixels(target,0,0,width,height,rgba);
      const flat=new Uint8ClampedArray(rgba.length);for(let y=0;y<height;y++)flat.set(rgba.subarray((height-y-1)*width*4,(height-y)*width*4),y*width*4);
      const c=document.createElement('canvas');c.width=width;c.height=height;const ctx=c.getContext('2d')!;ctx.putImageData(new ImageData(flat,width,height),0,0);
      const labelHeight=Math.max(20,Math.round(height*.023));ctx.fillStyle='#eee9e3';ctx.fillRect(0,height-labelHeight,width,labelHeight);
      ctx.fillStyle='#594550';ctx.font=`${Math.max(10,Math.round(labelHeight*.55))}px sans-serif`;ctx.textAlign='center';
      ctx.fillText('SELF · Digital expression · Not a product result',width/2,height-Math.round(labelHeight*.3));
      const blob=await new Promise<Blob>((resolve,reject)=>c.toBlob(b=>b?resolve(b):reject(Error('PNG encoder failed')),'image/png'));
      return new Uint8Array(await blob.arrayBuffer());
    }finally{target.dispose();this.renderer.setClearColor(0xeee9e3,0);this.camera.aspect=oldAspect;this.camera.updateProjectionMatrix();this.renderer.setRenderTarget(oldTarget);this.renderer.setViewport(oldViewport);this.renderer.setScissor(oldScissor);this.renderer.setScissorTest(oldTest);this.draw();}
  }
  pick(point:Point){if(!this.mesh)return null;const r=this.canvas.getBoundingClientRect(),ray=new T.Raycaster();ray.setFromCamera(new T.Vector2(point.x/r.width*2-1,1-point.y/r.height*2),this.camera);this.mesh.updateMatrixWorld(true);return ray.intersectObject(this.mesh)[0]||null;}
  async select(points:Point[]):Promise<Uint8Array>{
    if(!this.mesh||this.busy)throw Error('Selection busy');const rect=this.canvas.getBoundingClientRect(),poly=validatePolygon(points,rect.width,rect.height);this.busy=true;const token=this.generation;
    try{
      let mask:Uint8Array;
      if(this.kind==='PHOTO'){
        this.mesh.updateMatrixWorld(true);
        const plane=new T.Plane(new T.Vector3(0,0,1),-this.mesh.position.z),ray=new T.Raycaster();
        const imagePoints=poly.map(p=>{ray.setFromCamera(new T.Vector2(p.x/rect.width*2-1,1-p.y/rect.height*2),this.camera);
          const hit=ray.ray.intersectPlane(plane,new T.Vector3());if(!hit)throw Error('没有相交的照片平面');
          const local=this.mesh!.worldToLocal(hit);return {x:(local.x/(8*this.width/this.height)+.5)*this.width,y:(.5-local.y/8)*this.height};});
        mask=polygonMask(imagePoints,this.width,this.height);
      }else mask=await visibleMask(this.mesh,this.camera,poly,rect.width,rect.height,this.masks.get('editable')||new Uint8Array(this.width*this.height),this.width);
      if(token!==this.generation)throw Error('Stale selection');if(!mask.some(Boolean))throw Error('没有选中可编辑的可见表面');return mask;
    }finally{this.busy=false;}
  }
  private point(e:PointerEvent):Point{const r=this.canvas.getBoundingClientRect();return {x:e.clientX-r.left,y:e.clientY-r.top};}
  private pointer(e:PointerEvent){
    if(this.tool==='DETAIL'||this.busy)return;const p=this.point(e);
    if(e.type==='pointerdown'){this.freezeView();this.pointers.set(e.pointerId,p);this.canvas.setPointerCapture(e.pointerId);if(this.pointers.size>1){this.cancelStroke(false);this.pinchDistance=this.distance();return;}this.previous=p;if(this.tool==='LASSO')this.stroke=[p];}
    if(e.type==='pointermove'&&this.pointers.has(e.pointerId)){
      this.pointers.set(e.pointerId,p);
      const rect=this.canvas.getBoundingClientRect();this.onPointer(p.x/rect.width,p.y/rect.height);
      if(this.tool==='COMPARE'){this.compare=Math.max(0,Math.min(1,p.x/this.canvas.getBoundingClientRect().width));this.draw();}
      else if(this.pointers.size>1&&this.tool==='NAVIGATE'){const d=this.distance();if(this.pinchDistance)this.zoom(this.pinchDistance/d);this.pinchDistance=d;}
      else if(this.tool==='LASSO'&&this.stroke.length){if(Math.hypot(p.x-this.stroke.at(-1)!.x,p.y-this.stroke.at(-1)!.y)>2)this.stroke.push(p);this.paintStroke();}
      else if(this.tool==='NAVIGATE'&&this.previous&&this.mesh){const dx=p.x-this.previous.x,dy=p.y-this.previous.y;if(this.kind==='MESH'){this.mesh.rotation.y=T.MathUtils.euclideanModulo(this.mesh.rotation.y+dx*.006+Math.PI,Math.PI*2)-Math.PI;this.mesh.rotation.x=T.MathUtils.clamp(this.mesh.rotation.x+dy*.004,-.45,.45);}else {this.mesh.position.x=T.MathUtils.clamp(this.mesh.position.x+dx*.013,-20,20);this.mesh.position.y=T.MathUtils.clamp(this.mesh.position.y-dy*.013,-20,20);}this.draw();}this.previous=p;
    }
    if(e.type==='pointerup'){
      const stroke=this.stroke.slice();this.cancelStroke(false);this.pointers.delete(e.pointerId);this.previous=null;
      this.onView(this.view());
      if(stroke.length&&this.tool==='LASSO'){stroke.push(p);this.select(stroke).then(mask=>this.onSelection(mask)).catch(err=>this.onError(err.message));}
    }
    if(e.type==='pointercancel'||e.type==='lostpointercapture'){this.pointers.delete(e.pointerId);this.cancelStroke(false);this.onView(this.view());}
  }
  private distance(){const p=[...this.pointers.values()];return p.length>1?Math.hypot(p[0].x-p[1].x,p[0].y-p[1].y):0;}
  private zoom(factor:number){this.freezeView();this.camera.position.z=T.MathUtils.clamp(this.camera.position.z*factor,10,25);this.onView(this.view());this.draw();}
  private paintStroke(){const ctx=this.overlay.getContext('2d')!;ctx.clearRect(0,0,this.overlay.width,this.overlay.height);ctx.strokeStyle='#6b354d';ctx.lineWidth=2;ctx.beginPath();this.stroke.forEach((p,i)=>i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y));ctx.stroke();}
  private cancelStroke(clear=true){this.stroke=[];this.previous=null;if(clear)this.pointers.clear();this.overlay.getContext('2d')?.clearRect(0,0,this.overlay.width,this.overlay.height);}
  dispose(){if(this.disposed)return;this.disposed=true;this.observer.disconnect();cancelAnimationFrame(this.raf);for(const [type,handler]of this.handlers)this.canvas.removeEventListener(type,handler);document.removeEventListener('visibilitychange',this.visibility);this.reducedMotion.removeEventListener('change',this.motionChanged);this.clearAsset();this.renderer.dispose();}
}
