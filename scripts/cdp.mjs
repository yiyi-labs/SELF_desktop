export async function connect(port=9223){
 let page,lastError;
 for(let attempt=0;attempt<40;attempt++){
  try{const list=await (await fetch(`http://127.0.0.1:${port}/json`,{signal:AbortSignal.timeout(1500)})).json();page=list.find(p=>p.url==='resource://rawfile/renderer/index.html');if(page)break;}catch(e){lastError=e;}
  await new Promise(resolve=>setTimeout(resolve,250));
 }
 if(!page)throw Error('SELF ArkWeb target not ready: '+String(lastError||'page absent'));
 const ws=new WebSocket(page.webSocketDebuggerUrl);await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
 let id=0;const pending=new Map();ws.onmessage=event=>{const m=JSON.parse(event.data);if(m.id&&pending.has(m.id)){const p=pending.get(m.id);pending.delete(m.id);clearTimeout(p.timer);m.error?p.reject(Error(JSON.stringify(m.error))):p.resolve(m.result);}};
 return {send(method,params={}){return new Promise((resolve,reject)=>{const key=++id,timer=setTimeout(()=>{pending.delete(key);reject(Error(`CDP timeout ${method}`));},60000);pending.set(key,{resolve,reject,timer});ws.send(JSON.stringify({id:key,method,params}));});},close(){ws.close();},page};
}
if(process.argv[1]?.endsWith('cdp.mjs')){const c=await connect();console.log(await c.send('Runtime.evaluate',{expression:'JSON.stringify({url:location.href,ua:navigator.userAgent,rect:document.querySelector("canvas").getBoundingClientRect().toJSON()})',returnByValue:true}));c.close();}
