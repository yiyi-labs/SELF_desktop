"""Bounded native shader-radius attribution, no renderer or asset modification."""
import json
import numpy as np,torch
from run_haze_shared_surface import ROOT
from reconstruction_joint_visibility import load_recorded_ply
from reconstruction_portrait_model import GaussianState
from reconstruction_surface_patch import weights
from reconstruction_components_v3 import save_json
D=ROOT/'D';c=json.loads((D/'display.json').read_text());a=load_recorded_ply(D/'R0-frozen-T2.ply',9053);n=len(a['means']);parts=torch.zeros(n,device='cuda',dtype=torch.long);s=GaussianState(a['means'],a['quats'],a['scales'],a['opacity'],a['sh'][:,:4],parts)
C=torch.tensor(c['C'],device='cuda',dtype=torch.float32);K=torch.tensor(c['K'],device='cuda',dtype=torch.float32);v=s.means@C[:3,:3].T+C[:3,3];cov=C[:3,:3]@s.covariance()@C[:3,:3].T
# PC shader's J has 2*focal and its clip-to-pixel multiplies by 1/2.
# Both factors retained, including the actual 1024 shader radius cap.
z=v[:,2];J=torch.zeros(n,2,3,device='cuda');J[:,0,0]=2*K[0,0]/z;J[:,1,1]=2*K[1,1]/z;J[:,0,2]=-2*K[0,0]*v[:,0]/z.square();J[:,1,2]=-2*K[1,1]*v[:,1]/z.square()
cov2=J@cov@J.transpose(-1,-2)+torch.eye(2,device='cuda')*.3;eigen=torch.cat([torch.linalg.eigvalsh(chunk) for chunk in cov2.split(1024)]).clamp_min(.1);uncapped=(2*eigen).sqrt();cap=min(1024,c['width'],c['height']);capped=(uncapped>cap).any(1)&(z>0)
face=torch.tensor(np.load(D/'source-reference.npz')['face'],device='cuda');w,info=weights(s,C,K,c['width'],c['height'],face,unit_scale=c['near']/.01)
order=torch.argsort(w,descending=True)[:12];room=torch.zeros(n,device='cuda',dtype=torch.bool);room[11970:11970+26054]=True
rows=[{'index':int(i),'component':'room' if room[i] else 'person','gsplatAccumulatedFaceContribution':float(w[i]),'PCUncappedEllipseRadiusPx':uncapped[i].cpu().tolist(),'PC1024RadiusCapActive':bool(capped[i]),'cameraZ':float(z[i])} for i in order]
report={'shaderVersion':'PlayCanvas2.22.4 actual gsplatCorner.js','capPixels':cap,'positiveDepthCappedPoints':int(capped.sum()),'roomCappedPoints':int((room&capped).sum()),
 'fractionOfGsplatFaceContributionFromPCCappedRoom':float(w[room&capped].sum()/w.sum()),'topActualFaceContributors':rows,
 'limits':'different projection clamp, normExp tail, work-buffer quantization and depth ordering also remain; this is not a causal percentage of all haze and does not alter the viewer'}
save_json(D/'projection-support.json',report);print(json.dumps(report),flush=True)

