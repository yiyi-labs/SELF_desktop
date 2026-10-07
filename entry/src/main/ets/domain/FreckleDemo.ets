export interface FreckleDemoLook {id:string;title:string;note:string;image:string;}

/** A local tablet presentation script, independent of the viewed asset and cloud AI. */
export class FreckleDemo {
  static question:string='这处雀斑让我无法见人了';
  static answer:string='听起来，这处雀斑让你很在意，连见人都变得有压力了。雀斑也可以是很有辨识度的小特点。要不要先看看保留它的几种样子？喜欢哪一种，都由你决定。';
  static looks():FreckleDemoLook[]{return [
    {id:'natural',title:'自然保留',note:'让小特点自在一点',image:'freckle-natural.png'},
    {id:'warm',title:'暖光气色',note:'添一点温暖的光色',image:'freckle-warm.png'},
    {id:'airy',title:'轻透玫瑰',note:'淡淡妆感，留住雀斑',image:'freckle-airy.png'}
  ];}
  static enabled(deviceType:string):boolean{return deviceType==='tablet';}
  static validLook(id:string):boolean{return ['natural','warm','airy'].includes(id);}
}
