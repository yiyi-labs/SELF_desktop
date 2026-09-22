import {TransferReceiver,decode64,encode64,type TransferHeader} from './transfer.ts';
export type Envelope={schemaVersion:number,sessionId:string,assetId:string,assetVersion:string,requestId:string,revision:number,type:string,payload:any};
export class Endpoint {
  private port:MessagePort|null=null;private incoming=new TransferReceiver();
  private incomingHeader:TransferHeader|null=null;private incomingOffset=0;
  private queue:Promise<void>=Promise.resolve();
  sessionId='';assetId='';assetVersion='';revision=0;
  webgl2=false;startupError='';
  onMessage:(message:Envelope)=>Promise<void>=async()=>{};
  onBytes:(header:TransferHeader,bytes:Uint8Array)=>Promise<void>=async()=>{};
  connect(port:MessagePort){this.port?.close();this.port=port;port.onmessage=e=>{this.queue=this.queue.then(()=>this.receive(e.data));};port.start();this.send('READY',{webgl2:this.webgl2,message:this.startupError,arrayBuffer:true,three:'0.186.0'});}
  async receive(raw:string|ArrayBuffer){
    try{
      if(!this.webgl2)throw Error(this.startupError||'3D 镜面尚未就绪');
      if(raw instanceof ArrayBuffer){if(!this.incomingHeader)throw Error('Unframed binary');this.incoming.chunk(this.incomingHeader.transferId,this.incomingOffset,new Uint8Array(raw));this.incomingOffset+=raw.byteLength;return;}
      const m=JSON.parse(raw)as Envelope;
      if(m.schemaVersion!==1||typeof m.type!=='string'||!Number.isInteger(m.revision)||m.revision<0)throw Error('Invalid envelope');
      if(m.type==='INIT'){this.incoming.cancel();this.incomingHeader=null;this.sessionId=m.sessionId;this.assetId=m.assetId;this.assetVersion=m.assetVersion;this.revision=m.revision;this.send('INITIALIZED',{},m.requestId);return;}
      if(m.sessionId!==this.sessionId||m.assetId!==this.assetId||m.assetVersion!==this.assetVersion||m.revision<this.revision)throw Error('Stale envelope');
      if(m.type==='TRANSFER_BEGIN'){if(m.payload.sessionId!==m.sessionId||m.payload.assetId!==m.assetId||m.payload.assetVersion!==m.assetVersion||m.payload.revision!==m.revision)throw Error('Transfer association mismatch');this.incoming.begin(m.payload);this.incomingHeader=m.payload;this.incomingOffset=0;return;}
      if(m.type==='TRANSFER_CHUNK'){const p=m.payload,bytes=decode64(p.data);this.incoming.chunk(p.transferId,p.offset,bytes);return;}
      if(m.type==='TRANSFER_CANCEL'){this.incoming.cancel();this.incomingHeader=null;return;}
      if(m.type==='TRANSFER_END'){const complete=this.incoming.end(m.payload.transferId);this.incomingHeader=null;await this.onBytes(complete.header,complete.bytes);this.send('TRANSFER_ACCEPTED',{transferId:complete.header.transferId},m.requestId);return;}
      await this.onMessage(m);
    }catch(error){this.incoming.cancel();this.incomingHeader=null;this.send('RENDER_FAILED',{message:String(error)});}
  }
  send(type:string,payload:any,requestId=''){const message:Envelope={schemaVersion:1,sessionId:this.sessionId,assetId:this.assetId,assetVersion:this.assetVersion,requestId,revision:this.revision,type,payload};this.port?.postMessage(JSON.stringify(message));}
  sendBytes(kind:string,bytes:Uint8Array,requestId=''){
    const h:TransferHeader={transferId:crypto.randomUUID(),sessionId:this.sessionId,assetId:this.assetId,assetVersion:this.assetVersion,revision:this.revision,kind,length:bytes.length};
    this.send('TRANSFER_BEGIN',h,requestId);
    for(let offset=0;offset<bytes.length;offset+=65536)this.port?.postMessage(bytes.buffer.slice(bytes.byteOffset+offset,bytes.byteOffset+Math.min(offset+65536,bytes.length)));
    this.send('TRANSFER_END',{transferId:h.transferId},requestId);
  }
  dispose(){this.port?.close();this.port=null;this.incoming.cancel();}
}
