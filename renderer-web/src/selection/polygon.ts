export type Point = {x:number,y:number};
export function inside(p:Point, polygon:Point[]):boolean {
  let hit=false;
  for(let i=0,j=polygon.length-1;i<polygon.length;j=i++) {
    const a=polygon[i],b=polygon[j];
    if ((a.y>p.y)!==(b.y>p.y) && p.x < (b.x-a.x)*(p.y-a.y)/(b.y-a.y)+a.x) hit=!hit;
  }
  return hit;
}
function cross(a:Point,b:Point,c:Point):number{return (b.x-a.x)*(c.y-a.y)-(b.y-a.y)*(c.x-a.x);}
export function validatePolygon(points:Point[],w:number,h:number,closure=20):Point[] {
  if(points.length<4 || points.length>2048 || points.some(p=>!Number.isFinite(p.x)||!Number.isFinite(p.y)||p.x<0||p.x>w||p.y<0||p.y>h)) throw Error('请在画面内画一个闭合区域');
  if(Math.hypot(points[0].x-points.at(-1)!.x,points[0].y-points.at(-1)!.y)>closure) throw Error('请将圈线收回起点');
  const p=points.filter((v,i)=>i===0||Math.hypot(v.x-points[i-1].x,v.y-points[i-1].y)>.1);
  if(Math.hypot(p[0].x-p.at(-1)!.x,p[0].y-p.at(-1)!.y)<.1)p.pop();
  if(p.length<3)throw Error('圈选需要至少三个不同顶点');
  let area=0;
  for(let i=0;i<p.length;i++) {
    const a=p[i],b=p[(i+1)%p.length];area+=a.x*b.y-b.x*a.y;
    for(let j=i+2;j<p.length;j++) {
      if(i===0&&j===p.length-1)continue;
      const c=p[j],d=p[(j+1)%p.length];
      if(cross(a,b,c)*cross(a,b,d)<=0&&cross(c,d,a)*cross(c,d,b)<=0 && Math.max(Math.min(a.x,b.x),Math.min(c.x,d.x))<=Math.min(Math.max(a.x,b.x),Math.max(c.x,d.x)) && Math.max(Math.min(a.y,b.y),Math.min(c.y,d.y))<=Math.min(Math.max(a.y,b.y),Math.max(c.y,d.y))) throw Error('圈线不能自交或重叠');
    }
  }
  if(Math.abs(area)<32)throw Error('区域太小，请放大后重画');
  return p;
}
export function polygonMask(p:Point[],width:number,height:number):Uint8Array {
  const out=new Uint8Array(width*height);
  for(let y=0;y<height;y++)for(let x=0;x<width;x++)if(inside({x:x+.5,y:y+.5},p))out[y*width+x]=255;
  return out;
}
// Distance feathering only erodes inward. It can never authorize another pixel.
export function innerFeather(mask:Uint8Array,w:number,h:number,radius=3):Uint8Array {
  const distance=new Float32Array(mask.length);distance.fill(1e6);
  for(let y=0;y<h;y++)for(let x=0;x<w;x++) {
    const i=y*w+x;
    if(!mask[i]||x===0||y===0||x===w-1||y===h-1)distance[i]=0;
    else distance[i]=Math.min(distance[i],distance[i-1]+1,distance[i-w]+1);
  }
  for(let y=h-2;y>=0;y--)for(let x=w-2;x>=0;x--) {const i=y*w+x;distance[i]=Math.min(distance[i],distance[i+1]+1,distance[i+w]+1);}
  return Uint8Array.from(mask,(v,i)=>v?Math.round(255*Math.min(1,distance[i]/radius)):0);
}
