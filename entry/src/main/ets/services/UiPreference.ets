import { common } from '@kit.AbilityKit';
import { fileIo as fs } from '@kit.CoreFileKit';
export interface UiSettings {language:string;accent:string;palette:string;motion:boolean;followChat:boolean;stylusHints:boolean;}
/** Presentation only. Never stores model authorization or camera permission. */
export class UiPreference {
 static load(context:common.UIAbilityContext):UiSettings{
  const defaults:UiSettings={language:'zh',accent:'#7C698F',palette:'quiet',motion:true,followChat:true,stylusHints:true};
  try{const value=JSON.parse(fs.readTextSync(context.filesDir+'/ui-settings.json')) as UiSettings;
   if(['zh','en','ja','ko'].includes(value.language))defaults.language=value.language;
   if(['#7C698F','#A5697C','#487F80','#947347'].includes(value.accent))defaults.accent=value.accent;
   if(['quiet','warm','clear'].includes(value.palette))defaults.palette=value.palette;
   if(typeof value.motion==='boolean')defaults.motion=value.motion;
   if(typeof value.followChat==='boolean')defaults.followChat=value.followChat;
   if(typeof value.stylusHints==='boolean')defaults.stylusHints=value.stylusHints;
  }catch(_){}return defaults;
 }
 static save(context:common.UIAbilityContext,value:UiSettings):void{
  const path=context.filesDir+'/ui-settings.json',temp=path+'.tmp';
  const file=fs.openSync(temp,fs.OpenMode.CREATE|fs.OpenMode.READ_WRITE|fs.OpenMode.TRUNC);
  try{fs.writeSync(file.fd,JSON.stringify(value));}finally{fs.closeSync(file);}fs.renameSync(temp,path);
 }
}
