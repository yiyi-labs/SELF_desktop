import { common } from '@kit.AbilityKit';
import { fileIo as fs } from '@kit.CoreFileKit';
import { util } from '@kit.ArkTS';
import { huks } from '@kit.UniversalKeystoreKit';
import { cryptoFramework } from '@kit.CryptoArchitectureKit';
import { http } from '@kit.NetworkKit';
import { DeepSeekConfig } from './DeepSeekConfig';
import { DeepSeekError } from './DeepSeekTypes';
import { DeepSeekRuntimeState } from './DeepSeekRuntimeState';

interface SealedResult{cipher:Uint8Array;tag:Uint8Array;}
interface SavedCredential{schemaVersion:number;nonceBase64:string;cipherBase64:string;tagBase64:string;tail:string;savedAt:number;}
/**
 * The DeepSeek API key never exists in plaintext storage. HUKS owns an AES-256-GCM key
 * generated on this device; the app sandbox only keeps ciphertext, nonce and a masked tail.
 * Plaintext exists briefly inside loadForRequest to build one Authorization header.
 */
export class DeepSeekCredentialStore {
 private static readonly alias:string='self.deepseek.apikey.v1';
 private static readonly fileName:string='/deepseek-credential.json';
 private static readonly encoder:util.TextEncoder=new util.TextEncoder('utf-8');
 private static readonly decoder:util.TextDecoder=new util.TextDecoder('utf-8');

 private static keyProps():huks.HuksParam[]{
  return[
   {tag:huks.HuksTag.HUKS_TAG_ALGORITHM,value:huks.HuksKeyAlg.HUKS_ALG_AES},
   {tag:huks.HuksTag.HUKS_TAG_KEY_SIZE,value:huks.HuksKeySize.HUKS_AES_KEY_SIZE_256},
   {tag:huks.HuksTag.HUKS_TAG_PURPOSE,value:huks.HuksKeyPurpose.HUKS_KEY_PURPOSE_ENCRYPT|huks.HuksKeyPurpose.HUKS_KEY_PURPOSE_DECRYPT},
   {tag:huks.HuksTag.HUKS_TAG_PADDING,value:huks.HuksKeyPadding.HUKS_PADDING_NONE},
   {tag:huks.HuksTag.HUKS_TAG_BLOCK_MODE,value:huks.HuksCipherMode.HUKS_MODE_GCM}];
 }
 private static opProps(purpose:number,nonce:Uint8Array):huks.HuksParam[]{
  return[
   {tag:huks.HuksTag.HUKS_TAG_ALGORITHM,value:huks.HuksKeyAlg.HUKS_ALG_AES},
   {tag:huks.HuksTag.HUKS_TAG_PURPOSE,value:purpose},
   {tag:huks.HuksTag.HUKS_TAG_PADDING,value:huks.HuksKeyPadding.HUKS_PADDING_NONE},
   {tag:huks.HuksTag.HUKS_TAG_BLOCK_MODE,value:huks.HuksCipherMode.HUKS_MODE_GCM},
   {tag:huks.HuksTag.HUKS_TAG_NONCE,value:nonce}];
 }
 private static async ensureKey():Promise<void>{
  const props=DeepSeekCredentialStore.keyProps();
  // On real devices isKeyItemExist rejects when the alias is absent; treat that as absent.
  try{if(await huks.isKeyItemExist(DeepSeekCredentialStore.alias,{properties:props}))return;}catch(_){}
  try{await huks.deleteKeyItem(DeepSeekCredentialStore.alias,{properties:[]});}catch(_){}
  await huks.generateKeyItem(DeepSeekCredentialStore.alias,{properties:props});
 }
 /**
  * GCM with a detached tag, matching the TEE-backed HUKS path on this SDK:
  * encrypt returns ciphertext||tag (tag = last 16 bytes); decrypt receives the tag
  * through HUKS_TAG_AE_TAG and the ciphertext alone.
  */
 /**
  * Device-verified HUKS GCM flow: updateSession returns the ciphertext, finishSession
  * returns the 16-byte tag; decryption passes that tag via HUKS_TAG_AE_TAG and reads
  * the plaintext from the two calls' outputs.
  */
 private static async encrypt(nonce:Uint8Array,plain:Uint8Array):Promise<SealedResult>{
  const props=DeepSeekCredentialStore.opProps(huks.HuksKeyPurpose.HUKS_KEY_PURPOSE_ENCRYPT,nonce);
  const session=await huks.initSession(DeepSeekCredentialStore.alias,{properties:props});
  const updated=await huks.updateSession(session.handle,{properties:props,inData:plain});
  const finished=await huks.finishSession(session.handle,{properties:props,inData:new Uint8Array(0)});
  const cipher=updated?.outData??new Uint8Array(0);
  const tag=finished?.outData??new Uint8Array(0);
  if(!cipher.length||tag.length!==16)throw new Error('huks_bad_gcm_output');
  const sealed:SealedResult={cipher,tag};return sealed;
 }
 private static async decrypt(nonce:Uint8Array,cipher:Uint8Array,tag:Uint8Array):Promise<Uint8Array>{
  const props=DeepSeekCredentialStore.opProps(huks.HuksKeyPurpose.HUKS_KEY_PURPOSE_DECRYPT,nonce)
   .concat([{tag:huks.HuksTag.HUKS_TAG_AE_TAG,value:tag} as huks.HuksParam]);
  const session=await huks.initSession(DeepSeekCredentialStore.alias,{properties:props});
  const updated=await huks.updateSession(session.handle,{properties:props,inData:cipher});
  const finished=await huks.finishSession(session.handle,{properties:props,inData:new Uint8Array(0)});
  const head=updated?.outData??new Uint8Array(0);
  const tail=finished?.outData??new Uint8Array(0);
  const plain=new Uint8Array(head.length+tail.length);
  plain.set(head,0);plain.set(tail,head.length);
  if(!plain.length)throw new Error('huks_no_output');
  return plain;
 }
 private static path(context:common.UIAbilityContext):string{return context.filesDir+DeepSeekCredentialStore.fileName;}
 /** Saves or replaces the key: HUKS-encrypts it and persists ciphertext + nonce atomically. */
 static async save(context:common.UIAbilityContext,key:string):Promise<void>{
  const trimmed=key.trim();
  if(!trimmed)throw new DeepSeekError('invalid_request','请先输入 DeepSeek API Key。');
  await DeepSeekCredentialStore.ensureKey();
  const nonce=cryptoFramework.createRandom().generateRandomSync(12).data;
  const sealed=await DeepSeekCredentialStore.encrypt(nonce,DeepSeekCredentialStore.encoder.encodeInto(trimmed));
  const cipher=sealed.cipher,tag=sealed.tag;
  const base64=new util.Base64Helper();
  const saved:SavedCredential={schemaVersion:1,
   nonceBase64:base64.encodeToStringSync(nonce),cipherBase64:base64.encodeToStringSync(cipher),
   tagBase64:base64.encodeToStringSync(tag),
   tail:trimmed.length>4?trimmed.substring(trimmed.length-4):'',savedAt:Date.now()};
  const path=DeepSeekCredentialStore.path(context),temp=path+'.tmp';
  const file=fs.openSync(temp,fs.OpenMode.CREATE|fs.OpenMode.READ_WRITE|fs.OpenMode.TRUNC);
  try{fs.writeSync(file.fd,JSON.stringify(saved));}finally{fs.closeSync(file);}
  fs.renameSync(temp,path);
 }
 static exists(context:common.UIAbilityContext):boolean{
  try{return fs.accessSync(DeepSeekCredentialStore.path(context));}catch(_){return false;}
 }
 /** Masked presence for settings UI; never reconstructs or echoes the stored key. */
 static masked(context:common.UIAbilityContext):string{
  if(!DeepSeekCredentialStore.exists(context))return'';
  try{
   const saved=JSON.parse(fs.readTextSync(DeepSeekCredentialStore.path(context))) as SavedCredential;
   if(saved.schemaVersion===1&&saved.tail)return'sk-••••••••••'+saved.tail;
  }catch(_){}
  return'已配置';
 }
 /** Decrypts the key for one request. Callers must not retain or log the returned value. */
 static async loadForRequest(context:common.UIAbilityContext):Promise<string>{
  if(!DeepSeekCredentialStore.exists(context))throw new DeepSeekError('missing_key','尚未配置 DeepSeek API Key，请先在设置里保存。');
  try{
   const base64=new util.Base64Helper();
   const saved=JSON.parse(fs.readTextSync(DeepSeekCredentialStore.path(context))) as SavedCredential;
   if(saved.schemaVersion!==1||!saved.nonceBase64||!saved.cipherBase64)throw new Error('bad_metadata');
   const nonce=base64.decodeSync(saved.nonceBase64);
   const cipher=base64.decodeSync(saved.cipherBase64);
   const tag=base64.decodeSync(saved.tagBase64);
   const plain=await DeepSeekCredentialStore.decrypt(nonce,cipher,tag);
   const key=DeepSeekCredentialStore.decoder.decodeWithStream(plain,{stream:false});
   if(!key)throw new Error('empty');
   return key;
  }catch(e){
   if(e instanceof DeepSeekError)throw e;
   console.warn('SELF_DEEPSEEK_CREDENTIAL_READ_FAILED');
   throw new DeepSeekError('invalid_key','DeepSeek 密钥无法读取，请重新保存。');
  }
 }
 /** Removes ciphertext, metadata and the dedicated HUKS alias — no ghost configuration remains. */
 static async delete(context:common.UIAbilityContext):Promise<void>{
  const path=DeepSeekCredentialStore.path(context);
  if(fs.accessSync(path))fs.unlinkSync(path);
  try{await huks.deleteKeyItem(DeepSeekCredentialStore.alias,{properties:[]});}catch(_){}
 }
 /**
  * One light validity check performed only on an explicit user action. It sends no face,
  * product, history or 3D data — just an unauthenticated-models GET with the Bearer header.
  */
 static async verify(key:string):Promise<void>{
  if(!DeepSeekRuntimeState.allowRequests)throw new DeepSeekError('background','SELF 正在后台，无法验证密钥。');
  const request=http.createHttp();
  try{
   const response=await request.request(DeepSeekConfig.BASE_URL+'/models',{
    method:http.RequestMethod.GET,expectDataType:http.HttpDataType.STRING,
    header:{'Authorization':'Bearer '+key},connectTimeout:DeepSeekConfig.CONNECT_TIMEOUT_MS,
    readTimeout:15000,usingCache:false});
   if(response.responseCode===200)return;
   if(response.responseCode===401)throw new DeepSeekError('invalid_key','DeepSeek 密钥无效。');
   if(response.responseCode===402)throw new DeepSeekError('payment_required','DeepSeek 账户计费异常。');
   throw new DeepSeekError('server_unavailable','暂时无法验证密钥（HTTP '+response.responseCode+'），请稍后再试。');
  }catch(e){
   if(e instanceof DeepSeekError)throw e;
   throw new DeepSeekError('network','暂时无法连接 DeepSeek 验证密钥。');
  }finally{request.destroy();}
 }
}
