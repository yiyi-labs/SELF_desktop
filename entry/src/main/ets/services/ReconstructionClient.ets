import native from 'libself_native.so';

export interface ReconstructionCapability {
  libraryLoaded:boolean; api26Symbols:boolean; status:number; available:boolean;
  nativeSessionImplemented:boolean; captureIntegrated:boolean; gsAcceptanceVerified:boolean;
  pipelineImplemented:boolean; qualityPolicy:string; message:string;
}
export interface ReconstructionProgress {
  jobId:string; state:string; sdkStage:number; progress:number; frames:number;
  retainedRgbBytes:number; width:number; height:number; error:string; modelPath:string;
  acceptedForPortrait:boolean; qualityReduced:boolean;
}
export interface CalibratedReconstructionFrame {
  width:number; height:number; focalX:number; focalY:number; principalX:number; principalY:number;
  distortion:number[]; position:number[]; rotation:number[]; timestampNs:string;
  tracking:boolean; poseSource:string;
}
interface ReconCommand {
  op:string; jobId?:string; root?:string; memoryBudgetBytes?:number; value?:boolean;
  width?:number; height?:number; focalX?:number; focalY?:number; principalX?:number; principalY?:number;
  distortion?:number[]; position?:number[]; rotation?:number[]; timestampNs?:string;
  tracking?:boolean; poseSource?:string;
}
/** Task adapter only. Saved output is deliberately not an accepted portrait.
 * AR ownership, genuine capture data and GS acceptance must precede product activation. */
export class ReconstructionClient {
  private jobId:string='';
  private pending:boolean=false;
  async probe():Promise<ReconstructionCapability> {
    return JSON.parse((await native.reconstruct('{"op":"probe"}')).json) as ReconstructionCapability;
  }
  private async request(command:ReconCommand, rgb?:ArrayBuffer):Promise<ReconstructionProgress> {
    if(this.pending)throw new Error('重建任务正在处理上一项操作');
    this.pending=true;
    try{
      const result=rgb===undefined?await native.reconstruct(JSON.stringify(command)):await native.reconstruct(JSON.stringify(command),rgb);
      return JSON.parse(result.json) as ReconstructionProgress;
    }
    finally{this.pending=false;}
  }
  async create(root:string,jobId:string,memoryBudgetBytes:number):Promise<ReconstructionProgress> {
    if(this.jobId)throw new Error('请先结束当前重建任务');
    // Retain the ID even if SDK creation fails so explicit close can release partial resources.
    this.jobId=jobId;
    return this.request({op:'create',root,jobId,memoryBudgetBytes});
  }
  async push(frame:CalibratedReconstructionFrame,rgb:ArrayBuffer):Promise<ReconstructionProgress> {
    return this.request({op:'push',jobId:this.jobId,width:frame.width,height:frame.height,
      focalX:frame.focalX,focalY:frame.focalY,principalX:frame.principalX,principalY:frame.principalY,
      distortion:frame.distortion,position:frame.position,rotation:frame.rotation,
      timestampNs:frame.timestampNs,tracking:frame.tracking,poseSource:frame.poseSource},rgb);
  }
  async start():Promise<ReconstructionProgress>{return this.request({op:'start',jobId:this.jobId});}
  async status():Promise<ReconstructionProgress>{return this.request({op:'status',jobId:this.jobId});}
  async save():Promise<ReconstructionProgress>{return this.request({op:'save',jobId:this.jobId});}
  async pause():Promise<ReconstructionProgress>{return this.request({op:'pause',jobId:this.jobId});}
  async resume():Promise<ReconstructionProgress>{return this.request({op:'resume',jobId:this.jobId});}
  async foreground(value:boolean):Promise<ReconstructionProgress>{return this.request({op:'foreground',jobId:this.jobId,value});}
  async close():Promise<void>{await this.request({op:'close',jobId:this.jobId});this.jobId='';}
}
