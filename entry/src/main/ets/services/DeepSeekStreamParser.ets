import { util } from '@kit.ArkTS';
import { DeepSeekStreamChunk, DeepSeekToolCall, DeepSeekToolCallFunction } from './DeepSeekTypes';

interface EventBoundary{index:number;length:number;}
interface StreamResult{content:string;toolCalls:DeepSeekToolCall[];finishReason:string|null;}

/**
 * Incremental SSE framing over arbitrary HTTP chunk boundaries.
 * A chunk may hold half an event, several events, split UTF-8 bytes or keep-alive
 * blanks; only complete `data:` events are emitted, the rest stays buffered.
 */
export class DeepSeekStreamParser {
 private buffer:string='';
 private decoder:util.TextDecoder=new util.TextDecoder('utf-8');
 /** Feeds one raw network chunk; onData fires once per complete SSE data event (payload without the `data:` prefix). */
 push(chunk:ArrayBuffer,onData:(data:string)=>void,onDone:()=>void):void{
  this.buffer+=this.decoder.decodeWithStream(new Uint8Array(chunk),{stream:true});
  let boundary:EventBoundary=DeepSeekStreamParser.eventEnd(this.buffer);
  while(boundary.index>=0){
   const event=this.buffer.substring(0,boundary.index);
   this.buffer=this.buffer.substring(boundary.index+boundary.length);
   const payload=DeepSeekStreamParser.eventData(event);
   if(payload!==undefined){
    if(payload==='[DONE]'){onDone();return;}
    onData(payload);
   }
   boundary=DeepSeekStreamParser.eventEnd(this.buffer);
  }
 }
 /** Flushes a trailing event that arrived without a final blank line. */
 flush(onData:(data:string)=>void,onDone:()=>void):void{
  this.buffer+=this.decoder.decodeWithStream(new Uint8Array(0),{stream:false});
  const rest=this.buffer;this.buffer='';
  if(!rest.trim())return;
  const payload=DeepSeekStreamParser.eventData(rest);
  if(payload===undefined)return;
  if(payload==='[DONE]'){onDone();return;}
  onData(payload);
 }
 private static eventEnd(text:string):EventBoundary{
  const lf=text.indexOf('\n\n'),crlf=text.indexOf('\r\n\r\n');
  if(lf<0&&crlf<0){const none:EventBoundary={index:-1,length:0};return none;}
  if(crlf<0||(lf>=0&&lf<crlf)){const hit:EventBoundary={index:lf,length:2};return hit;}
  const crlfHit:EventBoundary={index:crlf,length:4};return crlfHit;
 }
 /** Joins the data lines of one event; comments, blanks and field lines without payload yield undefined. */
 private static eventData(event:string):string|undefined{
  const lines=event.split(/\r?\n/);
  const data:string[]=[];
  for(const line of lines){
   if(!line||line.startsWith(':'))continue;
   if(line.startsWith('data:'))data.push(line.charAt(5)===' '?line.substring(6):line.substring(5));
  }
  if(!data.length)return undefined;
  return data.join('\n').trim();
 }
}

/**
 * Accumulates streamed deltas into the same shape a non-stream response offers.
 * Tool-call arguments arrive in fragments and are only parseable once complete.
 */
export class DeepSeekStreamAssembler {
 private content:string='';
 private toolCalls:DeepSeekToolCall[]=[];
 private finishReason:string|null=null;
 push(payload:string):void{
  let chunk:DeepSeekStreamChunk;
  try{chunk=JSON.parse(payload) as DeepSeekStreamChunk;}catch(_){return;}
  if(!chunk.choices||!chunk.choices.length)return;
  const choice=chunk.choices[0];
  if(choice.finish_reason)this.finishReason=choice.finish_reason;
  const delta=choice.delta;
  if(!delta)return;
  if(delta.content)this.content+=delta.content;
  if(delta.tool_calls){
   for(const call of delta.tool_calls){
    const index=call.index||0;
    while(this.toolCalls.length<=index){
     const fresh:DeepSeekToolCall={id:'',type:'function',function:{name:'',arguments:''}};
     this.toolCalls.push(fresh);
    }
    const target=this.toolCalls[index];
    if(call.id)target.id+=call.id;
    if(call.type)target.type=call.type;
    if(call.function){
     if(call.function.name)target.function.name+=call.function.name;
     if(call.function.arguments)target.function.arguments+=call.function.arguments;
    }
   }
  }
 }
 result():StreamResult{
  const result:StreamResult={content:this.content,toolCalls:this.toolCalls,finishReason:this.finishReason};
  return result;
 }
}
