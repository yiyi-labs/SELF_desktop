"""Observed texture transfer on a shared surface; one bounded F correction.

A ray hits the current surface in the source. The SAME triangle/barycentric
point is transferred through the target expression mesh and projected. The
error is against independently tracked RGB features, not self-projected FLAME.
"""
import json,numpy as np,torch
from reconstruction_portrait_pipeline import make_frame
from reconstruction_components_v3 import save_json


def intersect(mesh,faces,F,K,uv):
    tri=mesh[faces];edge1=tri[:,1]-tri[:,0];edge2=tri[:,2]-tri[:,0];origin=np.linalg.inv(F)[:3,3]
    ray=np.linalg.solve(K,np.r_[uv,1.]);ray=F[:3,:3].T@ray;ray/=np.linalg.norm(ray)
    p=np.cross(np.broadcast_to(ray,edge2.shape),edge2);det=(edge1*p).sum(1)
    inv=np.divide(1.,det,out=np.zeros_like(det),where=np.abs(det)>1e-9);tvec=origin-tri[:,0]
    u=(tvec*p).sum(1)*inv;q=np.cross(tvec,edge1);v=(q*ray).sum(1)*inv;t=(edge2*q).sum(1)*inv
    good=(abs(det)>1e-9)&(u>=0)&(v>=0)&(u+v<=1)&(t>.01)
    if not good.any():return None
    indices=np.flatnonzero(good);i=indices[np.argmin(t[good])]
    return int(i),np.array([1-u[i]-v[i],u[i],v[i]])


def bounded_correspondence(model,data,out):
    report=json.loads((out/'correspondences.json').read_text());side=report['selected'];rows=[r for r in report['rows'] if r['side']==side and r.get('accepted',0)>=4]
    archive=np.load(out/'tracks.npz');records=[];p=model.portrait;faces=p.faces.cpu().numpy()
    for i,row in enumerate(rows):
        a,b=row['a'],row['b'];fa=model.adjusted_frame(make_frame(data,a,crop=False));mesh=(fa['mesh']+p.surface_residual).detach().cpu().numpy();F=fa['F'].detach().cpu().numpy()
        pts=archive[f'{i}_a'];targets=archive[f'{i}_b'];ti=[];ba=[];ta=[]
        for uv,target in zip(pts,targets):
            hit=intersect(mesh,faces,F,data['K'],uv)
            if hit is not None:ti.append(hit[0]);ba.append(hit[1]);ta.append(target)
        if len(ti)>=4:records.append({'a':a,'b':b,'triangle':torch.tensor(ti,device='cuda'),
            'bary':torch.tensor(np.array(ba),device='cuda',dtype=torch.float32),'target':torch.tensor(np.array(ta),device='cuda')})
    for param in model.parameters():param.requires_grad_(False)
    start=model.pose.delta.detach().clone();K=torch.tensor(data['K'],device='cuda',dtype=torch.float32)
    def errors():
        values=[]
        for r in records:
            f=make_frame(data,r['b'],crop=False);mesh=f['mesh']+p.surface_residual
            xyz=(mesh[p.faces[r['triangle']]]*r['bary'][...,None]).sum(1);F=model.pose(r['b'],f['F']);cam=xyz@F[:3,:3].T+F[:3,3];uv=cam@K.T;uv=uv[:,:2]/uv[:,2:];values.append(uv-r['target'])
        return values
    with torch.no_grad():before=[e.norm(dim=-1).cpu().numpy() for e in errors()]
    needs=any(np.median(e)>2.5 for e in before);iterations=0;curve=[]
    # Source charts stay fixed. Only target frames with RGB correspondences
    # receive bounded residual F. Identity/K/scale/expressions stay frozen.
    targetset={r['b'] for r in records};trainable=torch.zeros(len(model.pose.names),device='cuda',dtype=torch.bool)
    for name in targetset:
        if name!=model.pose.reference:trainable[model.pose.index[name]]=True
    if needs and records:
        model.pose.delta.requires_grad_(True);optimizer=torch.optim.Adam([model.pose.delta],lr=.005)
        for step in range(64):
            optimizer.zero_grad(set_to_none=True);values=errors();loss=sum(torch.nn.functional.smooth_l1_loss(e,torch.zeros_like(e),beta=1.) for e in values)/len(values)
            loss+=.01*(model.pose.delta-start).square().mean();loss.backward();model.pose.delta.grad[~trainable]=0;optimizer.step()
            with torch.no_grad():
                model.pose.delta.copy_(torch.maximum(torch.minimum(model.pose.delta,start+.20),start-.20));model.pose.delta[~trainable]=start[~trainable]
            if step%16==0:curve.append({'step':step,'loss':float(loss.detach())})
        iterations=64
        torch.save({'optimizer':optimizer.state_dict(),'initialDelta':start,'finalDelta':model.pose.delta.detach(),'records':records,'curve':curve},out/'bounded-correspondence.pt')
        model.pose.delta.requires_grad_(False)
    with torch.no_grad():after=[e.norm(dim=-1).cpu().numpy() for e in errors()]
    selected=[];details=[]
    for r,a,b in zip(records,before,after):
        good=np.median(b)<=2.5 and np.quantile(b,.9)<=5.
        if good:selected.extend([r['a'],r['b']])
        details.append({'a':r['a'],'b':r['b'],'count':len(a),'beforeMedian':float(np.median(a)),'afterMedian':float(np.median(b)),
            'afterP90':float(np.quantile(b,.9)),'acceptedForLocalCapacity':bool(good)})
    names=sorted(set(selected));result={'pixelChecks':details,'optimizerSteps':iterations,'curve':curve,'selectedTrainingNames':names,
        'maximumRawPoseDeltaChange':float((model.pose.delta-start).abs().max()),'bound':'+/-0.20 raw tanh parameter; original 1 degree/.0015 head-unit caps retained',
        'fixed':'K, world C, identity, expression, mesh, scene scale, source-ray triangle bindings',
        'independentEvidence':'bidirectional real RGB texture tracks; local depth still conditional on F and low frequency mesh',
        'sufficient':len(names)>=4 and sum(r['acceptedForLocalCapacity'] for r in details)>=3}
    save_json(out/'surface-transfer.json',result)
    if not result['sufficient']:raise ValueError('bounded_surface_transfer_still_exceeds_detail_scale')
    return names,result
