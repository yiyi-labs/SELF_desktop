import {MirrorRenderer,type RenderOperation} from './scene/Renderer.ts';
import {Endpoint} from './bridge/endpoint.ts';
import {Atmosphere} from './scene/Atmosphere.ts';
const status=document.getElementById('status')!;
const bridge=new Endpoint();let renderer:MirrorRenderer;
const atmosphere=new Atmosphere();
function initializeRenderer(){
renderer=new MirrorRenderer(document.getElementById('mirror')as HTMLCanvasElement,document.getElementById('selection')as HTMLCanvasElement);
bridge.webgl2=true;
renderer.onError=message=>{status.textContent=message;bridge.send('RENDER_FAILED',{message});};
renderer.onSelection=mask=>bridge.sendBytes('selection',mask);
renderer.onReady=()=>bridge.send('RESTORE_REQUEST',{});
renderer.onView=view=>bridge.send('VIEW_CHANGED',{view});renderer.onPointer=(x,y)=>atmosphere.pointer(x,y);
bridge.onBytes=async(h,bytes)=>{
 if(h.kind==='echo'){bridge.sendBytes('echo',bytes);return;}
 if(h.kind==='glb'){await renderer.loadGLB(bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength)as ArrayBuffer);status.textContent='';bridge.send('ASSET_REGISTERED',{width:renderer.width,height:renderer.height});return;}
 if(h.kind==='photo/jpeg'||h.kind==='photo/png'){await renderer.loadPhoto(bytes,h.kind==='photo/jpeg'?'image/jpeg':'image/png');status.textContent='';bridge.send('ASSET_REGISTERED',{width:renderer.width,height:renderer.height});return;}
 if(h.kind.startsWith('mask:')){if(bytes.length!==renderer.width*renderer.height)throw Error('Mask dimensions mismatch');renderer.masks.set(h.kind.slice(5),bytes);return;}
 throw Error('Unknown binary kind');
};
bridge.onMessage=async m=>{
 if(m.type==='ECHO'){bridge.send('ECHO_RESULT',m.payload,m.requestId);return;}
 if(m.type==='SET_TOOL'){renderer.setTool(m.payload.tool);return;}
 if(m.type==='SET_ATMOSPHERE'){atmosphere.set(m.payload.motion===true,m.payload.palette);if(!m.payload.motion)renderer.freezeView();return;}
 if(m.type==='VIEW_SET'){renderer.setView(m.payload.view);return;}
 if(m.type==='VIEW_ORBIT'){renderer.setTool('NAVIGATE');renderer.startOrbit();return;}
 if(m.type==='VIEW_FREEZE'){renderer.freezeView();return;}
 if(m.type==='RENDER_AUTHORIZED_PLAN'){
  const ops:RenderOperation[]=m.payload.operations.map((o:any)=>{const mask=renderer.masks.get(o.regionId);if(!mask)throw Error('Unknown mask');return {id:o.operationId,mask,color:o.color,strength:o.absoluteStrength};});
  const protection=m.payload.protectionId?renderer.masks.get(m.payload.protectionId):undefined;
  const anchor:RenderOperation[]=(m.payload.anchorOperations||[]).map((o:any)=>{const mask=renderer.masks.get(o.regionId);if(!mask)throw Error('Missing anchored region');return {id:o.operationId,mask,color:o.color,strength:o.absoluteStrength};});
  const old=renderer.operations;
  try{renderer.apply(ops,protection,m.payload.protectedSnapshot||0,anchor);renderer.render();if(renderer.renderer.getContext().getError()!==0)throw Error('GPU render error');bridge.revision=m.revision;bridge.send('RENDER_SUCCEEDED',{},m.requestId);}catch(e){renderer.apply(old);bridge.send('RESTORE_REQUEST',{});throw e;}return;
 }
 if(m.type==='EXPORT_REQUEST'){const bytes=await renderer.exportPNG(m.payload.width,m.payload.height);bridge.sendBytes('png',bytes,m.requestId);return;}
 if(m.type==='DISPOSE'){atmosphere.dispose();renderer.dispose();bridge.dispose();return;}
 throw Error('Unknown control message');
};
}
window.addEventListener('message',e=>{if(e.data==='SELF_PORT_V1'&&e.ports.length===1)bridge.connect(e.ports[0]);});
try{initializeRenderer();}catch(e){
  bridge.webgl2=false;bridge.startupError=e instanceof Error?e.message:String(e);
  status.textContent=bridge.startupError;status.setAttribute('role','alert');
  document.body.classList.add('graphics-unavailable');atmosphere.set(false,'quiet');
}
// Test surface is only compiled into a separate desktop test bundle, never into packaged rawfile.
if(__SELF_TEST__){(window as any).selfTest={renderer,bridge};}
