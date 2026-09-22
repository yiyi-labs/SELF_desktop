export class AmbiencePreference {
  static fromText(text:string):string|undefined{
    if(/不开心|难过|低落|疲惫|有点累|想安静|想放松|平静/.test(text))return 'quiet';
    if(/我.*开心|我.*愉快|好心情|暖一点|暖阳/.test(text))return 'warm';
    if(/想专注|清透|清新一点/.test(text))return 'clear';
    return undefined;
  }
  static label(mode:string):string{return mode==='warm'?'暖阳':mode==='clear'?'清透':'微光';}
}
