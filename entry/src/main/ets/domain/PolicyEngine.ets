import { CandidatePlan, RegionRecord, EditOperation } from './EditPlan';
export class PolicyEngine {
  static colors(preset: string): number[] {
    if(preset === 'rose') { return [0.66,0.12,0.30]; }
    if(preset === 'terracotta') { return [0.65,0.25,0.18]; }
    throw new Error('没有登记这个数字预设');
  }
  static validate(plan: CandidatePlan, assetId: string, version: string, revision: number, regions: RegionRecord[], sourceKind: string): void {
    if(plan.assetId!==assetId || plan.assetVersion!==version || plan.baseRevision!==revision) { throw new Error('方案已过期，请重新提出'); }
    if(plan.kind!=='lipTint' && plan.kind!=='localTint') { throw new Error('该操作未实现'); }
    if(!Number.isFinite(plan.strength) || plan.strength<0 || plan.strength>0.65) { throw new Error('强度超出支持范围'); }
    PolicyEngine.colors(plan.presetId);
    const region=regions.find((r:RegionRecord)=>r.regionId===plan.regionId);
    if(!region || region.assetId!==assetId || region.assetVersion!==version || region.width<=0 || region.height<=0) { throw new Error('区域与当前面容不匹配'); }
    if(plan.kind==='lipTint' && region.semantic!=='confirmed-lips') { throw new Error('尚未确认唇区，请先精细圈选并确认边界'); }
  }
  static authorizedOperation(plan: CandidatePlan, authorizationId: string): EditOperation {
    if(!authorizationId) { throw new Error('缺少本次授权'); }
    const operation: EditOperation={operationId:plan.planId,kind:plan.kind,regionId:plan.regionId,presetId:plan.presetId,color:PolicyEngine.colors(plan.presetId),absoluteStrength:plan.strength,authorizationId};
    operation.plannerSource=plan.plannerSource||'本地操作';operation.snapshotId=plan.snapshotId;
    return operation;
  }
  static productSimulationAllowed(calibrationProfile: string, allowedViews: string[]): boolean {
    return calibrationProfile.length>0 && allowedViews.includes('calibrated-simulation');
  }
}
