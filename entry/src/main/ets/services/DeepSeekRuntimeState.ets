/**
 * One foreground/background truth for every DeepSeek call. EntryAbility is the only writer;
 * pages and clients only read allowRequests, so no page judges lifecycle by itself.
 * Entering the background denies and cancels; returning to the foreground only re-allows —
 * it never issues any request or ping on its own.
 */
export interface DeepSeekLifecycleListener{onDeepSeekBackground():void;}
export class DeepSeekRuntimeState {
 private static foreground:boolean=true;
 private static listeners:DeepSeekLifecycleListener[]=[];
 static setForeground(value:boolean):void{
  if(DeepSeekRuntimeState.foreground===value)return;
  DeepSeekRuntimeState.foreground=value;
  if(!value)for(const listener of DeepSeekRuntimeState.listeners.slice())listener.onDeepSeekBackground();
 }
 static get allowRequests():boolean{return DeepSeekRuntimeState.foreground;}
 static addListener(listener:DeepSeekLifecycleListener):void{
  if(!DeepSeekRuntimeState.listeners.includes(listener))DeepSeekRuntimeState.listeners.push(listener);
 }
}
