export interface GalaxyDustTile {
  x:number; y:number; delay:number; distance:number; drift:number;
  alpha:number; light:boolean; phase:number; curl:number; life:number;
  r:number; g:number; b:number;
}
export interface GalaxyDustFrame {x:number;y:number;scale:number;opacity:number;progress:number;}

/** The source pixels and their grains share one release schedule, rather than two layered effects. */
export class GalaxyDeleteDust {
  static readonly duration:number=1696;
  static readonly step:number=32;
  readonly left:number=24;
  readonly top:number=248;
  readonly width:number;
  readonly height:number;
  readonly bufferWidth:number;
  readonly bufferHeight:number;
  tiles:GalaxyDustTile[]=[];
  private cell:number=5;
  private columns:number;
  private rows:number;
  private pixels:Uint8Array;
  private pixelWidth:number;
  private pixelHeight:number;
  private bgra:boolean;
  private premultiplied:boolean;
  private base:Uint8ClampedArray=new Uint8ClampedArray(0);
  private heads:Int32Array=new Int32Array(0);
  private next:Int32Array=new Int32Array(0);
  private destinations:Int32Array=new Int32Array(0);
  private detached:Uint8Array=new Uint8Array(0);
  private positions:Int16Array=new Int16Array(0);
  private opacity:Uint8Array=new Uint8Array(0);
  private kernels:number[][]=[];
  private stride:number=0;
  private scale:number=1;
  constructor(width:number,height:number,pixels:Uint8Array=new Uint8Array(0),pixelWidth:number=0,pixelHeight:number=0,
    bgra:boolean=false,premultiplied:boolean=false){
    this.width=width;this.height=height;this.bufferWidth=Math.ceil(width+154);this.bufferHeight=Math.ceil(height+this.top+24);
    this.pixels=pixels;this.pixelWidth=pixelWidth;this.pixelHeight=pixelHeight;this.bgra=bgra;this.premultiplied=premultiplied;
    this.columns=Math.ceil(width/this.cell);this.rows=Math.ceil(height/this.cell);
    for(let y=0;y<this.rows;y++)for(let x=0;x<this.columns;x++){
      const seed=Math.sin(x*12.9898+y*78.233)*43758.5453,n=seed-Math.floor(seed);
      const seedY=Math.sin(x*39.346+y*11.135)*24634.6345,m=seedY-Math.floor(seedY);
      const ox=Math.min(width-.1,(x+.16+n*.68)*this.cell),oy=Math.min(height-.1,(y+.16+m*.68)*this.cell);
      const delay=Math.max(16,(.58*ox/width+.42*(1-oy/height))*670+
        (Math.sin(ox*.041)+Math.sin(oy*.069+ox*.013))*16+(n-.5)*42);
      this.tiles.push({x:ox,y:oy,delay,distance:36+n*62,drift:122+m*100,
        alpha:0,light:n>.89,phase:m*Math.PI*2,curl:9+n*13,life:780+m*170,r:0,g:0,b:0});
    }
  }
  frame(tile:GalaxyDustTile,elapsed:number):GalaxyDustFrame{
    const age=elapsed-tile.delay,t=Math.max(0,Math.min(1,age/tile.life));
    const travel=.68*t+.32*t*t,swirl=Math.sin(t*Math.PI)*tile.curl;
    return {x:tile.x+travel*tile.distance+Math.sin(t*4.6+tile.phase)*swirl,
      y:tile.y-travel*tile.drift+Math.cos(t*4.1+tile.phase)*swirl*.8,
      scale:1,opacity:age<0||t>=1?0:Math.pow(1-t,1.5),progress:t};
  }
  /** Called once. Assign actual source pixels to irregular nearest-seed fragments. */
  prepare(pixelWidth:number,pixelHeight:number):void{
    this.stride=pixelWidth;this.scale=pixelWidth/this.bufferWidth;
    this.base=new Uint8ClampedArray(pixelWidth*pixelHeight*4);
    this.heads=new Int32Array(this.tiles.length);this.heads.fill(-1);
    this.detached=new Uint8Array(this.tiles.length);
    const rw=Math.ceil(this.width*this.scale),rh=Math.ceil(this.height*this.scale);
    this.next=new Int32Array(rw*rh);this.destinations=new Int32Array(rw*rh);
    const counts=new Uint32Array(this.tiles.length),red=new Float64Array(this.tiles.length),
      green=new Float64Array(this.tiles.length),blue=new Float64Array(this.tiles.length);
    const ow=Math.ceil(this.width),oh=Math.ceil(this.height),owners=new Uint16Array(ow*oh);
    for(let y=0;y<oh;y++)for(let x=0;x<ow;x++){
      const cx=Math.floor(x/this.cell),cy=Math.floor(y/this.cell);let nearest=0,distance=Infinity;
      const minY=Math.max(0,cy-1),maxY=Math.min(this.rows-1,cy+1),minX=Math.max(0,cx-1),maxX=Math.min(this.columns-1,cx+1);
      for(let ny=minY;ny<=maxY;ny++)for(let nx=minX;nx<=maxX;nx++){
        const index=ny*this.columns+nx,tile=this.tiles[index],dx=x+.5-tile.x,dy=y+.5-tile.y,d=dx*dx+dy*dy;
        if(d<distance){distance=d;nearest=index;}
      }
      owners[y*ow+x]=nearest;
    }
    for(let y=0;y<rh;y++)for(let x=0;x<rw;x++){
      const vx=(x+.5)/this.scale,vy=(y+.5)/this.scale;
      const source=(Math.min(this.pixelHeight-1,Math.floor(vy/this.height*this.pixelHeight))*this.pixelWidth+
        Math.min(this.pixelWidth-1,Math.floor(vx/this.width*this.pixelWidth)))*4;
      const hasSource=this.pixels.length>0,a=hasSource?this.pixels[source+3]:255;
      if(a<8)continue;
      const correction=this.premultiplied?255/a:1;
      const r=hasSource?Math.min(255,this.pixels[source+(this.bgra?2:0)]*correction):64,
        g=hasSource?Math.min(255,this.pixels[source+1]*correction):79,
        b=hasSource?Math.min(255,this.pixels[source+(this.bgra?0:2)]*correction):112;
      const nearest=owners[Math.min(oh-1,Math.floor(vy))*ow+Math.min(ow-1,Math.floor(vx))];
      const pixel=y*rw+x,at=((y+Math.round(this.top*this.scale))*pixelWidth+x+Math.round(this.left*this.scale))*4;
      this.next[pixel]=this.heads[nearest];this.heads[nearest]=pixel;this.destinations[pixel]=at;
      // ArkUI putImageData consumes premultiplied RGBA, unlike browser Canvas image data.
      this.base[at]=r*a/255;this.base[at+1]=g*a/255;this.base[at+2]=b*a/255;this.base[at+3]=a;
      counts[nearest]++;red[nearest]+=r;green[nearest]+=g;blue[nearest]+=b;
    }
    for(let i=0;i<this.tiles.length;i++){
      const tile=this.tiles[i],count=counts[i];
      if(count){tile.alpha=.86;tile.r=red[i]/count;tile.g=green[i]/count;tile.b=blue[i]/count;}
    }
    // Cache once: animation frames perform no trigonometry or object allocation.
    const frames=Math.ceil(GalaxyDeleteDust.duration/GalaxyDeleteDust.step)+1,count=this.tiles.length;
    this.positions=new Int16Array(frames*count*2);this.opacity=new Uint8Array(frames*count);
    const samples=256,sinA=new Float32Array(samples+1),cosA=new Float32Array(samples+1),
      sinB=new Float32Array(samples+1),cosB=new Float32Array(samples+1),swirl=new Float32Array(samples+1),
      travel=new Float32Array(samples+1),fade=new Float32Array(samples+1);
    for(let i=0;i<=samples;i++){
      const t=i/samples;sinA[i]=Math.sin(t*4.6);cosA[i]=Math.cos(t*4.6);sinB[i]=Math.sin(t*4.1);cosB[i]=Math.cos(t*4.1);
      swirl[i]=Math.sin(t*Math.PI);travel[i]=.68*t+.32*t*t;fade[i]=Math.pow(1-t,1.5);
    }
    for(let i=0;i<count;i++){
      const tile=this.tiles[i],sinPhase=Math.sin(tile.phase),cosPhase=Math.cos(tile.phase);
      for(let frame=0;frame<frames;frame++){
        const age=frame*GalaxyDeleteDust.step-tile.delay,q=Math.max(0,Math.min(samples,Math.round(age/tile.life*samples))),at=frame*count+i;
        const x=tile.x+travel[q]*tile.distance+(sinA[q]*cosPhase+cosA[q]*sinPhase)*swirl[q]*tile.curl;
        const y=tile.y-travel[q]*tile.drift+(cosB[q]*cosPhase-sinB[q]*sinPhase)*swirl[q]*tile.curl*.8;
        this.positions[at*2]=Math.round((x+this.left)*this.scale*8);this.positions[at*2+1]=Math.round((y+this.top)*this.scale*8);
        this.opacity[at]=age<0?0:Math.round(fade[q]*tile.alpha*255);
      }
    }
    this.kernels=[];
    // Small sphere sprites include their own shading and edge coverage. Quarter-pixel variants
    // keep their movement smooth on the small raster without per-frame gradients or extra layers.
    for(let kind=0;kind<3;kind++)for(let y=0;y<4;y++)for(let x=0;x<4;x++)
      this.kernels.push(this.makeKernel(kind,x/4,y/4));
    this.pixels=new Uint8Array(0);
  }
  private makeKernel(kind:number,fractionX:number,fractionY:number):number[]{
    const radius=kind===0?1.05:kind===1?1.25:1.18,glow=kind===2;
    const result:number[]=[],extent=Math.ceil((glow?2.7:radius+.65)*this.scale);
    for(let y=-extent;y<=extent;y++)for(let x=-extent;x<=extent;x++){
      const dx=(x-fractionX)/this.scale,dy=(y-fractionY)/this.scale,d=Math.sqrt(dx*dx+dy*dy);
      const coverage=Math.max(0,Math.min(1,radius+.6-d));
      const nx=dx/radius,ny=dy/radius,nz=Math.sqrt(Math.max(0,1-nx*nx-ny*ny));
      const diffuse=.38+.62*Math.max(0,-nx*.36-ny*.48+nz*.8);
      const glint=Math.exp(-((dx+.3)*(dx+.3)+(dy+.4)*(dy+.4))/.2)*.12;
      const body=Math.min(1,coverage*(diffuse+glint));
      const halo=glow?Math.exp(-d*d/2.1)*.095:0;
      const weight=body+halo*(1-body);
      if(weight>.012)result.push(x,y,Math.round(weight*255));
    }
    return result;
  }
  /** One reusable raster, one Canvas upload. Released source pixels never return. */
  render(data:Uint8ClampedArray,elapsed:number):void{
    const count=this.tiles.length,frame=Math.min(Math.floor(elapsed/GalaxyDeleteDust.step),
      Math.ceil(GalaxyDeleteDust.duration/GalaxyDeleteDust.step)),offset=frame*count;
    const sampled=frame*GalaxyDeleteDust.step;
    for(let i=0;i<count;i++)if(!this.detached[i]&&sampled>=this.tiles[i].delay){
      for(let p=this.heads[i];p>=0;p=this.next[p]){
        const at=this.destinations[p];this.base[at]=0;this.base[at+1]=0;this.base[at+2]=0;this.base[at+3]=0;
      }
      this.detached[i]=1;
    }
    data.set(this.base);
    for(let i=0;i<count;i++){
      const alpha=this.opacity[offset+i];if(alpha<4)continue;
      const tile=this.tiles[i],at=(offset+i)*2,packedX=this.positions[at],packedY=this.positions[at+1],
        x=packedX>>3,y=packedY>>3,phase=((packedY&7)>>1)*4+((packedX&7)>>1),
        kind=tile.light?2:i%3===0?1:0,kernel=this.kernels[kind*16+phase];
      for(let k=0;k<kernel.length;k+=3){
        const px=x+kernel[k],py=y+kernel[k+1];
        if(px<0||px>=this.stride||py<0||py>=this.base.length/4/this.stride)continue;
        const dest=(py*this.stride+px)*4,a=alpha*kernel[k+2]>>8;if(a<2)continue;
        const keep=(255-a)/255;
        data[dest]=tile.r*a/255+data[dest]*keep;
        data[dest+1]=tile.g*a/255+data[dest+1]*keep;
        data[dest+2]=tile.b*a/255+data[dest+2]*keep;data[dest+3]=a+data[dest+3]*keep;
      }
    }
  }
  release():void{
    this.pixels=new Uint8Array(0);this.base=new Uint8ClampedArray(0);this.heads=new Int32Array(0);
    this.next=new Int32Array(0);this.destinations=new Int32Array(0);this.positions=new Int16Array(0);
    this.opacity=new Uint8Array(0);this.kernels=[];this.tiles=[];
  }
}
