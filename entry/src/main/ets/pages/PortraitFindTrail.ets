export interface PortraitLight {
  x:number; y:number; speed:number; drift:number; age:number; life:number; length:number; radius:number; warm:boolean;
}

/** Quiet starlight confined to the portrait button; every trail drifts to the right. */
export class PortraitFindTrail {
  particles:PortraitLight[]=[];
  private fraction:number=0;
  private serial:number=0;
  private unit(seed:number):number{
    const value=Math.sin(seed*127.1+78.233)*43758.5453;
    return value-Math.floor(value);
  }
  burst(count:number,width:number,height:number):void{
    for(let i=0;i<count&&this.particles.length<36;i++){
      const seed=++this.serial;
      this.particles.push({x:18+this.unit(seed)*width*.28,y:height/2+(this.unit(seed+17)-.5)*18,
        speed:95+this.unit(seed+31)*80,drift:(this.unit(seed+49)-.5)*7,
        age:0,life:.62+this.unit(seed+67)*.55,length:5+this.unit(seed+83)*10,
        radius:.4+this.unit(seed+101)*.55,warm:seed%9===0});
    }
  }
  step(delta:number,held:boolean,width:number,height:number):void{
    const dt=Math.max(0,Math.min(delta,.05));
    for(const light of this.particles){light.age+=dt;light.x+=light.speed*dt;light.y+=light.drift*dt;}
    this.particles=this.particles.filter((light:PortraitLight)=>light.age<light.life&&light.x<width-14);
    if(held){
      this.fraction+=dt*30;
      const count=Math.floor(this.fraction);this.fraction-=count;
      this.burst(count,width,height);
    }else this.fraction=0;
  }
  clear():void{this.particles=[];this.fraction=0;}
}
