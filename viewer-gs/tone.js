/** Coarse background tone, sampled only around the upper-left title region. */
export function upperLeftLuma(pixels, width, height) {
  if (width < 4 || height < 4 || pixels.length !== width * height * 4) throw Error('Invalid tone sample');
  const samples=[];
  for(let y=1;y<Math.max(2,Math.floor(height*.42));y++){
    for(let x=1;x<Math.max(2,Math.floor(width*.48));x++){
      const i=(y*width+x)*4,a=pixels[i+3]/255;
      // Transparent GS background is dark night in the parent surface.
      const l=(.2126*pixels[i]+.7152*pixels[i+1]+.0722*pixels[i+2])/255*a;
      samples.push(l);
    }
  }
  samples.sort((a,b)=>a-b);
  return samples[Math.floor(samples.length*.5)];
}

export function createToneTracker() {
  let light=null, candidate=null, repeats=0;
  return luma=>{
    // Wide hysteresis and two consecutive readings avoid switching during
    // short rotations or a single bright splat crossing the title area.
    const next=light===true?(luma<.40?false:true):(luma>.68?true:false);
    if(next===light){candidate=null;repeats=0;return null;}
    if(candidate!==next){candidate=next;repeats=1;return null;}
    if(++repeats<2)return null;
    light=next;candidate=null;repeats=0;return light;
  };
}
