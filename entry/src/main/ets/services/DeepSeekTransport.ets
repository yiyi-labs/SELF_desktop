import { http } from '@kit.NetworkKit';
import { DeepSeekConfig } from './DeepSeekConfig';
import { DeepSeekRequestBody,DeepSeekRawResponse,DeepSeekError } from './DeepSeekTypes';
import { DeepSeekRuntimeState,DeepSeekLifecycleListener } from './DeepSeekRuntimeState';
import { DeepSeekStreamParser,DeepSeekStreamAssembler } from './DeepSeekStreamParser';

interface ActiveRequest{request:http.HttpRequest;cancelled:boolean;owner:string;}
interface RequestTicket{id:number;entry:ActiveRequest;}
interface StreamTicket{parser:DeepSeekStreamParser;assembler:DeepSeekStreamAssembler;done:boolean;}

/**
 * HTTPS transport to the official DeepSeek API only. It knows requests, SSE framing,
 * cancellation and error normalisation — nothing about plans, products or prompts.
 * The key is handed in per call and never stored or logged here.
 */
export class DeepSeekTransport implements DeepSeekLifecycleListener {
 private static sharedInstance:DeepSeekTransport=new DeepSeekTransport();
 private active:Map<number,ActiveRequest>=new Map();
 private nextId:number=1;
 static shared():DeepSeekTransport{return DeepSeekTransport.sharedInstance;}
 private constructor(){DeepSeekRuntimeState.addListener(this);}
 onDeepSeekBackground():void{this.cancelAll();}
 /** Really destroys the in-flight HttpRequest objects, stopping network, stream and callbacks. */
 cancelAll():void{
  for(const entry of this.active){
   entry[1].cancelled=true;
   try{entry[1].request.destroy();}catch(_){}
  }
  const count=this.active.size;this.active.clear();
  if(count>0)console.info('SELF_DEEPSEEK_CANCEL_ALL '+count);
 }
 cancel(id:number):void{
  const entry=this.active.get(id);
  if(!entry)return;
  this.active.delete(id);entry.cancelled=true;
  try{entry.request.destroy();}catch(_){}
 }
 /** Cancels only the requests one caller owns, so cancelling a plan never kills a live story reply. */
 cancelOwner(owner:string):void{
  for(const entry of this.active){
   if(entry[1].owner!==owner)continue;
   entry[1].cancelled=true;
   try{entry[1].request.destroy();}catch(_){}
   this.active.delete(entry[0]);
  }
 }
 private register(request:http.HttpRequest,owner:string):RequestTicket{
  const id=this.nextId++;const entry:ActiveRequest={request,cancelled:false,owner};
  this.active.set(id,entry);const ticket:RequestTicket={id,entry};return ticket;
 }
 /** Non-stream chat completion. No silent retry: failures surface as DeepSeekError for the caller to decide. */
 async chat(body:DeepSeekRequestBody,key:string,readTimeout:number,owner:string='self'):Promise<DeepSeekRawResponse>{
  if(!DeepSeekRuntimeState.allowRequests)throw new DeepSeekError('background','SELF 正在后台，已暂停 DeepSeek 请求。');
  const request=http.createHttp();const ticket=this.register(request,owner);const id=ticket.id;const entry=ticket.entry;
  try{
   const response=await request.request(DeepSeekConfig.BASE_URL+'/chat/completions',{
    method:http.RequestMethod.POST,
    header:{'Content-Type':'application/json','Authorization':'Bearer '+key},
    extraData:JSON.stringify(body),expectDataType:http.HttpDataType.STRING,
    connectTimeout:DeepSeekConfig.CONNECT_TIMEOUT_MS,readTimeout,usingCache:false});
   if(entry.cancelled)throw new DeepSeekError('cancelled','这次请求已取消。');
   if(response.responseCode!==200){
    console.warn('SELF_DEEPSEEK_HTTP '+response.responseCode);
    throw DeepSeekTransport.httpError(response.responseCode);
   }
   try{return JSON.parse(response.result as string) as DeepSeekRawResponse;}
   catch(_){throw new DeepSeekError('invalid_response','DeepSeek 返回了无法读取的回复。');}
  }catch(e){
   if(e instanceof DeepSeekError)throw e;
   if(entry.cancelled)throw new DeepSeekError('cancelled','这次请求已取消。');
   throw DeepSeekTransport.connectionError(e);
  }finally{this.active.delete(id);request.destroy();}
 }
 /**
  * SSE streaming chat. HTTP chunk boundaries are irrelevant here: the parser buffers
  * until whole `data:` events arrive, tolerating split UTF-8, blanks, keep-alives and [DONE].
  */
 async streamChat(body:DeepSeekRequestBody,key:string,onEvent:(payload:string)=>void,idleTimeoutMs:number,owner:string='self'):Promise<DeepSeekStreamAssembler>{
  if(!DeepSeekRuntimeState.allowRequests)throw new DeepSeekError('background','SELF 正在后台，已暂停 DeepSeek 请求。');
  const request=http.createHttp();const ticket=this.register(request,owner);const id=ticket.id;const entry=ticket.entry;
  const ticketStream:StreamTicket={parser:new DeepSeekStreamParser(),assembler:new DeepSeekStreamAssembler(),done:false};
  return new Promise<DeepSeekStreamAssembler>((resolve,reject)=>{
   let settled=false;let lastActivity=Date.now();
   const guard=setInterval(()=>{
    if(settled)return;
    if(Date.now()-lastActivity>idleTimeoutMs)settle(new DeepSeekError('timeout','DeepSeek 回复中断了，请稍后再试。'));
   },1000);
   const settle=(error:DeepSeekError|undefined):void=>{
    if(settled)return;settled=true;clearInterval(guard);
    this.active.delete(id);try{request.destroy();}catch(_){}
    if(error)reject(error);else resolve(ticketStream.assembler);
   };
   const onData=(payload:string):void=>{
    lastActivity=Date.now();
    try{ticketStream.assembler.push(payload);onEvent(payload);}
    catch(e){console.warn('SELF_DEEPSEEK_STREAM_EVENT_DROPPED');}
   };
   const onDone=():void=>{ticketStream.done=true;settle(undefined);};
   request.on('dataReceive',(chunk:ArrayBuffer)=>{
    lastActivity=Date.now();
    ticketStream.parser.push(chunk,onData,onDone);
   });
   request.on('dataEnd',()=>{if(!ticketStream.done)ticketStream.parser.flush(onData,onDone);settle(undefined);});
   request.requestInStream(DeepSeekConfig.BASE_URL+'/chat/completions',{
    method:http.RequestMethod.POST,
    header:{'Content-Type':'application/json','Authorization':'Bearer '+key},
    extraData:JSON.stringify(body),
    connectTimeout:DeepSeekConfig.CONNECT_TIMEOUT_MS,readTimeout:idleTimeoutMs,usingCache:false})
    .then((code:number)=>{
     if(code!==200){console.warn('SELF_DEEPSEEK_STREAM_HTTP '+code);settle(DeepSeekTransport.httpError(code));}
    })
    .catch((e:Error)=>{
     if(entry.cancelled)settle(new DeepSeekError('cancelled','这次请求已取消。'));
     else settle(DeepSeekTransport.connectionError(e));
    });
  });
 }
 /** Maps an HTTP status to a user-safe category and message; never includes the body. */
 static httpError(code:number):DeepSeekError{
  if(code===401)return new DeepSeekError('invalid_key','DeepSeek 密钥无效，请在设置里更新。');
  if(code===402)return new DeepSeekError('payment_required','DeepSeek 账户计费异常，请检查账户余额。');
  if(code===400||code===422)return new DeepSeekError('invalid_request','DeepSeek 没有接受这次请求（HTTP '+code+'）。');
  if(code===429)return new DeepSeekError('rate_limited','请求过于频繁，请稍后再试。');
  return new DeepSeekError('server_unavailable','DeepSeek 服务暂时不可用，请稍后再试。');
 }
 private static connectionError(e:Error|Object):DeepSeekError{
  const text=String(e).toLowerCase();
  if(text.includes('cancel'))return new DeepSeekError('cancelled','这次请求已取消。');
  if(text.includes('timeout')||text.includes('timed out'))return new DeepSeekError('timeout','DeepSeek 回复超时，请稍后再试。');
  return new DeepSeekError('network','网络连接失败，请检查网络后重试。');
 }
}
