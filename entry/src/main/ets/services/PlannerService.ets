export interface Intent { action: string; text: string; }
// Finite, local templates. This service only proposes actions and never edits or grants permission.
export class PlannerService {
  static plan(input: string): Intent {
    const text=input.trim();
    if(/自杀|自伤|不想活|伤害自己/.test(text))return {action:'urgentSupport',text:'听起来你正承受很大的痛苦。如果你可能马上伤害自己，请立即联系当地急救或前往急诊，并找一位可信任的人陪着你。SELF 无法处理紧急危机。'};
    if(text==='打开音乐'||text==='来点音乐')return {action:'musicOn',text:''};
    if(text==='关闭音乐'||text==='停止音乐')return {action:'musicOff',text:''};
    if(text==='看看现在的我'||text==='先看看'||text==='保留现在')return {action:'observe',text:''};
    if(text==='自然一点'||text==='试试唇色')return {action:'suggestLip',text:'先试轻一点的唇色，其他地方不动'};
    if(text==='试一下')return {action:'apply',text:''};
    if(text==='颜色淡一点'||text==='淡一点')return {action:'lighter',text:'把当前颜色调淡，其他地方不动'};
    if(text==='换一种颜色')return {action:'changeColor',text:'换一个通用数字颜色'};
    if(text==='取消')return {action:'cancel',text:'已取消候选建议'};
    if(text==='撤销')return {action:'undo',text:''};
    if(text==='这次保留这里'||text==='这里别动')return {action:'protect',text:'只在本次保护圈选范围'};
    if(text==='以后保留这里')return {action:'preference',text:'明确保存这处范围的长期偏好'};
    if(text==='看看产品资料'||text==='产品')return {action:'products',text:''};
    if(/不喜欢|难看|焦虑|困扰/.test(text))return {action:'supportOffer',text:'听起来这里让你有些困扰。可以先保留，也可以按你的意愿尝试改变。愿意聊聊吗？'};
    return {action:'clarify',text:'可以说“自然一点”，或先圈选，再试局部颜色。当前使用本地有限建议。'};
  }
}
