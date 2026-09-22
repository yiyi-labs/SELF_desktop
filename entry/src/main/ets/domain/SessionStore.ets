import { CandidatePlan, RegionRecord, EditOperation, Snapshot, Protection, SavedWorkspace, SceneView } from './EditPlan';
import { PolicyEngine } from './PolicyEngine';
export class SessionStore {
  assetId: string='sample-lee';
  assetVersion: string='lee-r186-self2';
  sourceKind: string='MESH';
  sourceFile: string='';
  width: number=1024;
  height: number=1024;
  revision: number=0;
  sceneRevision:number=0;
  regionVersion:number=0;
  viewRevision:number=0;
  textureVersion:string='LeePerrySmith-Map-COL-r186-original';
  regions: RegionRecord[]=[];
  snapshots: Snapshot[]=[{revision:0,operations:[]}];
  cursor: number=0;
  candidate: CandidatePlan | undefined=undefined;
  pending: Snapshot | undefined=undefined;
  pendingRequest: string='';
  private pendingCursor: number=-1;
  protection: Protection | undefined=undefined;
  view: SceneView={yaw:0,pitch:0,distance:16,panX:0,panY:0};
  get operations(): EditOperation[] { return this.snapshots[this.cursor].operations; }
  propose(kind: string, regionId: string, presetId: string='rose', strength: number=0.25, replacesLast: boolean=false): CandidatePlan {
    const p: CandidatePlan={planId:'plan-'+Date.now()+'-'+Math.floor(Math.random()*100000),assetId:this.assetId,assetVersion:this.assetVersion,baseRevision:this.revision,kind,regionId,presetId,strength,replacesLast};
    PolicyEngine.validate(p,this.assetId,this.assetVersion,this.revision,this.regions,this.sourceKind);
    p.baseSceneRevision=this.sceneRevision;
    this.candidate=p;return p;
  }
  protectionKey():string { const p=this.protection;return p?(p.ruleId||p.regionId+'@'+p.anchorRevision):''; }
  authorize(planId: string, allowProtectedOnce:boolean=false): Snapshot {
    if(this.pending) { throw new Error('上一项修改尚未完成'); }
    const p=this.candidate;
    if(!p || p.planId!==planId) { throw new Error('候选方案已取消或过期'); }
    if(!p.plannerSource?.startsWith('DeepSeek · ')||!p.snapshotId){throw new Error('新的外观修改必须先由模型提出候选');}
    if(p.baseSceneRevision!==undefined&&p.baseSceneRevision!==this.sceneRevision)throw new Error('候选生成后区域或规则已改变，请重新提出');
    PolicyEngine.validate(p,this.assetId,this.assetVersion,this.revision,this.regions,this.sourceKind);
    const ops=this.operations.slice();
    const op=PolicyEngine.authorizedOperation(p,'preview-'+p.planId);
    if(allowProtectedOnce){if(!this.protection)throw new Error('保护状态已改变');op.protectionException=this.protectionKey();}
    if(p.targetLayerId){const index=ops.findIndex((v:EditOperation)=>v.operationId===p.targetLayerId);if(index<0)throw new Error('目标编辑层已改变');if(p.removeLayer)ops.splice(index,1);else ops[index]=op;}
    else if(p.replacesLast && ops.length>0) { ops[ops.length-1]=op; } else { ops.push(op); }
    if(ops.length>8) { throw new Error('本版每份作品最多支持 8 项表达，请先撤销一项'); }
    this.candidate=undefined;return this.begin(ops,-1);
  }
  private begin(operations: EditOperation[], cursor: number): Snapshot {
    if(this.pending) { throw new Error('请等待当前修改完成'); }
    this.revision++;this.sceneRevision++;this.pendingRequest='render-'+this.revision+'-'+Date.now();this.pendingCursor=cursor;
    this.pending={revision:this.revision,operations:operations.slice()};return this.pending;
  }
  replay(direction: number): Snapshot {
    const next=this.cursor+direction;if(next<0||next>=this.snapshots.length) { throw new Error('没有可回放的版本'); }
    // Active protection is always sent separately; undo/redo never restores an obsolete policy.
    return this.begin(this.snapshots[next].operations,next);
  }
  reset(): Snapshot { return this.begin([],-1); }
  succeeded(requestId: string, revision: number): boolean {
    if(!this.pending || requestId!==this.pendingRequest || revision!==this.pending.revision) { return false; }
    if(this.pendingCursor>=0) { this.cursor=this.pendingCursor; }
    else { this.snapshots=this.snapshots.slice(0,this.cursor+1);this.snapshots.push(this.pending);this.cursor=this.snapshots.length-1; }
    this.pending=undefined;this.pendingRequest='';return true;
  }
  failed(): void { this.pending=undefined;this.pendingRequest='';this.candidate=undefined; }
  protect(regionId: string, keepCurrent: boolean, persistent: boolean): void {
    if(this.pending) { throw new Error('请等待当前修改完成'); }
    if(!this.regions.some((r:RegionRecord)=>r.regionId===regionId)) { throw new Error('请先圈选需要保护的区域'); }
    if(this.protection) { throw new Error('本版支持一处保护范围；请先明确移除已有保护再建立新范围'); }
    const anchor=JSON.parse(JSON.stringify(this.operations)) as EditOperation[];
    this.protection={ruleId:'rule-'+Date.now(),regionId,anchorRevision:keepCurrent?this.snapshots[this.cursor].revision:0,anchorOperations:keepCurrent?anchor:[],persistent};
    this.sceneRevision++;
    this.candidate=undefined;
  }
  serialize(id: string,label: string): SavedWorkspace {
    if(this.pending) { throw new Error('渲染成功后才能保存作品'); }
    const s: SavedWorkspace={schemaVersion:1,workspaceId:id,label,assetId:this.assetId,assetVersion:this.assetVersion,sourceKind:this.sourceKind,sourceFile:this.sourceFile,width:this.width,height:this.height,regions:this.regions,snapshots:this.snapshots,cursor:this.cursor,protection:this.protection,savedAt:Date.now()};
    s.view=this.view;s.sceneRevision=this.sceneRevision;s.regionVersion=this.regionVersion;s.textureVersion=this.textureVersion;s.renderPipelineVersion='self-native-per-operation-v2';return JSON.parse(JSON.stringify(s)) as SavedWorkspace;
  }
  restore(s: SavedWorkspace): void {
    if(s.schemaVersion!==1 || s.cursor<0 || s.cursor>=s.snapshots.length) { throw new Error('不支持这个作品版本'); }
    this.assetId=s.assetId;this.assetVersion=s.assetVersion;this.sourceKind=s.sourceKind;this.sourceFile=s.sourceFile;
    this.width=s.width;this.height=s.height;this.regions=s.regions;this.snapshots=s.snapshots;this.cursor=s.cursor;this.protection=s.protection;
    this.view=s.view||{yaw:0,pitch:0,distance:16,panX:0,panY:0};
    this.sceneRevision=(s.sceneRevision||0)+1;this.regionVersion=s.regionVersion||s.regions.length;this.textureVersion=s.textureVersion||(s.sourceKind==='MESH'?'LeePerrySmith-Map-COL-r186-original':s.assetVersion);
    this.revision=Math.max(...s.snapshots.map((v:Snapshot)=>v.revision))+1;this.failed();
  }
}
