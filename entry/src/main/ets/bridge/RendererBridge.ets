import { webview } from '@kit.ArkWeb';
import { SceneView } from '../domain/EditPlan';
export interface MessagePayload {
  action?:string;
  serial?:number;
  preset?:string;
  strength?:number;
  count?:number;
  total?:number;
  x?:number;
  y?:number;
  images?:number;
  maskBase64?:string;
  regionId?:string;
  layers?: GsRenderLayer[];
  view?: SceneView;
  motion?: boolean;
  animate?:boolean;
  palette?: string;
  transferId?: string;
  kind?: string;
  length?: number;
  tool?: string;
  width?: number;
  height?: number;
  message?: string;
  text?: string;
  operations?: RenderOperation[];
  protectionId?: string;
  protectionRuleId?: string;
  protectedSnapshot?: number;
  anchorOperations?: RenderOperation[];
  webgl2?: boolean;
  light?: boolean;
}
export interface GsRenderLayer {maskBase64:string;preset:string;strength:number;}
export interface RenderOperation {
  compositingVersion?:string;
  protectionException?: string;
  operationId: string;
  regionId: string;
  color: number[];
  absoluteStrength: number;
}
export interface Envelope {
  schemaVersion: number;
  sessionId: string;
  assetId: string;
  assetVersion: string;
  requestId: string;
  revision: number;
  type: string;
  payload: MessagePayload;
}
export class RendererBridge {
  private ports: webview.WebMessagePort[] = [];
  sessionId: string = 'session-' + Date.now();
  assetId: string = 'sample-lee';
  assetVersion: string = 'lee-r186-self2';
  revision: number = 0;
  ready: boolean = false;
  onMessage: (message: Envelope) => void = () => {};
  onBytes: (kind: string, bytes: ArrayBuffer) => void = () => {};
  private incoming: MessagePayload | undefined = undefined;
  private incomingBytes: ArrayBuffer | undefined = undefined;
  private incomingOffset: number = 0;
  attach(controller: webview.WebviewController): void {
    this.dispose();
    this.ports = controller.createWebMessagePorts(true);
    this.ports[0].onMessageEventExt((event: webview.WebMessageExt) => {
      try {
        if (event.getType() === webview.WebMessageType.ARRAY_BUFFER) {
          if (!this.incoming || !this.incomingBytes) { throw new Error('Unframed binary'); }
          const data = event.getArrayBuffer();
          if (!data.byteLength || this.incomingOffset+data.byteLength > this.incomingBytes.byteLength) { throw new Error('Binary length mismatch'); }
          new Uint8Array(this.incomingBytes).set(new Uint8Array(data),this.incomingOffset);this.incomingOffset+=data.byteLength;
          return;
        }
        if (event.getType() !== webview.WebMessageType.STRING) { return; }
        const m = JSON.parse(event.getString()) as Envelope;
        if (m.schemaVersion !== 1) { return; }
        if (m.type === 'READY') {
          this.ready = m.payload.webgl2 === true;
          if(this.ready)this.send('INIT', {});
          this.onMessage(m);return;
        }
        if (m.sessionId !== this.sessionId || m.assetId !== this.assetId || m.assetVersion !== this.assetVersion || m.revision !== this.revision) { return; }
        if (m.type === 'TRANSFER_BEGIN') {
          if (this.incoming || !m.payload.length || m.payload.length > 33554432) { throw new Error('Invalid incoming transfer'); }
          this.incoming = m.payload;this.incomingBytes=new ArrayBuffer(m.payload.length);this.incomingOffset=0;return;
        }
        if(m.type==='TRANSFER_CANCEL'){this.incoming=undefined;this.incomingBytes=undefined;this.incomingOffset=0;return;}
        if (m.type === 'TRANSFER_END') {
          if (!this.incoming || this.incoming.transferId !== m.payload.transferId || !this.incomingBytes || this.incomingOffset!==this.incomingBytes.byteLength) { throw new Error('Incomplete transfer'); }
          this.onBytes(this.incoming.kind || '', this.incomingBytes);
          this.incoming = undefined; this.incomingBytes = undefined; return;
        }
        this.onMessage(m);
      } catch (error) {
        this.incoming = undefined; this.incomingBytes = undefined;
        const failure: Envelope = {schemaVersion:1,sessionId:this.sessionId,assetId:this.assetId,assetVersion:this.assetVersion,revision:this.revision,requestId:'',type:'RENDER_FAILED',payload:{message:String(error)}};
        this.onMessage(failure);
      }
    });
    controller.postMessage('SELF_PORT_V1', [this.ports[1]], '*');
  }
  send(type: string, payload: MessagePayload, requestId: string = ''): void {
    if (!this.ready) { throw new Error('Renderer is not ready'); }
    if(type==='INIT'){this.incoming=undefined;this.incomingBytes=undefined;this.incomingOffset=0;}
    const message: Envelope = {schemaVersion:1,sessionId:this.sessionId,assetId:this.assetId,assetVersion:this.assetVersion,requestId,revision:this.revision,type,payload};
    const frame = new webview.WebMessageExt(); frame.setType(webview.WebMessageType.STRING); frame.setString(JSON.stringify(message));
    this.ports[0].postMessageEventExt(frame);
  }
  sendBytes(kind: string, bytes: Uint8Array): void {
    const id = 'bytes-' + Date.now() + '-' + Math.floor(Math.random()*100000);
    // Framing fields are duplicated for receiver's independent asset/version verification.
    const header: TransferPayload = {transferId:id,kind,length:bytes.byteLength,sessionId:this.sessionId,assetId:this.assetId,assetVersion:this.assetVersion,revision:this.revision};
    this.send('TRANSFER_BEGIN', header);
    for(let offset=0;offset<bytes.byteLength;offset+=65536){
      const frame = new webview.WebMessageExt(); frame.setType(webview.WebMessageType.ARRAY_BUFFER);
      frame.setArrayBuffer(bytes.buffer.slice(bytes.byteOffset+offset,bytes.byteOffset+Math.min(offset+65536,bytes.byteLength)) as ArrayBuffer);
      this.ports[0].postMessageEventExt(frame);
    }
    this.send('TRANSFER_END', {transferId:id});
  }
  dispose(): void {
    this.ready = false;
    this.ports.forEach((p: webview.WebMessagePort) => { try { p.close(); } catch (error) {} });
    this.ports = []; this.incoming = undefined; this.incomingBytes = undefined;
  }
}
interface TransferPayload extends MessagePayload {
  sessionId: string;
  assetId: string;
  assetVersion: string;
  revision: number;
}
