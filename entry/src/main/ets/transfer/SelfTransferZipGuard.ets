import { fileIo as fs } from '@kit.CoreFileKit';
import { PackageValidationError, safeEntry } from './SelfTransferContract';
import { readAt, ascii } from './TransferFiles';

export interface ZipEntryInfo {path:string;size:number;compressedSize:number;localOffset:number;}
export interface ZipInspection {entries:ZipEntryInfo[];originalSize:number;}
function invalid():never{throw new PackageValidationError('模型压缩包损坏或包含不安全路径');}
function u64(view:DataView,offset:number):number{
  const n=view.getUint32(offset,true)+view.getUint32(offset+4,true)*4294967296;
  if(!Number.isSafeInteger(n))invalid();return n;
}

/** Read-only ZIP metadata preflight, NOT a ZIP codec. Official zlib performs all compression/extraction.
 * API 26 zlib has no entry enumeration. Inspect local AND central names before any extraction.
 * Supports classic ZIP and ZIP64, store/deflate, rejects encryption, links, overlaps and multipart archives.
 */
export async function inspectZip(path:string):Promise<ZipInspection>{
  const file=fs.openSync(path,fs.OpenMode.READ_ONLY);
  try{
    const size=fs.statSync(file.fd).size;if(size<22)invalid();
    const tailOffset=Math.max(0,size-65557),tail=new DataView(await readAt(file.fd,tailOffset,size-tailOffset));
    let eocd=-1;
    for(let i=tail.byteLength-22;i>=0;i--)if(tail.getUint32(i,true)===0x06054b50&&i+22+tail.getUint16(i+20,true)===tail.byteLength){eocd=i;break;}
    if(eocd<0||tail.getUint16(eocd+4,true)!==0||tail.getUint16(eocd+6,true)!==0)invalid();
    let count=tail.getUint16(eocd+10,true),centralSize=tail.getUint32(eocd+12,true),centralOffset=tail.getUint32(eocd+16,true);
    let centralEnd=tailOffset+eocd;
    if(count===65535||centralSize===4294967295||centralOffset===4294967295){
      const locatorOffset=tailOffset+eocd-20;if(locatorOffset<0)invalid();
      const locator=new DataView(await readAt(file.fd,locatorOffset,20));
      if(locator.getUint32(0,true)!==0x07064b50||locator.getUint32(4,true)!==0||locator.getUint32(16,true)!==1)invalid();
      const zip64Offset=u64(locator,8),record=new DataView(await readAt(file.fd,zip64Offset,56));
      if(record.getUint32(0,true)!==0x06064b50||record.getUint32(16,true)!==0||record.getUint32(20,true)!==0||
        zip64Offset+12+u64(record,4)!==locatorOffset||u64(record,24)!==u64(record,32))invalid();
      count=u64(record,32);centralSize=u64(record,40);centralOffset=u64(record,48);centralEnd=zip64Offset;
    }else if(tail.getUint16(eocd+8,true)!==count)invalid();
    // Metadata bounds protect the parser, without imposing a model byte-size business limit.
    if(count<1||count>4096||centralOffset+centralSize!==centralEnd||centralOffset<0)invalid();
    const entries:ZipEntryInfo[]=[],names:Set<string>=new Set<string>();let cursor=centralOffset,originalSize=0;
    const rangeEnds:number[]=[],rangeStarts:number[]=[];
    for(let index=0;index<count;index++){
      if(cursor+46>centralEnd)invalid();
      const fixed=new DataView(await readAt(file.fd,cursor,46));
      if(fixed.getUint32(0,true)!==0x02014b50)invalid();
      const flags=fixed.getUint16(8,true),method=fixed.getUint16(10,true),nameLength=fixed.getUint16(28,true),
        extraLength=fixed.getUint16(30,true),commentLength=fixed.getUint16(32,true),disk=fixed.getUint16(34,true);
      if((flags&0x2041)!==0||![0,8].includes(method)||disk!==0||nameLength<1||nameLength>512||cursor+46+nameLength+extraLength+commentLength>centralEnd)invalid();
      const name=ascii(await readAt(file.fd,cursor+46,nameLength));
      if(!safeEntry(name)||names.has(name))invalid();names.add(name);
      const unixType=(fixed.getUint32(38,true)>>>16)&0xf000;
      if(unixType!==0&&unixType!==0x8000&&unixType!==0x4000)invalid();
      if((unixType===0x4000)!==name.endsWith('/')&&unixType!==0)invalid();
      let unpacked=fixed.getUint32(24,true),packed=fixed.getUint32(20,true),local=fixed.getUint32(42,true);
      const extra=new DataView(await readAt(file.fd,cursor+46+nameLength,extraLength));
      let extraCursor=0,zip64=false;
      while(extraCursor<extraLength){
        if(extraCursor+4>extraLength)invalid();const tag=extra.getUint16(extraCursor,true),length=extra.getUint16(extraCursor+2,true);
        if(extraCursor+4+length>extraLength)invalid();
        if(tag===1){
          let p=extraCursor+4;const end=p+length;zip64=true;
          if(unpacked===4294967295){if(p+8>end)invalid();unpacked=u64(extra,p);p+=8;}
          if(packed===4294967295){if(p+8>end)invalid();packed=u64(extra,p);p+=8;}
          if(local===4294967295){if(p+8>end)invalid();local=u64(extra,p);}
        }
        // Alternate Unicode paths could disagree with the checked ASCII path in an extractor.
        if(tag===0x7075)invalid();extraCursor+=4+length;
      }
      if(!zip64&&(unpacked===4294967295||packed===4294967295||local===4294967295))invalid();
      if(local+30>centralOffset||name.endsWith('/')&&unpacked!==0)invalid();
      const localHeader=new DataView(await readAt(file.fd,local,30));
      if(localHeader.getUint32(0,true)!==0x04034b50||localHeader.getUint16(6,true)!==flags||localHeader.getUint16(8,true)!==method||
        localHeader.getUint16(26,true)!==nameLength)invalid();
      const localName=ascii(await readAt(file.fd,local+30,nameLength));
      if(localName!==name)invalid();
      const localExtraLength=localHeader.getUint16(28,true);
      const localExtra=new DataView(await readAt(file.fd,local+30+nameLength,localExtraLength));
      let localCursor=0,localUnpacked=localHeader.getUint32(22,true),localPacked=localHeader.getUint32(18,true);
      while(localCursor<localExtraLength){
        if(localCursor+4>localExtraLength)invalid();
        const tag=localExtra.getUint16(localCursor,true),length=localExtra.getUint16(localCursor+2,true),limit=localCursor+4+length;
        if(limit>localExtraLength||tag===0x7075)invalid();
        if(tag===1){
          let p=localCursor+4;
          if(localUnpacked===4294967295){if(p+8>limit)invalid();localUnpacked=u64(localExtra,p);p+=8;}
          if(localPacked===4294967295){if(p+8>limit)invalid();localPacked=u64(localExtra,p);}
        }
        localCursor=limit;
      }
      if((flags&8)===0&&(localUnpacked!==unpacked||localPacked!==packed||localHeader.getUint32(14,true)!==fixed.getUint32(16,true)))invalid();
      const end=local+30+nameLength+localExtraLength+packed;
      if(end>centralOffset||!Number.isSafeInteger(end))invalid();
      for(let r=0;r<rangeStarts.length;r++)if(local<rangeEnds[r]&&end>rangeStarts[r])invalid();
      rangeStarts.push(local);rangeEnds.push(end);
      originalSize+=unpacked;if(!Number.isSafeInteger(originalSize))invalid();
      if(name==='manifest.json'&&unpacked>65536||name==='viewer/viewer_state.json'&&unpacked>65536)invalid();
      entries.push({path:name,size:unpacked,compressedSize:packed,localOffset:local});
      cursor+=46+nameLength+extraLength+commentLength;
    }
    if(cursor!==centralEnd||!names.has('manifest.json')||!names.has('model/model.ply'))invalid();
    return {entries,originalSize};
  }catch(error){if(error instanceof PackageValidationError)throw error;throw new PackageValidationError('无法读取模型压缩包');}
  finally{fs.closeSync(file);}
}
