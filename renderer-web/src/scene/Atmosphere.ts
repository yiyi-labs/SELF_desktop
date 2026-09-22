/** Decorative light is behind the face, never a skin shader or an export effect. */
export class Atmosphere {
  private root=document.getElementById('atmosphere')!;
  private enabled=true;
  private onVisibility=()=>this.updateMotion();
  private reduced=matchMedia('(prefers-reduced-motion: reduce)');
  private onReduced=()=>this.updateMotion();
  constructor(){
    for(let i=0;i<18;i++){
      const dot=document.createElement('i');dot.className='particle';
      dot.style.setProperty('--x',`${i%2?82+(i*7%15):4+(i*11%18)}%`);dot.style.setProperty('--y',`${8+(i*17%80)}%`);
      dot.style.setProperty('--delay',`${-i*1.7}s`);dot.style.setProperty('--duration',`${14+i%7*3}s`);dot.style.setProperty('--size',`${2+i%3}px`);this.root.appendChild(dot);
    }
    document.addEventListener('visibilitychange',this.onVisibility);this.reduced.addEventListener('change',this.onReduced);this.updateMotion();
  }
  set(motion:boolean,palette:string){this.enabled=motion;document.body.dataset.palette=['quiet','warm','clear'].includes(palette)?palette:'quiet';this.updateMotion();}
  private updateMotion(){document.body.classList.toggle('still',!this.enabled||document.hidden||this.reduced.matches);}
  pointer(x:number,y:number){this.root.style.setProperty('--pointer-x',`${Math.max(15,Math.min(85,x*100))}%`);this.root.style.setProperty('--pointer-y',`${Math.max(15,Math.min(85,y*100))}%`);}
  dispose(){document.removeEventListener('visibilitychange',this.onVisibility);this.reduced.removeEventListener('change',this.onReduced);this.root.replaceChildren();}
}
