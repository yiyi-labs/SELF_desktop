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
  let seamSquared=0,centerX=0,centerY=0;
  for(let i=0;i<personPoints;i++){
    const first=16+i*stride,last=16+((expectedFrames-1)*expectedPoints+i)*stride;
    centerX+=bytes.readInt16LE(first)/32767/personPoints;
    centerY+=bytes.readInt16LE(first+2)/32767/personPoints;
    for(let axis=0;axis<3;axis++){
      const difference=(bytes.readInt16LE(last+axis*2)-bytes.readInt16LE(first+axis*2))/32767;
      seamSquared+=difference*difference/personPoints;
    }
  }
  const seamRms=Math.sqrt(seamSquared);
  if(!Number.isFinite(seamRms)||seamRms>.025)throw Error(`${name}: animation loop jumps (${seamRms})`);
  results.push({scene:name,bytes:bytes.length,points:expectedPoints,frames:expectedFrames,
    personPoints,loopSeamRms:Number(seamRms.toFixed(5)),
    personCenter:[Number(centerX.toFixed(4)),Number(centerY.toFixed(4))],
    sha256:crypto.createHash('sha256').update(bytes).digest('hex')});
}
console.log(JSON.stringify({passed:true,totalBytes:results.reduce((sum,item)=>sum+item.bytes,0),results},null,2));
