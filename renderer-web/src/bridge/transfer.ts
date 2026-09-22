// Same framing is used for ArrayBuffer and optional base64 adapters. No partial file may be committed.
export type TransferHeader={transferId:string,sessionId:string,assetId:string,assetVersion:string,revision:number,kind:string,length:number};
export class TransferReceiver {
  private header:TransferHeader|null=null;
  private data:Uint8Array|null=null;
  private offset=0;
  readonly maxBytes=32*1024*1024;
  begin(h:TransferHeader):void{
    if(this.header)throw Error('Transfer already active');
    if(!/^[a-zA-Z0-9_-]{1,100}$/.test(h.transferId)||!Number.isInteger(h.length)||h.length<=0||h.length>this.maxBytes||!Number.isInteger(h.revision)||h.revision<0)throw Error('Invalid transfer header');
    this.header={...h};this.data=new Uint8Array(h.length);this.offset=0;
  }
  chunk(id:string,offset:number,bytes:Uint8Array):void {
    if(!this.header||!this.data||id!==this.header.transferId||offset!==this.offset||bytes.length===0||offset+bytes.length>this.data.length){this.cancel();throw Error('Out-of-order or invalid chunk');}
    this.data.set(bytes,offset);this.offset+=bytes.length;
  }
  end(id:string):{header:TransferHeader,bytes:Uint8Array}{
    if(!this.header||!this.data||this.header.transferId!==id||this.offset!==this.data.length){this.cancel();throw Error('Incomplete transfer');}
    const result={header:this.header,bytes:this.data};this.cancel();return result;
  }
  cancel():void{this.header=null;this.data=null;this.offset=0;}
}
export function encode64(bytes:Uint8Array):string{let s='';for(const v of bytes)s+=String.fromCharCode(v);return btoa(s);}
export function decode64(s:string):Uint8Array{if(!/^[A-Za-z0-9+/]*={0,2}$/.test(s)||s.length%4!==0)throw Error('Invalid base64');return Uint8Array.from(atob(s),c=>c.charCodeAt(0));}
