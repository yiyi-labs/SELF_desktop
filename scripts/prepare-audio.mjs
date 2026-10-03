import fs from 'node:fs/promises';import {createHash} from 'node:crypto';
// Original, deterministic ambient composition. No downloaded recordings or product claims.
// One seamless loop per interface of the journey: the mirror home keeps three atmosphere
// moods (quiet/warm/clear); capture, forming, sky, travel, personal and care each carry
// their own scene loop. A soft bell marks every four seconds so the particle field can
// breathe with the music. All loops crossfade their tail into their head, so AVPlayer
// loop=true never clicks.
const RATE=24000,TAU=Math.PI*2,OUT='entry/src/main/resources/rawfile/audio';
const f=m=>440*Math.pow(2,(m-69)/12);
function mulberry32(a){return()=>{a|=0;a=a+0x6D2B79F5|0;let t=Math.imul(a^a>>>15,1|a);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296;};}
const SINN=8192,SINT=new Float32Array(SINN+1);for(let i=0;i<=SINN;i++)SINT[i]=Math.sin(TAU*i/SINN);
function sini(x){const p=((x%TAU)+TAU)%TAU/TAU*SINN,i=p|0;return SINT[i]+(SINT[i+1]-SINT[i])*(p-i);}
function ctx(seconds,seed){const frames=Math.round(RATE*seconds),tail=Math.round(RATE*2.5);return{seconds,frames,tail,L:new Float32Array(frames+tail),R:new Float32Array(frames+tail),rng:mulberry32(seed)};}
const at=(c,t)=>Math.round(t*RATE);
const panLR=p=>[Math.cos((p+1)*Math.PI/4),Math.sin((p+1)*Math.PI/4)];
// Generic additive voice with attack + exponential decay (bells, plucks, e-piano, thumps).
function voice(c,midi,start,dur,o){
  const g=o.gain??.05,attack=o.attack??.005,decay=o.decay??.9,harm=o.harmonics??[[1,1],[2,.15]],pan=o.pan??0;
  const tremHz=o.tremHz??0,tremDepth=o.tremDepth??0,vibHz=o.vibHz??0,vibCents=o.vibCents??0;
  const i0=at(c,start),i1=Math.min(c.L.length,at(c,start+dur+1.5)),[pl,pr]=panLR(pan),fr=f(midi);
  for(let i=i0;i<i1;i++){
    const t=i/RATE,lt=t-start;if(lt<0)continue;
    const env=Math.min(1,lt/attack)*Math.exp(-Math.max(0,lt-attack)/decay);if(lt>attack&&env<1e-4)break;
    const vv=vibHz?fr*Math.pow(2,vibCents*Math.sin(TAU*vibHz*lt)/1200):fr;
    let s=0;for(const [h,a] of harm)s+=a*sini(TAU*vv*h*t);
    if(tremHz)s*=1-tremDepth*.5*(1+sini(TAU*tremHz*lt-Math.PI/2));
    s*=g*env;c.L[i]+=s*pl;c.R[i]+=s*pr;
  }
}
// Slow pad: detuned triangle-free sine pairs per note, per-note drift LFO, wide spread.
function pad(c,chord,start,dur,o){
  const g=o.gain??.02,attack=o.attack??1.4,release=o.release??1.8,det=o.detuneCents??4;
  const lfoHz=o.lfoHz??.07,lfoDepth=o.lfoDepth??.22,spread=o.spread??.6;
  chord.forEach((n,j)=>{
    const i0=at(c,start),i1=Math.min(c.L.length,at(c,start+dur+release+1)),base=f(n);
    const pan=chord.length>1?spread*((j/(chord.length-1))*2-1):0,[pl,pr]=panLR(pan);
    const d1=TAU*base*Math.pow(2,det/1200)/RATE,d2=TAU*base*Math.pow(2,-det/1200)/RATE;
    let p1=c.rng()*TAU,p2=c.rng()*TAU;
    for(let i=i0;i<i1;i++){
      const lt=i/RATE-start;
      const env=Math.min(1,Math.max(0,lt/attack),Math.max(0,(dur+release-lt)/release));
      p1+=d1;p2+=d2;
      const lfo=1+lfoDepth*.5*sini(TAU*lfoHz*lt+j*1.7);
      const s=(sini(p1)+sini(p2))*.5*g*env*lfo;
      c.L[i]+=s*pl;c.R[i]+=s*pr;
    }
  });
}
function bell(c,midi,start,o){voice(c,midi,start,o?.dur??2.6,{gain:o?.gain??.03,attack:.004,decay:o?.decay??1.0,harmonics:[[1,1],[2,.18],[3,.06]],pan:o?.pan??0});}
function pluck(c,midi,start,o){voice(c,midi,start,.5,{gain:o?.gain??.034,attack:.003,decay:o?.decay??.16,harmonics:[[1,1],[2,.22]],pan:o?.pan??0});}
function thump(c,midi,start,gain){voice(c,midi,start,.3,{gain:gain??.05,attack:.004,decay:.075,harmonics:[[1,1],[2,.3]]});}
function epiano(c,midi,start,pan){voice(c,midi,start,2.2,{gain:.042,attack:.004,decay:.8,harmonics:[[1,1],[2,.10],[3,.30]],tremHz:4.6,tremDepth:.16,pan});}
// Filtered noise riser for the star-travel scene; band follows an exponential sweep.
function whoosh(c,start,dur,o){
  const g=o.gain??.05,from=o.from??400,to=o.to??2800;
  const i0=at(c,start),i1=Math.min(c.L.length,at(c,start+dur));
  let fL=0,fR=0,sL=0,sR=0;
  for(let i=i0;i<i1;i++){
    const p=(i-i0)/(i1-i0),env=Math.pow(Math.sin(Math.PI*p),1.5);
    const hz=from*Math.pow(to/from,p),aF=1-Math.exp(-TAU*hz/RATE),aS=1-Math.exp(-TAU*hz*.35/RATE);
    const nL=c.rng()*2-1,nR=c.rng()*2-1;
    fL+=aF*(nL-fL);sL+=aS*(nL-sL);fR+=aF*(nR-fR);sR+=aS*(nR-sR);
    c.L[i]+=(fL-sL)*env*g;c.R[i]+=(fR-sR)*env*g;
  }
}
// Stereo feedback delay; echoes sit dark and wide behind the dry signal.
function echo(c,wet,fb){
  const dA=Math.round(.42*RATE),dB=Math.round(.57*RATE);
  const bL=new Float32Array(dA),bR=new Float32Array(dB);let iA=0,iB=0;
  for(let i=0;i<c.L.length;i++){
    const l=c.L[i],r=c.R[i],el=bL[iA],er=bR[iB];
    c.L[i]=l+el*wet;c.R[i]=r+er*wet;
    bL[iA]=(l+er*.35)*fb;bR[iB]=(r+el*.35)*fb;
    iA=(iA+1)%dA;iB=(iB+1)%dB;
  }
}
// Whole-loop lowpass; endpoints match when from===to so the loop seam stays invisible.
function lowpass(c,hzFrom,hzTo,cycle){
  let yl=0,yr=0;const n=c.L.length;
  for(let i=0;i<n;i++){
    const p=i/n,u=cycle?Math.pow(Math.sin(Math.PI*p),2):p;
    const hz=hzFrom+(hzTo-hzFrom)*u,a=1-Math.exp(-TAU*hz/RATE);
    yl+=a*(c.L[i]-yl);yr+=a*(c.R[i]-yr);c.L[i]=yl;c.R[i]=yr;
  }
}
// Fold the rendered tail into the head, normalize to the target peak, write PCM WAV.
async function finish(c,file,peakTarget){
  for(let i=0;i<c.tail;i++){const w=1-i/c.tail;c.L[i]+=c.L[c.frames+i]*w;c.R[i]+=c.R[c.frames+i]*w;}
  let peak=0,energy=0;
  for(let i=0;i<c.frames;i++){peak=Math.max(peak,Math.abs(c.L[i]),Math.abs(c.R[i]));energy+=(c.L[i]*c.L[i]+c.R[i]*c.R[i])/2;}
  const scale=peak>0?peakTarget/peak:1;
  const data=Buffer.alloc(c.frames*4);
  for(let i=0;i<c.frames;i++){data.writeInt16LE(Math.round(Math.max(-1,Math.min(1,c.L[i]*scale))*32767),i*4);data.writeInt16LE(Math.round(Math.max(-1,Math.min(1,c.R[i]*scale))*32767),i*4+2);}
  const header=Buffer.alloc(44);header.write('RIFF');header.writeUInt32LE(36+data.length,4);header.write('WAVEfmt ',8);header.writeUInt32LE(16,16);header.writeUInt16LE(1,20);header.writeUInt16LE(2,22);header.writeUInt32LE(RATE,24);header.writeUInt32LE(RATE*4,28);header.writeUInt16LE(4,32);header.writeUInt16LE(16,34);header.write('data',36);header.writeUInt32LE(data.length,40);
  const wav=Buffer.concat([header,data]);await fs.writeFile(`${OUT}/${file}`,wav);
  return{file,sampleRate:RATE,channels:2,durationSeconds:c.seconds,peak:peak*scale,rms:Math.sqrt(energy/c.frames)*scale,sha256:createHash('sha256').update(wav).digest('hex')};
}
// A soft bell every four seconds keeps the particle-field pulse anchored to the music.
function barBells(c,notes,gain,decay){const penta=notes;for(let b=0;b<c.seconds/4;b++){const n=penta[b%penta.length];bell(c,n,b*4,{gain,decay,pan:(b%2?-.25:.25)});}}
const records=[];
async function mood(name,chord,bellNotes,seed){
  const c=ctx(32,seed);pad(c,chord,0,32,{gain:.026,attack:2.4,release:3.2,detuneCents:5,lfoDepth:.3});
  barBells(c,bellNotes,.016,1.1);echo(c,.22,.32);
  records.push(await finish(c,name+'.wav',.096));
}
async function scene(name,seconds,compose,seed,peak,lp){
  const c=ctx(seconds,seed);compose(c);echo(c,...({capture:[.15,.25],forming:[.25,.35],sky:[.32,.42],travel:[.18,.22],personal:[.28,.36],care:[.22,.30]})[name]);
  if(lp)lowpass(c,...lp);
  records.push(await finish(c,`scene-${name}.wav`,peak));
}
await fs.mkdir(OUT,{recursive:true});
// Mirror-home atmosphere moods keep their original chord identities, now with air and echo.
await mood('quiet',[48,55,62,64],[72,76,79,81],11);
await mood('warm',[53,60,64,69],[77,81,84,88],22);
await mood('clear',[50,57,64,67],[74,78,81,86],33);
// capture — a calm, focused room: D dorian pads, a slow heartbeat, barely-there bells.
await scene('capture',32,c=>{
  const chords=[[50,57,60,64],[46,53,57,62],[50,57,60,64],[48,55,62,64]];
  chords.forEach((ch,b)=>pad(c,ch,b*8,8,{gain:.02,attack:1.8,release:2.6,lfoDepth:.18}));
  for(let t=0;t<32;t+=.8)thump(c,38,t,.028);
  for(let b=0;b<8;b++)bell(c,[74,77][b%2],b*4,{gain:.012,decay:1.2,pan:b%2?-.2:.2});
},44,.08);
// forming — starlight gathering: rising celesta arpeggios over Am-F-C-G hope, filter blooming.
await scene('forming',40,c=>{
  const chords=[[45,52,60,64],[41,53,57,60],[48,55,59,64],[43,55,59,64],[40,52,55,59],[41,53,57,60],[48,55,59,64],[43,55,59,64],[45,52,60,64],[45,52,59,64]];
  chords.forEach((ch,b)=>{pad(c,ch,b*4,4,{gain:.018,attack:1.1,release:1.6,lfoDepth:.2});
    const steps=[0,1,2,3,2,3,1,2];steps.forEach((si,k)=>{const tone=ch[si]+12+(k===7?12:0);pluck(c,tone,b*4+k*.5,{gain:.016+.007*(b/9),decay:.3,pan:(k%2?-.3:.3)});});});
  chords.forEach((ch,b)=>bell(c,ch[0]+24,b*4,{gain:.02,decay:1.3}));
},55,.11,[520,2600,true]);
// sky — the deep night: low drone, wide minor pads, sparse high bells like distant stars.
await scene('sky',48,c=>{
  pad(c,[36,43],0,48,{gain:.03,attack:4,release:5,detuneCents:3,lfoDepth:.12,spread:.3});
  const chords=[[48,55,58,62],[51,55,58,62],[44,60,63,67],[46,58,62,65],[53,56,60,63],[43,60,62,65]];
  chords.forEach((ch,b)=>pad(c,ch,b*8,8,{gain:.019,attack:2.6,release:3.4,detuneCents:6,lfoDepth:.28}));
  for(let b=0;b<12;b++)bell(c,chords[Math.floor(b/2)%6][0]+12,b*4,{gain:.010,decay:1.6});
  for(let k=0;k<14;k++){const n=[79,82,84,86,89,91][Math.floor(c.rng()*6)];bell(c,n,c.rng()*44+2,{gain:.008+c.rng()*.006,decay:2.6+c.rng()*1.2,pan:c.rng()*1.4-.7});}
},66,.12);
// travel — flying through the stars: driving sixteenth arpeggios, sub heartbeat, whoosh risers.
await scene('travel',32,c=>{
  const chords=[[40,47,52,55],[40,47,52,55],[48,52,55,60],[48,52,55,60],[43,47,50,55],[43,47,50,55],[38,45,50,54],[38,45,50,54]];
  chords.forEach((ch,b)=>{
    pad(c,ch,b*4,4,{gain:.014,attack:.5,release:1.1,lfoDepth:.14,lfoHz:.18});
    const pattern=[0,2,1,3,2,1,3,2,0,2,1,3,2,3,1,2];
    pattern.forEach((si,k)=>pluck(c,ch[si]+12,b*4+k*.25,{gain:.03,decay:.2,pan:(k%2?-.42:.42)}));
    for(let beat=0;beat<4;beat++)thump(c,ch[0]-12,b*4+beat,beat===0?.06:.038);
    bell(c,ch[0]+24,b*4,{gain:.026,decay:1.1,harmonics:undefined});
  });
  whoosh(c,0,2.0,{gain:.055,from:420,to:3000});whoosh(c,16,2.0,{gain:.055,from:420,to:3000});
  whoosh(c,8,1.6,{gain:.03,from:900,to:2200});whoosh(c,24,1.6,{gain:.03,from:900,to:2200});
},77,.14);
// personal — orbiting your own star: warm pads with close, trembling e-piano fragments.
await scene('personal',40,c=>{
  const chords=[[45,52,59,64],[41,48,57,64],[48,55,62,64],[43,50,55,64],[50,57,60,65],[41,48,57,64],[48,55,62,64],[43,50,55,64],[45,52,59,64],[45,52,60,67]];
  chords.forEach((ch,b)=>pad(c,ch,b*4,4,{gain:.02,attack:1.3,release:1.9,lfoDepth:.2}));
  const scale=[69,72,74,76,79,81];
  for(let b=0;b<10;b++){const count=2+Math.floor(c.rng()*2);for(let k=0;k<count;k++){const n=scale[Math.floor(c.rng()*scale.length)];epiano(c,n,b*4+.5+k*(1.1+c.rng()*.5),c.rng()*.8-.4);}}
  chords.forEach((ch,b)=>bell(c,[60,64,67][b%3]+12,b*4,{gain:.013,decay:1.4}));
},88,.10);
// care — being looked after: dark-warm major pads, everything rounded and safe.
await scene('care',36,c=>{
  const chords=[[41,48,53,60],[48,52,55,60],[50,53,57,60],[46,50,53,58],[41,48,53,60],[48,52,55,60],[50,53,57,60],[48,52,55,59],[41,48,53,60]];
  chords.forEach((ch,b)=>pad(c,ch,b*4,4,{gain:.022,attack:1.5,release:2.1,detuneCents:5,lfoDepth:.24}));
  for(let b=0;b<9;b++)bell(c,[65,69,72][b%3],b*4,{gain:.014,decay:1.5,pan:b%2?.2:-.2});
},99,.09,[1500,1500,false]);
await fs.mkdir('assets/audio',{recursive:true});
await fs.writeFile('assets/audio/manifest.json',JSON.stringify({
 origin:'Original procedural composition made for SELF; no third-party recordings',
 generator:'scripts/prepare-audio.mjs',
 purpose:'Optional ambient music, no therapeutic or efficacy claims',
 design:'One seamless loop per interface of the journey: mirror-home moods (quiet/warm/clear), capture, forming, sky, travel, personal, care. A soft bell marks every four seconds so the particle field can breathe with the music; every loop crossfades its tail into its head.',
 scenes:{origin:'quiet/warm/clear by atmosphere',capture:'scene-capture',forming:'scene-forming',sky:'scene-sky',travel:'scene-travel',personal:'scene-personal',care:'scene-care'},
 files:records},null,2));
console.log(`Prepared ${records.length} original stereo ambient loops (3 home moods + 6 scene loops); default playback is off.`);
