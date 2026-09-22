import fs from 'node:fs/promises';
import {connect} from './cdp.mjs';
const c=await connect(Number(process.env.SELF_CDP_PORT||9223));
try{
 const result=await c.send('Runtime.evaluate',{returnByValue:true,expression:`JSON.stringify((()=>{
 const results=[];
 for(const [kind,options]of [['webgl2',{}],['webgl2',{antialias:false}],['webgl2',{antialias:false,powerPreference:'high-performance'}],['webgl',{}]]){
  const canvas=document.createElement('canvas');let error='';canvas.addEventListener('webglcontextcreationerror',e=>error=e.statusMessage);
  const gl=canvas.getContext(kind,options),item={kind,options,available:!!gl,error};
  if(gl){const ext=gl.getExtension('WEBGL_debug_renderer_info');item.version=gl.getParameter(gl.VERSION);item.renderer=gl.getParameter(gl.RENDERER);if(ext)item.unmaskedRenderer=gl.getParameter(ext.UNMASKED_RENDERER_WEBGL);item.attributes=gl.getContextAttributes();gl.getExtension('WEBGL_lose_context')?.loseContext();}
  results.push(item);
 }
 return {userAgent:navigator.userAgent,url:location.href,status:document.getElementById('status')?.textContent,webgl2Interface:typeof WebGL2RenderingContext,results};
})())`});
 const report=JSON.parse(result.result.value);
 try{
  const version=await (await fetch(`http://127.0.0.1:${process.env.SELF_CDP_PORT||9223}/json/version`)).json();
  const ws=new WebSocket(version.webSocketDebuggerUrl);await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
  try{report.gpu=await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('GPU query timeout')),5000);ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id===1){clearTimeout(timer);resolve(m.result||m.error);}};ws.send(JSON.stringify({id:1,method:'SystemInfo.getInfo'}));});}finally{ws.close();}
 }catch(e){report.gpuQueryError=String(e);}
 console.log(JSON.stringify(report,null,2));
 if(process.env.SELF_PROBE_OUTPUT)await fs.writeFile(process.env.SELF_PROBE_OUTPUT,JSON.stringify({date:new Date().toISOString(),...report},null,2));
}finally{c.close();}
