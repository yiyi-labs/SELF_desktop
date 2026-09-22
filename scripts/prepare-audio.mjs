import fs from 'node:fs/promises';import {createHash} from 'node:crypto';
// Original, deterministic ambient composition. No downloaded recordings or product claims.
const rate=24000,seconds=32,frames=rate*seconds,out='entry/src/main/resources/rawfile/audio';await fs.mkdir(out,{recursive:true});
const records=[];
for(const [name,notes] of Object.entries({quiet:[48,55,62,64],warm:[53,60,64,69],clear:[50,57,64,67]})){
 const data=Buffer.alloc(frames*4),freq=m=>440*Math.pow(2,(m-69)/12);let peak=0,energy=0;
 for(let i=0;i<frames;i++){
  const t=i/rate,edge=Math.min(1,t/1.6,(seconds-t)/1.6),gain=Math.sin(Math.max(0,edge)*Math.PI/2)**2;
  let l=0,r=0;
  notes.forEach((n,j)=>{const f=freq(n),a=.027*(.72+.28*Math.sin(2*Math.PI*t/(17+j*3)+j));const tone=Math.sin(2*Math.PI*f*t)+.16*Math.sin(2*Math.PI*2*f*t);l+=a*tone*(.7+j*.07);r+=a*tone*(.91-j*.05);});
  const beat=t%4,note=notes[Math.floor(t/4)%notes.length]+12,envelope=(1-Math.exp(-beat*3))*Math.exp(-beat*.9)*.018;
  const bell=envelope*(Math.sin(2*Math.PI*freq(note)*t)+.12*Math.sin(2*Math.PI*freq(note)*2*t));l=(l+bell)*gain;r=(r+bell*.88)*gain;
  peak=Math.max(peak,Math.abs(l),Math.abs(r));energy+=(l*l+r*r)/2;data.writeInt16LE(Math.round(l*32767),i*4);data.writeInt16LE(Math.round(r*32767),i*4+2);
 }
 const header=Buffer.alloc(44);header.write('RIFF');header.writeUInt32LE(36+data.length,4);header.write('WAVEfmt ',8);header.writeUInt32LE(16,16);header.writeUInt16LE(1,20);header.writeUInt16LE(2,22);header.writeUInt32LE(rate,24);header.writeUInt32LE(rate*4,28);header.writeUInt16LE(4,32);header.writeUInt16LE(16,34);header.write('data',36);header.writeUInt32LE(data.length,40);
 const wav=Buffer.concat([header,data]);await fs.writeFile(`${out}/${name}.wav`,wav);records.push({file:`${name}.wav`,sampleRate:rate,channels:2,durationSeconds:seconds,peak,rms:Math.sqrt(energy/frames),sha256:createHash('sha256').update(wav).digest('hex')});
}
await fs.mkdir('assets/audio',{recursive:true});await fs.writeFile('assets/audio/manifest.json',JSON.stringify({origin:'Original procedural composition made for SELF; no third-party recordings',generator:'scripts/prepare-audio.mjs',purpose:'Optional ambient music, no therapeutic or efficacy claims',files:records},null,2));console.log('Prepared three original stereo ambient loops; default playback is off.');
