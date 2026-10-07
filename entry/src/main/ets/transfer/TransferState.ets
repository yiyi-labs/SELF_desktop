import { PreparedTransfer, ImportedTransfer } from './SelfTransferContract';
export enum TransferIntent { NONE='NONE', SEND='SEND', RECEIVE='RECEIVE' }
export enum TransferPolicy { AUTO='AUTO', FORCE_RECEIVE='FORCE_RECEIVE' }
export enum TransferPhase { IDLE='IDLE', PREPARING_SEND='PREPARING_SEND', SEND_READY='SEND_READY',
  RECEIVE_READY='RECEIVE_READY', TRANSFERRING='TRANSFERRING', IMPORTING='IMPORTING', ERROR='ERROR' }
export interface TransferSurface {kind:string;modelId:string;revision:string;}
export interface TransferSnapshot {intent:TransferIntent;phase:TransferPhase;policy:TransferPolicy;message:string;}
export interface TransferTransport {
  supported():boolean;
  automaticReceive():boolean;
  listenSend(prepared:PreparedTransfer,onBegin:()=>boolean,onSubmitted:()=>void,onError:(error:Error)=>void):void;
  listenReceive(onBegin:()=>boolean,onFile:(path:string)=>void,onError:(error:Error)=>void):void;
  clear():void;
}
export interface TransferModels {
  prepare(modelId:string,revision:string):Promise<PreparedTransfer>;
  importPackage(path:string,cancelled:()=>boolean):Promise<ImportedTransfer>;
}
export function surfaceIntent(surface:TransferSurface,policy:TransferPolicy,foreground:boolean):TransferIntent {
  if(!foreground||surface.kind==='BUSY'||surface.kind==='NONE')return TransferIntent.NONE;
  if(surface.kind==='VIEWER')return policy===TransferPolicy.FORCE_RECEIVE?TransferIntent.RECEIVE:
    surface.modelId?TransferIntent.SEND:TransferIntent.NONE;
  return surface.kind==='HOME'||surface.kind==='LIST'?TransferIntent.RECEIVE:TransferIntent.NONE;
}
