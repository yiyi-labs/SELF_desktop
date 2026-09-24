import { http } from '@kit.NetworkKit';
import { fileIo as fs } from '@kit.CoreFileKit';
import { cryptoFramework } from '@kit.CryptoArchitectureKit';

export interface ReconstructionTransportHealth {
  status:string;
  protocol:number;
  chunkBytes:number;
  maxCaptureBytes:number;
  engine:string;
}
export interface ReconstructionJobStatus {jobId:string;state:string;progress:number;message:string;assets:Record<string,ReconstructionAssetManifest>;}
export interface ReconstructionAssetManifest {file:string;bytes:number;sha256:string;}
interface CreatedJob {jobId:string;chunkBytes:number;state:string;}
interface ChunkReceipt {index:number;sha256:string;received:number;total:number;}
interface CaptureManifest {bytes:number;sha256:string;}
interface SealedJob {state:string;sha256:string;}

/** Portable private reconstruction endpoint. USB HDC and a future HTTPS service share this contract. */
export class ReconstructionTransportClient {
  endpoint:string='http://127.0.0.1:8787';
  token:string='';
  private url(path:string):string {
    const base=this.endpoint.trim().replace(/\/$/,'');
    if(base!=='http://127.0.0.1:8787'&&!base.startsWith('https://'))throw new Error('请在设置中连接安全的建模服务');
    return base+'/v1/reconstruction'+path;
  }
  private headers(binary:boolean=false):Record<string,string>{
    const values:Record<string,string>={'Content-Type':binary?'application/octet-stream':'application/json'};
    if(this.token)values['Authorization']='Bearer '+this.token;
    return values;
  }
  async probe():Promise<ReconstructionTransportHealth>{
    const request=http.createHttp();
    try{
      const response=await request.request(this.url('/health'),{method:http.RequestMethod.GET,header:this.headers(),expectDataType:http.HttpDataType.STRING,connectTimeout:5000,readTimeout:8000,usingCache:false});
      if(response.responseCode!==200)throw new Error('建模服务暂时不可用（'+response.responseCode+'）');
      const health=JSON.parse(response.result as string) as ReconstructionTransportHealth;
      if(health.protocol!==1||health.chunkBytes!==1048576||health.status!=='ready')throw new Error('建模服务版本不匹配');
      return health;
    }finally{request.destroy();}
  }
  /** Actual device-to-service binary path check; never treated as a portrait result. */
  async echo():Promise<boolean>{
    const sent=new Uint8Array(65539);
    for(let i=0;i<sent.length;i++)sent[i]=(i*131+17)%256;
    const request=http.createHttp();
    try{
      const response=await request.request(this.url('/echo'),{method:http.RequestMethod.POST,header:this.headers(true),extraData:sent.buffer as ArrayBuffer,expectDataType:http.HttpDataType.ARRAY_BUFFER,connectTimeout:5000,readTimeout:10000,usingCache:false});
      if(response.responseCode!==200)return false;
      const received=new Uint8Array(response.result as ArrayBuffer);
      return received.length===sent.length&&received.every((value:number,index:number)=>value===sent[index]);
    }finally{request.destroy();}
  }
  private async sha256(bytes:ArrayBuffer):Promise<string>{
    const md=cryptoFramework.createMd('SHA256');
    await md.update({data:new Uint8Array(bytes)});
    return this.hex((await md.digest()).data);
  }
  private hex(bytes:Uint8Array):string{
    let value='';for(let i=0;i<bytes.length;i++)value+=bytes[i].toString(16).padStart(2,'0');return value;
  }
  private async fileDigest(path:string):Promise<CaptureManifest>{
    const file=fs.openSync(path,fs.OpenMode.READ_ONLY);
    try{
      const size=fs.statSync(file.fd).size;
      if(size<1024||size>256*1024*1024)throw new Error('拍摄文件不完整或过大');
      const md=cryptoFramework.createMd('SHA256');let remaining=size;
      while(remaining>0){const data=new ArrayBuffer(Math.min(1048576,remaining));const read=fs.readSync(file.fd,data,{length:data.byteLength});if(read<=0)throw new Error('无法完整读取拍摄文件');await md.update({data:new Uint8Array(read===data.byteLength?data:data.slice(0,read))});remaining-=read;}
      return {bytes:size,sha256:this.hex((await md.digest()).data)};
    }finally{fs.closeSync(file);}
  }
  private async json(path:string,method:http.RequestMethod,body:string=''):Promise<string>{
    const request=http.createHttp();
    try{
      const response=await request.request(this.url(path),{method,header:this.headers(),extraData:body,expectDataType:http.HttpDataType.STRING,connectTimeout:10000,readTimeout:30000,usingCache:false});
      if(response.responseCode<200||response.responseCode>=300)throw new Error('建模服务暂时无法处理（'+response.responseCode+'）');
      return response.result as string;
    }finally{request.destroy();}
  }
  async uploadCapture(path:string,onProgress:(value:number)=>void=()=>{}):Promise<string>{
    const manifest=await this.fileDigest(path);
    const created=JSON.parse(await this.json('/jobs',http.RequestMethod.POST,JSON.stringify({totalBytes:manifest.bytes,sha256:manifest.sha256,format:'mp4'}))) as CreatedJob;
    if(!/^[a-f0-9]{32}$/.test(created.jobId)||created.chunkBytes!==1048576)throw new Error('建模任务回复无效');
    const file=fs.openSync(path,fs.OpenMode.READ_ONLY);
    try{
      const count=Math.ceil(manifest.bytes/created.chunkBytes);let remaining=manifest.bytes;
      for(let index=0;index<count;index++){
        const buffer=new ArrayBuffer(Math.min(created.chunkBytes,remaining));
        const read=fs.readSync(file.fd,buffer,{length:buffer.byteLength});
        if(read!==buffer.byteLength)throw new Error('拍摄数据读取不完整');
        const digest=await this.sha256(buffer),request=http.createHttp();
        try{
          const headers=this.headers(true);headers['X-Content-SHA256']=digest;
          const response=await request.request(this.url('/jobs/'+created.jobId+'/chunks/'+index),{method:http.RequestMethod.PUT,header:headers,extraData:buffer,expectDataType:http.HttpDataType.STRING,connectTimeout:10000,readTimeout:45000,usingCache:false});
          if(response.responseCode!==200)throw new Error('拍摄数据传输中断（'+response.responseCode+'）');
          const receipt=JSON.parse(response.result as string) as ChunkReceipt;
          if(receipt.index!==index||receipt.sha256!==digest)throw new Error('拍摄数据校验失败');
        }finally{request.destroy();}
        remaining-=read;onProgress((index+1)/count);
      }
    }finally{fs.closeSync(file);}
    const sealed=JSON.parse(await this.json('/jobs/'+created.jobId+'/seal',http.RequestMethod.POST,'{}')) as SealedJob;
    if(sealed.state!=='queued'||sealed.sha256!==manifest.sha256)throw new Error('建模任务校验失败');
    return created.jobId;
  }
  async status(jobId:string):Promise<ReconstructionJobStatus>{
    if(!/^[a-f0-9]{32}$/.test(jobId))throw new Error('建模任务编号无效');
    return JSON.parse(await this.json('/jobs/'+jobId,http.RequestMethod.GET)) as ReconstructionJobStatus;
  }
  /** Download only a completed, hash-matched GLB into app-private fixed storage. */
  async downloadMesh(jobId:string,filesDir:string):Promise<string>{
    if(!/^[a-f0-9]{32}$/.test(jobId))throw new Error('建模任务编号无效');
    const job=await this.status(jobId);
    const asset=job.assets?.mesh;
    if(job.state!=='complete'||!asset||!Number.isInteger(asset.bytes)||asset.bytes<1024||asset.bytes>32*1024*1024||
      !/^[a-f0-9]{64}$/.test(asset.sha256))throw new Error('个人模型尚未通过校验');
    const request=http.createHttp();
    let bytes:ArrayBuffer;
    try{
      const response=await request.request(this.url('/jobs/'+jobId+'/assets/mesh'),{method:http.RequestMethod.GET,
        header:this.headers(),expectDataType:http.HttpDataType.ARRAY_BUFFER,connectTimeout:10000,readTimeout:60000,usingCache:false});
      if(response.responseCode!==200)throw new Error('个人模型下载失败（'+response.responseCode+'）');
      bytes=response.result as ArrayBuffer;
    }finally{request.destroy();}
    const header=new DataView(bytes);
    if(bytes.byteLength!==asset.bytes||bytes.byteLength<12||header.getUint32(0,true)!==0x46546c67||
      header.getUint32(4,true)!==2||header.getUint32(8,true)!==bytes.byteLength||
      await this.sha256(bytes)!==asset.sha256)throw new Error('个人模型文件校验失败');
    const models=filesDir+'/models';if(!fs.accessSync(models))fs.mkdirSync(models);
    const directory=models+'/'+jobId;if(!fs.accessSync(directory))fs.mkdirSync(directory);
    const path=directory+'/portrait.glb',temporary=path+'.tmp';
    const file=fs.openSync(temporary,fs.OpenMode.CREATE|fs.OpenMode.READ_WRITE|fs.OpenMode.TRUNC);
    try{const written=fs.writeSync(file.fd,bytes);if(written!==bytes.byteLength)throw new Error('个人模型保存不完整');fs.fsyncSync(file.fd);}
    catch(e){fs.closeSync(file);if(fs.accessSync(temporary))fs.unlinkSync(temporary);throw new Error('个人模型保存失败');}
    fs.closeSync(file);fs.renameSync(temporary,path);
    return path;
  }
  /** Receive a Gaussian result in bounded USB chunks. This is not a GLB. */
  async downloadGaussian(jobId:string,filesDir:string,onProgress:(value:number)=>void=()=>{}):Promise<string>{
    if(!/^[a-f0-9]{32}$/.test(jobId))throw new Error('建模任务编号无效');
    const job=await this.status(jobId),asset=job.assets?.gaussian;
    if(job.state!=='gaussian_ready'||!asset||!Number.isInteger(asset.bytes)||asset.bytes<4096||asset.bytes>256*1024*1024||
      !/^[a-f0-9]{64}$/.test(asset.sha256))throw new Error('立体细节尚未通过校验');
    const models=filesDir+'/models';if(!fs.accessSync(models))fs.mkdirSync(models);
    const directory=models+'/'+jobId;if(!fs.accessSync(directory))fs.mkdirSync(directory);
    const path=directory+'/portrait.gaussian.ply',temporary=path+'.tmp';
    const file=fs.openSync(temporary,fs.OpenMode.CREATE|fs.OpenMode.READ_WRITE|fs.OpenMode.TRUNC);
    const digest=cryptoFramework.createMd('SHA256');let received=0;
    try{
      const count=Math.ceil(asset.bytes/1048576);
      for(let index=0;index<count;index++){
        const request=http.createHttp();let chunk:ArrayBuffer;
        try{
          const response=await request.request(this.url('/jobs/'+jobId+'/assets/gaussian/chunks/'+index),{
            method:http.RequestMethod.GET,header:this.headers(),expectDataType:http.HttpDataType.ARRAY_BUFFER,
            connectTimeout:10000,readTimeout:60000,usingCache:false});
          if(response.responseCode!==200)throw new Error('立体细节传输中断');
          chunk=response.result as ArrayBuffer;
        }finally{request.destroy();}
        const expected=Math.min(1048576,asset.bytes-received);
        if(chunk.byteLength!==expected)throw new Error('立体细节文件不完整');
        if(index===0){const header=new Uint8Array(chunk);if(header[0]!==112||header[1]!==108||header[2]!==121||header[3]!==10)throw new Error('立体细节格式不正确');}
        const written=fs.writeSync(file.fd,chunk);if(written!==chunk.byteLength)throw new Error('立体细节保存不完整');
        await digest.update({data:new Uint8Array(chunk)});received+=written;onProgress(received/asset.bytes);
      }
      if(received!==asset.bytes||this.hex((await digest.digest()).data)!==asset.sha256)throw new Error('立体细节校验失败');
      fs.fsyncSync(file.fd);
    }catch(e){fs.closeSync(file);if(fs.accessSync(temporary))fs.unlinkSync(temporary);throw new Error(String(e));}
    fs.closeSync(file);fs.renameSync(temporary,path);return path;
  }
}
