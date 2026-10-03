// Presentation coordinates only. Saved reconstruction coordinates are never changed.
export const clamp=(value,min,max)=>Math.max(min,Math.min(max,value));
export const smooth=value=>{const t=clamp(value,0,1);return t*t*(3-2*t);};
export const unit=seed=>{const n=Math.sin(seed*127.1+78.233)*43758.5453;return n-Math.floor(n);};
export const aspectScale=aspect=>clamp(aspect,.48,2.4);
export function position(index,aspect){
  const a=aspectScale(aspect);
  // Restrained offsets around an ascending depth axis; they do not steer the camera.
  const bend=Math.sin(index*1.67),drift=Math.sin(index*.57);
  return {x:(index*2.5+bend*.48+drift*.16)*a,
    y:index*3.45-bend*.32+drift*.18,z:-index*8.8-Math.sin(index*.91)*.55};
}
export function cameraPosition(index,aspect){
  // Travel along the calm spine. Following each star's lateral offset causes a visible slalom.
  return {x:(index*2.5+2.4)*aspectScale(aspect),y:index*3.45+1.65,z:-index*8.8+12};
}
// Labels compete for a limited screen area, with the selected memory placed first.
export function placeLabels(candidates,width,height,obstacles=[]){
  const accepted=[];
  for(const entry of [...candidates].sort((a,b)=>Number(b.selected)-Number(a.selected)||a.depth-b.depth)){
    if(accepted.length>=5)break;
    const w=Math.min(entry.width,width*.46),h=entry.selected?46:34;
    const x=clamp(entry.x-w/2,18,width-w-18),y=entry.selected?Math.min(entry.y,height*.8-h):entry.y;
    if(y<height*.26||y+h>height*.81||entry.x<12||entry.x>width-12)continue;
    const box={...entry,x,y,width:w,height:h};
    if(!entry.selected&&obstacles.some(other=>other.id!==entry.id&&x<other.x+other.width+5&&x+w+5>other.x&&y<other.y+other.height+5&&y+h+5>other.y))continue;
    if(accepted.some(other=>x<other.x+other.width+16&&x+w+16>other.x&&y<other.y+other.height+14&&y+h+14>other.y))continue;
    accepted.push(box);
  }
  return accepted;
}
