import {unit,clamp} from './universe-layout.js';

export const galaxyStyles=[
  {photo:0,hue:0,saturation:1.12,space:[9,18,37],light:[85,139,214]},
  {photo:1,hue:0,saturation:1.1,space:[18,12,34],light:[148,104,208]},
  {photo:0,hue:-30,saturation:1.06,space:[6,21,30],light:[68,158,173]},
  {photo:2,hue:-9,saturation:1.05,space:[22,15,27],light:[182,129,106]},
  {photo:1,hue:24,saturation:1.04,space:[22,11,31],light:[186,103,150]},
  {photo:0,hue:19,saturation:.9,space:[11,13,36],light:[107,124,200]}
];

const palettes=[['113,157,255','92,206,232','225,151,200'],['177,126,241','108,163,255','255,165,119'],
  ['79,174,214','132,157,255','245,166,187'],['214,128,179','136,131,240','255,194,141'],
  ['117,143,238','172,143,224','243,192,150'],['89,180,207','103,130,230','236,151,192']];
const surface=size=>{const c=document.createElement('canvas');c.width=c.height=size;return c;};
function glow(ctx,x,y,r,color,alpha){
  const g=ctx.createRadialGradient(x,y,0,x,y,r);
  g.addColorStop(0,`rgba(${color},${alpha})`);g.addColorStop(.25,`rgba(${color},${alpha*.54})`);
  g.addColorStop(1,`rgba(${color},0)`);ctx.fillStyle=g;ctx.fillRect(x-r,y-r,r*2,r*2);
}

// Cached, deterministic spiral dust, stellar knots and dark lanes. No per-frame noise generation.
export function galaxyTexture(seed,photograph,style=galaxyStyles[0]){
  const c=surface(768),ctx=c.getContext('2d'),colors=palettes[seed%palettes.length];
  if(photograph){
    ctx.translate(384,384);ctx.rotate((unit(seed+91)-.5)*.9);
    ctx.scale(seed%2===0?1:-1,.8+unit(seed+8)*.24);
    ctx.filter=`hue-rotate(${style.hue}deg) saturate(${style.saturation})`;
    ctx.drawImage(photograph,-352,-352,704,704);ctx.filter='none';
    ctx.globalCompositeOperation='destination-in';
    const edge=ctx.createRadialGradient(0,0,210,0,0,355);
    edge.addColorStop(0,'rgba(0,0,0,1)');edge.addColorStop(.62,'rgba(0,0,0,.8)');edge.addColorStop(1,'rgba(0,0,0,0)');
    ctx.fillStyle=edge;ctx.fillRect(-384,-384,768,768);
    ctx.globalCompositeOperation='destination-out';glow(ctx,0,0,66,'0,0,0',.65);
    return c;
  }
  ctx.translate(384,384);ctx.rotate(-.28+unit(seed+51)*.48);ctx.scale(1,.57+unit(seed+8)*.14);
  glow(ctx,0,0,350,colors[0],.1);
  ctx.globalCompositeOperation='screen';
  const arms=seed%3===0?3:2,spin=seed%2?1:-1;
  for(let i=0;i<1700;i++){
    const r=18+Math.pow(unit(i*9+seed*181),.7)*299;
    const arm=i%arms*Math.PI*2/arms;
    const angle=arm+spin*(r*.016)+(.5-unit(i*9+3+seed))*Math.pow(r/320,.35)*.85;
    const x=Math.cos(angle)*r,y=Math.sin(angle)*r;
    const fade=Math.pow(1-r/345,1.5);
    glow(ctx,x,y,9+unit(i*5+seed)*28,colors[i%11===0?2:i%3===0?1:0],fade*(.032+unit(i+31)*.065));
  }
  ctx.globalCompositeOperation='source-over';
  for(let i=0;i<650;i++){
    const r=40+unit(i*7+seed*23)*258;
    const a=i%arms*Math.PI*2/arms+spin*r*.016+.17+(unit(i+19)-.5)*.12;
    glow(ctx,Math.cos(a)*r,Math.sin(a)*r,8+unit(i+29)*13,'2,4,13',.035*(1-r/340));
  }
  ctx.globalCompositeOperation='screen';
  for(let i=0;i<6200;i++){
    const r=Math.pow(unit(i*11+seed*83),.67)*310;
    const a=i%arms*Math.PI*2/arms+spin*r*.016+(unit(i*11+5)-.5)*(i%5===0?5:.72);
    const x=Math.cos(a)*r,y=Math.sin(a)*r;
    const size=.25+unit(i*11+7)*.85;
    ctx.fillStyle=`rgba(${i%13===0?'255,211,176':i%3===0?'198,215,255':'144,174,228'},${(.15+unit(i+2)*.6)*Math.pow(1-r/340,.7)})`;
    ctx.fillRect(x,y,size,size);
    if(i%173===0)glow(ctx,x,y,3.2,'200,222,255',.5);
  }
  // A quiet centre keeps the real reconstruction legible, with warm starlight around it.
  glow(ctx,0,0,95,'252,198,145',.2);glow(ctx,0,0,43,'255,229,198',.14);
  ctx.globalCompositeOperation='destination-out';glow(ctx,0,0,65,'0,0,0',.48);
  return c;
}

export function planetTexture(){
  const c=surface(384),ctx=c.getContext('2d'),image=ctx.createImageData(384,384);
  for(let y=0;y<384;y++)for(let x=0;x<384;x++){
    const nx=(x-192)/174,ny=(y-192)/174,r2=nx*nx+ny*ny;if(r2>1)continue;
    const z=Math.sqrt(1-r2),light=Math.max(0,nx*-.66+ny*-.42+z*.32);
    const bands=Math.sin(ny*34+Math.sin(nx*8+z*11)*1.4)*.05+Math.sin(ny*79+nx*19)*.025;
    const grain=(unit(x*1.1+y*401)-.5)*.05;
    const limb=Math.pow(1-z,5)*Math.max(0,-nx*.7-ny*.45)*.46;
    const i=(y*384+x)*4;
    image.data[i]=clamp((.025+light*(.22+bands+grain)+limb*.35)*255,0,255);
    image.data[i+1]=clamp((.034+light*(.29+bands+grain)+limb*.59)*255,0,255);
    image.data[i+2]=clamp((.06+light*(.41+bands+grain)+limb)*255,0,255);
    image.data[i+3]=Math.round(clamp((1-r2)*160,0,1)*255);
  }
  ctx.putImageData(image,0,0);return c;
}

export function drawSpace(ctx,width,height,camera,clock,travel,motion,planet,theme){
  ctx.clearRect(0,0,width,height);
  const wash=ctx.createRadialGradient(width*.6,height*.38,0,width*.6,height*.38,width*.8);
  wash.addColorStop(0,`rgb(${theme.space.join(',')})`);wash.addColorStop(.58,'#060b19');wash.addColorStop(1,'#02040b');
  ctx.fillStyle=wash;ctx.fillRect(0,0,width,height);
  // A low-contrast, broad nebular veil drifts in parallax. Its colour is interpolated in world travel.
  ctx.save();ctx.translate(width*(.36+Math.sin(camera.z*.012)*.07),height*.45);
  ctx.rotate(-.52+Math.sin(camera.z*.008)*.06);ctx.scale(1,.38);
  glow(ctx,0,0,Math.max(width,height)*.6,theme.light.join(','),.045);ctx.restore();
  // Three distance shells create differential parallax during travel.
  for(let i=0;i<340;i++){
    const layer=1+i%3,z=layer*34;
    const x=((unit(i*7+1)*width-camera.x*width/z*.16)%width+width)%width;
    const y=((unit(i*7+2)*height+camera.y*height/z*.16)%height+height)%height;
    const alpha=(.13+unit(i*7+3)*.5)*(motion?.9+Math.sin(clock*.45+i)*.1:1);
    const radius=(.35+Math.pow(unit(i*7+4),6)*1.3)*(4-layer)/2.4;
    const starColor=i%11===0?theme.light.join(','):i%7===0?'245,205,172':'182,206,241';
    ctx.fillStyle=`rgba(${starColor},${alpha})`;
    ctx.beginPath();ctx.arc(x,y,radius,0,Math.PI*2);ctx.fill();
    if(radius>1.3)glow(ctx,x,y,5,'168,198,255',.13);
  }
  const size=Math.min(width,height)*.3;
  ctx.globalAlpha=.67*(1-travel*.7);
  ctx.drawImage(planet,width*.97-size/2-camera.x*.3,height*.73-size/2+camera.y*.3,size,size);
  ctx.globalAlpha=1;
  if(travel>0){
    // Slow, tapered starlight, with a dark centre instead of a white loading flash.
    const cx=width*.5,cy=height*.5;
    for(let i=0;i<105;i++){
      const a=unit(i*17+3)*Math.PI*2;
      const t=(unit(i*13+7)+(motion?clock*.13:0))%1;
      const r=(.09+t*t*.76)*Math.hypot(width,height);
      const length=(8+t*t*height*.09)*travel;
      const dx=Math.cos(a),dy=Math.sin(a);
      const g=ctx.createLinearGradient(cx+dx*r,cy+dy*r,cx+dx*(r+length),cy+dy*(r+length));
      g.addColorStop(0,'rgba(115,164,225,0)');g.addColorStop(1,`rgba(180,206,244,${travel*(1-t)*.43})`);
      ctx.strokeStyle=g;ctx.lineWidth=.5+t*.65;ctx.beginPath();ctx.moveTo(cx+dx*r,cy+dy*r);ctx.lineTo(cx+dx*(r+length),cy+dy*(r+length));ctx.stroke();
    }
  }
}
