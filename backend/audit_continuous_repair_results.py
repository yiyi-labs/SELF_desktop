"""Read-only completed research evidence aggregation; writes one fresh output.
Does not train, mutate candidates or select a production default.
"""
import argparse,json,hashlib,shutil
from pathlib import Path
import numpy as np

def digest(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        while True:
            b=f.read(1048576)
            if not b:break
            h.update(b)
    return h.hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def run(root,out):
    root=Path(root);out=Path(out);out.mkdir(parents=True,exist_ok=False);branches={};names=['neck/rigid-control','neck/strain-candidate','neck-material-jacobian/rigid-control','neck-material-jacobian/strain-candidate','face-measured-recorded/appearance-control','face-measured-recorded/measured-candidate','hair-measured/appearance-control','hair-measured/measured-candidate','room-projected-surface/old-kernel-control','room-projected-surface/surface-candidate','hair-native-surface/old-patch-control','hair-native-surface/actual-surface-candidate']
    for name in names:
        folder=root/name;r=read(folder/'result.json');ply=folder/'candidate-research-only.ply';side=folder/'candidate-identities.npz'
        z=dict(np.load(side));assert digest(ply)==r['assetHash']==str(z['asset_hash']);assert len(z['point_id'])==r['pointCount']
        ck={n:{'exists':(folder/(n+'.pt')).exists(),'sha256':digest(folder/(n+'.pt'))} for n in ['initial','mid','candidate-final','restored']}
        metrics={n:r[n] for n in ['baseline','initial','final']};ref=r['reference'];regions={}
        for part in r['baseline'][ref]:
            a=r['baseline'][ref][part];b=r['final'][ref][part];regions[part]=dict(before=a,after=b)
        branches[name]=dict(assetHash=r['assetHash'],sidecarHash=digest(side),sourceHash=r['sourceHash'],reference=ref,pointCount=r['pointCount'],steps=r['steps'],failures=r['failures'],frozenBaselineExact=r['frozenBaselineExact'],transactionAccepted=r['transactionAccepted'],releaseQualityPassed=r['releaseQualityPassed'],trainEvalSeconds=r['trainEvalSeconds'],allocatedMiB=r['allocatedMiB'],reservedMiB=r['reservedMiB'],parameterChanges=r.get('parameterChanges'),referenceRegions=regions,checkpoints=ck)
        if 'localFinal' in r:branches[name]['localMetrics']=r['localFinal']
        (out/(name.replace('/','-')+'-metrics.json')).write_text(json.dumps(metrics,indent=2)+'\n')
    measurements=read(root/'observed-tracks/result.json');body=read(root/'body-motion/result.json');summary=dict(branches=branches,sourceHash=next(iter(branches.values()))['sourceHash'],GPUTrainingBranches=len(branches),AdamSteps=sum(b['steps'] for b in branches.values()),measurement=measurements,bodyMotion=body,faceGeometry=read(root/'face-measured-recorded/geometry.json'),hairGeometry=read(root/'hair-measured/geometry.json'),nativeHairProposal=read(root/'hair-native-surface/proposal.json'),nativeHairMVS=read(root/'head-restored-native-mvs/execution.json'),display=read(root/'display-comparison/result.json'),hairDisplay=read(root/'hair-surface-display-comparison/result.json'),neckOrbit=read(root/'neck-fixed-orbit/frozen-ply/result.json'),hairOrbit=read(root/'hair-surface-fixed-orbit/frozen-ply/result.json'),published=False,HarmonyOSTested=False,originalE1E5Unchanged=True)
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');shutil.copyfile(__file__,out/Path(__file__).name)
    print(json.dumps(dict(branches=len(branches),steps=summary['AdamSteps'],maxAllocatedMiB=max(b['allocatedMiB'] for b in branches.values()),maxReservedMiB=max(b['reservedMiB'] for b in branches.values()),allFrozenExact=all(b['frozenBaselineExact'] for b in branches.values()),allRestored=all(b['checkpoints']['restored']['exists'] for b in branches.values()),published=False)),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--out',required=True);a=p.parse_args();run(a.root,a.out)
