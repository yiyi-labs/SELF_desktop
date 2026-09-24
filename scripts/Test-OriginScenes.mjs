/** Asset-level audit for the five corresponding 3D particle scenes. */
import fs from 'node:fs';
import crypto from 'node:crypto';

const names=['walker','window','bridge','horizon','threshold'];
const expectedPoints=4200,expectedFrames=20,stride=6;
const results=[];
for(const name of names){
  const filename=`entry/src/main/resources/rawfile/origin-${name}.bin`;
  const bytes=fs.readFileSync(filename);
  if(bytes.toString('ascii',0,4)!=='SHUM'||bytes.readUInt16LE(4)!==1||
     bytes.readUInt16LE(6)!==expectedFrames||bytes.readUInt16LE(8)!==expectedPoints||
     bytes.readUInt16LE(10)!==stride||bytes.length!==16+expectedFrames*expectedPoints*stride){
    throw Error(`${name}: invalid scene header or length`);
  }
  const personPoints=name==='walker'?4200:name==='window'?2300:2100;
  let centerX=0,centerY=0;
  for(let i=0;i<personPoints;i++){
    const first=16+i*stride;
    centerX+=bytes.readInt16LE(first)/32767/personPoints;
    centerY+=bytes.readInt16LE(first+2)/32767/personPoints;
  }
  const steps=[];
  for(let frame=0;frame<expectedFrames;frame++){
    let squared=0;
    for(let i=0;i<personPoints;i++){
      const current=16+(frame*expectedPoints+i)*stride;
      const next=16+((((frame+1)%expectedFrames)*expectedPoints)+i)*stride;
      for(let axis=0;axis<3;axis++){
        const difference=(bytes.readInt16LE(current+axis*2)-bytes.readInt16LE(next+axis*2))/32767;
        squared+=difference*difference/personPoints;
      }
    }
    steps.push(Math.sqrt(squared));
  }
  const seamRms=steps[expectedFrames-1];
  const peakRms=Math.max(...steps.slice(0,-1)),minRms=Math.min(...steps);
  if(!Number.isFinite(seamRms)||seamRms>.04||seamRms>peakRms*1.25)
    throw Error(`${name}: animation loop jumps (${seamRms})`);
  if((name==='walker'||name==='bridge')&&(minRms<.01||peakRms/minRms>3.2))
    throw Error(`${name}: walk motion pauses at a baked frame (${minRms})`);
  let seamVelocityMismatchRms=0;
  if(name==='walker'||name==='bridge'){
    let squared=0;
    for(let i=0;i<personPoints;i++){
      const first=16+i*stride,last=16+((expectedFrames-1)*expectedPoints+i)*stride;
      const previous=16+((expectedFrames-2)*expectedPoints+i)*stride;
      for(let axis=0;axis<3;axis++){
        const before=bytes.readInt16LE(last+axis*2)-bytes.readInt16LE(previous+axis*2);
        const after=bytes.readInt16LE(first+axis*2)-bytes.readInt16LE(last+axis*2);
        squared+=(before-after)*(before-after)/personPoints;
      }
    }
    seamVelocityMismatchRms=Math.sqrt(squared)/32767;
    if(seamVelocityMismatchRms>.0001)
      throw Error(`${name}: walk velocity changes at the loop seam (${seamVelocityMismatchRms})`);
  }
  results.push({scene:name,bytes:bytes.length,points:expectedPoints,frames:expectedFrames,
    personPoints,loopSeamRms:Number(seamRms.toFixed(5)),
    minFrameStepRms:Number(minRms.toFixed(5)),maxFrameStepRms:Number(peakRms.toFixed(5)),
    seamVelocityMismatchRms:Number(seamVelocityMismatchRms.toFixed(6)),
    personCenter:[Number(centerX.toFixed(4)),Number(centerY.toFixed(4))],
    sha256:crypto.createHash('sha256').update(bytes).digest('hex')});
}
console.log(JSON.stringify({passed:true,totalBytes:results.reduce((sum,item)=>sum+item.bytes,0),results},null,2));
