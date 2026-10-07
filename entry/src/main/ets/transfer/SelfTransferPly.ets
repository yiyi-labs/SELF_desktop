import { fileIo as fs } from '@kit.CoreFileKit';
import { PlyInfo, PackageValidationError } from './SelfTransferContract';
import { readAt, ascii } from './TransferFiles';

/** Audited common PlayCanvas contract. No conversion, reordering, quantization or write occurs here. */
export async function inspectPly(path:string,cancelled:()=>boolean=()=>false):Promise<PlyInfo>{
  const file=fs.openSync(path,fs.OpenMode.READ_ONLY);
  try{
    const size=fs.statSync(file.fd).size,head=new Uint8Array(await readAt(file.fd,0,Math.min(size,65536)));
    const marker=[101,110,100,95,104,101,97,100,101,114,10];let headerBytes=0;
    for(let i=0;i<=head.length-marker.length;i++){
      if(marker.every((value:number,j:number)=>head[i+j]===value)){headerBytes=i+marker.length;break;}
    }
    if(!headerBytes)throw new PackageValidationError('PLY 头部不完整或不受支持');
    const lines=ascii(head.buffer.slice(0,headerBytes)).trim().split('\n');
    if(lines[0]!=='ply'||lines[1]!=='format binary_little_endian 1.0')throw new PackageValidationError('当前 SELF 仅支持二进制小端 3DGS PLY');
    let vertexCount=0;const properties:string[]=[];
    for(let i=2;i<lines.length;i++){
      const parts=lines[i].split(' ');
      if(parts[0]==='element'){
        if(parts[1]!=='vertex'||vertexCount!==0)throw new PackageValidationError('PLY 元素契约不支持');vertexCount=Number(parts[2]);
      }else if(parts[0]==='property'){
        if(!vertexCount||parts.length!==3||parts[1]!=='float'||!/^\w+$/.test(parts[2])||properties.includes(parts[2]))throw new PackageValidationError('PLY 属性契约不支持');
        properties.push(parts[2]);
      }else if(parts[0]!=='comment'&&parts[0]!=='obj_info'&&parts[0]!=='end_header')throw new PackageValidationError('PLY 头部内容不受支持');
    }
    const required=['x','y','z','f_dc_0','f_dc_1','f_dc_2','opacity','scale_0','scale_1','scale_2','rot_0','rot_1','rot_2','rot_3'];
    if(required.some((name:string)=>!properties.includes(name)))throw new PackageValidationError('模型缺少必要的 Gaussian 属性');
    const rest=properties.filter((name:string)=>name.startsWith('f_rest_')).length;
    if(![0,9,24,45].includes(rest))throw new PackageValidationError('模型的球谐属性不受支持');
    for(let i=0;i<rest;i++)if(!properties.includes('f_rest_'+i))throw new PackageValidationError('模型的球谐属性不完整');
    const stride=properties.length*4;
    if(!Number.isSafeInteger(vertexCount)||vertexCount<=0||stride<=0||stride>65536||size!==headerBytes+vertexCount*stride)
      throw new PackageValidationError('模型文件长度与 PLY 头部不一致');
    const offsets=['x','y','z'].map((name:string)=>properties.indexOf(name)*4);
    const rotation=['rot_0','rot_1','rot_2','rot_3'].map((name:string)=>properties.indexOf(name)*4);
    const min=[Infinity,Infinity,Infinity],max=[-Infinity,-Infinity,-Infinity];
    const rowsPerRead=Math.max(1,Math.floor(262144/stride));
    for(let vertex=0;vertex<vertexCount;){
      if(cancelled())throw new PackageValidationError('模型交接已取消');
      const rows=Math.min(rowsPerRead,vertexCount-vertex),data=new DataView(await readAt(file.fd,headerBytes+vertex*stride,rows*stride));
      for(let row=0;row<rows;row++){
        const start=row*stride;
        for(let p=0;p<properties.length;p++)if(!Number.isFinite(data.getFloat32(start+p*4,true)))throw new PackageValidationError('模型包含损坏的 Gaussian 数值');
        if(rotation.every((offset:number)=>data.getFloat32(start+offset,true)===0))throw new PackageValidationError('模型旋转属性损坏');
        for(let axis=0;axis<3;axis++){const value=data.getFloat32(start+offsets[axis],true);min[axis]=Math.min(min[axis],value);max[axis]=Math.max(max[axis],value);}
      }
      vertex+=rows;
    }
    return {vertexCount,headerBytes,stride,properties,min,max};
  }finally{fs.closeSync(file);}
}
