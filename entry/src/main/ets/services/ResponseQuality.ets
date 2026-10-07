/**
 * Rejects conversational loops before a reply reaches the user — the phone-side
 * equivalent of response_quality.py. Normalisation keeps CJK characters (Python \w is
 * unicode-aware), and near-duplicates are caught by an LCS similarity ratio.
 */
export class ResponseQuality {
 static normalized(text:string):string{return text.toLowerCase().replace(/[\p{P}\p{S}\s_]+/gu,'');}
 private static sentences(text:string):string[]{
  return text.split(/[。！？.!?\n]/).map((s:string)=>ResponseQuality.normalized(s)).filter((s:string)=>s.length>=10);
 }
 private static lcsLength(a:string,b:string):number{
  if(!a.length||!b.length)return 0;
  let previous=new Array<number>(b.length+1).fill(0);
  let current=new Array<number>(b.length+1).fill(0);
  for(let i=1;i<=a.length;i++){
   for(let j=1;j<=b.length;j++){
    current[j]=a.charAt(i-1)===b.charAt(j-1)?previous[j-1]+1:Math.max(previous[j],current[j-1]);
   }
   const swap=previous;previous=current;current=swap;current.fill(0);
  }
  return previous[b.length];
 }
 static similar(a:string,b:string):boolean{
  if(!a.length||!b.length)return false;
  if(a===b)return true;
  const ratio=2*ResponseQuality.lcsLength(a,b)/(a.length+b.length);
  return ratio>=.84;
 }
 static repeats(text:string,previous:string[]):boolean{
  const value=ResponseQuality.normalized(text);
  if(!value)return false;
  const sentences=ResponseQuality.sentences(text);
  const unique=new Set<string>(sentences);
  if(sentences.length!==unique.size)return true;
  for(const old of previous){
   const other=ResponseQuality.normalized(old);
   if(!other)continue;
   if(value===other||ResponseQuality.similar(value,other))return true;
   if(value.length>=6&&other.includes(value))return true;
   const oldSentences=new Set<string>(ResponseQuality.sentences(old));
   if(sentences.length&&sentences.every((s:string)=>oldSentences.has(s)))return true;
  }
  return false;
 }
}
