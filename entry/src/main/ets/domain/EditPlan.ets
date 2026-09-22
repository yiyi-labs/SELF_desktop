export interface EditOperation {
  operationId: string;
  kind: string;
  regionId: string;
  presetId: string;
  color: number[];
  absoluteStrength: number;
  authorizationId: string;
  plannerSource?: string;
  snapshotId?: string;
  protectionException?: string;
}
export interface RegionRecord {
  regionId: string;
  assetId: string;
  assetVersion: string;
  width: number;
  height: number;
  semantic: string;
  fileName: string;
}
export interface CandidatePlan {
  planId: string;
  assetId: string;
  assetVersion: string;
  baseRevision: number;
  baseSceneRevision?: number;
  kind: string;
  regionId: string;
  presetId: string;
  strength: number;
  replacesLast: boolean;
  targetLayerId?: string;
  removeLayer?: boolean;
  plannerSource?: string;
  snapshotId?: string;
}
export interface Protection {
  ruleId?: string;
  regionId: string;
  anchorRevision: number;
  anchorOperations: EditOperation[];
  persistent: boolean;
}
export interface Snapshot {
  revision: number;
  operations: EditOperation[];
}
export interface SceneView { yaw:number; pitch:number; distance:number; panX:number; panY:number; }
export interface SavedWorkspace {
  schemaVersion: number;
  workspaceId: string;
  label: string;
  assetId: string;
  assetVersion: string;
  sourceKind: string;
  sourceFile: string;
  width: number;
  height: number;
  regions: RegionRecord[];
  snapshots: Snapshot[];
  cursor: number;
  protection: Protection | undefined;
  savedAt: number;
  view?: SceneView;
  sceneRevision?: number;
  regionVersion?: number;
  textureVersion?: string;
  renderPipelineVersion?: string;
}
