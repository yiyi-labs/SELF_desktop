import { fileIo as fs, hash, statfs } from '@kit.CoreFileKit';
import { util } from '@kit.ArkTS';
import { PackageValidationError } from './SelfTransferContract';

export function makeDir(path:string):void{if(!fs.accessSync(path))fs.mkdirSync(path,true);}
export async function ensureSpace(path:string,bytes:number):Promise<void>{
  if(!Number.isSafeInteger(bytes)||bytes<0||await statfs.getFreeSize(path)<bytes+16*1024*1024)
    throw new PackageValidationError('存储空间不足，请清理空间后重试');
}
export function writeText(path:string,text:string):void{
  const file=fs.openSync(path,fs.OpenMode.CREATE|fs.OpenMode.READ_WRITE|fs.OpenMode.TRUNC);
  try{const bytes=new util.TextEncoder().encodeInto(text);if(fs.writeSync(file.fd,bytes.buffer)!==bytes.byteLength)throw new Error('Short metadata write');fs.fsyncSync(file.fd);}
  finally{fs.closeSync(file);}
}
export async function fileSha256(path:string):Promise<string>{return (await hash.hash(path,'sha256')).toLowerCase();}
export async function readAt(fd:number,offset:number,length:number):Promise<ArrayBuffer>{
  if(!Number.isSafeInteger(offset)||offset<0||!Number.isSafeInteger(length)||length<0||length>1048576)
    throw new PackageValidationError('模型包文件范围无效');
  const buffer=new ArrayBuffer(length);let read=0;
  while(read<length){const part=new ArrayBuffer(length-read);const n=await fs.read(fd,part,{offset:offset+read,length:part.byteLength});
    if(n<=0)throw new PackageValidationError('模型文件不完整');new Uint8Array(buffer).set(new Uint8Array(part,0,n),read);read+=n;}
  return buffer;
}
export function ascii(bytes:ArrayBuffer):string{
  const view=new Uint8Array(bytes);let value='';for(let i=0;i<view.length;i++){if(view[i]>127||view[i]===0)throw new PackageValidationError('模型包文件名或头部编码不支持');value+=String.fromCharCode(view[i]);}return value;
}
export function boundedText(path:string,limit:number=65536):string{
  if(!fs.accessSync(path)||!fs.statSync(path).isFile()||fs.statSync(path).size>limit)throw new PackageValidationError('模型包元数据缺失或过大');
  return fs.readTextSync(path);
}
/** Only used on directories created and owned by SELF transfer, never on external URI paths. */
export function removeTransferTree(path:string,ownedRoot:string):void{
  if(!path.startsWith(ownedRoot+'/')||path.includes('/../')||path.includes('\\'))throw new Error('Transfer cleanup outside owned directory');
  if(!fs.accessSync(path))return;
  const stat=fs.lstatSync(path);
  if(stat.isSymbolicLink()||!stat.isDirectory()){fs.unlinkSync(path);return;}
  for(const name of fs.listFileSync(path)){
    if(!name||name.includes('/')||name.includes('\\')||name==='.'||name==='..')throw new Error('Invalid transfer cleanup entry');
    removeTransferTree(path+'/'+name,ownedRoot);
  }
  fs.rmdirSync(path);
}
