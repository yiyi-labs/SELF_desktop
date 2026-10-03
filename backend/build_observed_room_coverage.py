"""Re-budget unchanged multi-view surface hypotheses by projected footprints."""
from pathlib import Path
import argparse,json,time,shutil
import numpy as np
from build_continuity_candidates import collect,inside_mask
from reconstruction_components_v3 import load_v3_prepared,save_json,sha
from reconstruction_continuity_surface import physical_masks,spatial_neighbours
from reconstruction_dense_contract import project,bilinear
from reconstruction_dense_surfaces import native_uv
from reconstruction_observed_coverage import footprint_atlas,balanced_select,atlas_summary,protected_exchange


def run(prepared,depth,out,budget=22000,pool_cache=None):
    start=time.perf_counter();out=Path(out);out.mkdir(parents=True,exist_ok=False)
    if pool_cache is None:collect(prepared,depth,out/'uniform',component='room',budget=budget,save_pool=True)
    else:
        (out/'uniform').mkdir()
        for file in ('supported-pool.npz','surface.npz','result.json'):shutil.copyfile(Path(pool_cache)/file,out/'uniform'/file)
    a=dict(np.load(out/'uniform/supported-pool.npz'));old=dict(np.load(out/'uniform/surface.npz'))
    data=load_v3_prepared(Path(prepared));spec=json.loads((Path(depth)/'manifest.json').read_text())
    cached=json.loads((out/'uniform/result.json').read_text())
    if str(a['source_hash'])!=data['sourceHash'] or cached['sourceHash']!=data['sourceHash'] or cached['depthHash']!=sha(Path(depth)/'manifest.json'):
        raise ValueError('cached_pool_contract_changed')
    rows=[r for r in spec['observations'] if r['group']=='world' and r['scaleGatePassed']]
    names=sorted({r['imageName'] for r in rows});masks=physical_masks(prepared,data,names);observations=[]
    for name in names:
        compatible=np.zeros(len(a['means']),bool)
        for r in [r for r in rows if r['imageName']==name]:
            if r['role']!='train' or name in spec['forbidden']:raise ValueError('role_leak')
            d=dict(np.load(Path(depth)/r['file']));np.testing.assert_allclose(d['W2C'],data['worlds'][name],rtol=0,atol=1e-5)
            uv,z=project(a['means'],d['K'],d['W2C']);h,w=d['depth'].shape;dep=bilinear(d['depth'],uv);conf=bilinear(d['confidence'],uv)
            ok=(z>0)&(uv[:,0]>=0)&(uv[:,0]<w-1)&(uv[:,1]>=0)&(uv[:,1]<h-1)&np.isfinite(dep)&(dep>0)
            ok&=inside_mask(masks[name]['room'],native_uv(uv,d['nativeToProcessed']))&(conf>=np.quantile(d['confidence'],.2))
            compatible|=ok&(np.abs(z-dep)<=.03*dep)
        observations.append(dict(name=name,role='train',C=data['worlds'][name],K=data['K'],mask=masks[name]['room'],point_visible=compatible))
    atlas,weight,metadata=footprint_atlas(a,observations,cell=8,alpha_floor=.05,max_radius=96)
    proposed,trace=balanced_select(atlas,weight,a['uid'],budget,batch=64,target_mass=1.5)
    lookup={int(uid):i for i,uid in enumerate(a['uid'])};uniform=np.array([lookup[int(uid)] for uid in old['uid']])
    selected,exchanges=protected_exchange(atlas,weight,a['uid'],uniform,proposed,max_swaps=5000)
    folder=out/'coverage';folder.mkdir();arrays={k:v[selected] for k,v in a.items() if v.ndim>0}
    arrays['edges']=spatial_neighbours(arrays['means'],arrays['quats'],arrays['scales'],arrays['parts'])
    np.savez_compressed(folder/'surface.npz',**arrays,source_hash=a['source_hash'])
    meta=json.loads((out/'uniform/result.json').read_text());meta.update(selection='train-only footprint exchange with baseline sample floors',count=len(selected),geometrySupported=False)
    save_json(folder/'result.json',meta)
    for key in ('means','quats','scales','opacity','sh'):
        if not np.array_equal(old[key],a[key][uniform]):raise ValueError('uniform_pool_restore_changed:'+key)
        if not np.array_equal(arrays[key],a[key][selected]):raise ValueError('selection_changed_parameters:'+key)
    np.savez_compressed(out/'selection.npz',uniform=uniform,coverage=selected,unguarded=proposed,pool_uid=a['uid'])
    save_json(out/'protected-exchanges.json',exchanges)
    save_json(out/'selection.json',dict(sourceHash=data['sourceHash'],poolHash=sha(out/'uniform/supported-pool.npz'),
        inputDepthHash=sha(Path(depth)/'manifest.json'),budget=budget,poolCount=len(a['means']),atlasShape=list(atlas.shape),atlasNonzero=int(atlas.nnz),
        metadata=metadata,trace=trace,uniform=atlas_summary(atlas,uniform,metadata),coverage=atlas_summary(atlas,selected,metadata),unguarded=atlas_summary(atlas,proposed,metadata),
        unchangedInitialParameterValues=True,pointCountSingleFactor=True,trainingOnly=True,
        limits='Potential footprint samples, not actual alpha or independent geometry. Prediction-compatible depth can share systematic error; coverage outside available support is not invented.',seconds=time.perf_counter()-start,published=False))
    src=out/'algorithm-source';src.mkdir()
    for name in ('build_observed_room_coverage.py','reconstruction_observed_coverage.py','build_continuity_candidates.py','reconstruction_continuity_surface.py','reconstruction_dense_surfaces.py'):
        shutil.copyfile(Path(__file__).with_name(name),src/name)
    print(json.dumps(dict(stage='coverage_candidates',count=budget,seconds=time.perf_counter()-start)),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('prepared','depth','out'):p.add_argument('--'+k,required=True)
    p.add_argument('--budget',type=int,default=22000);p.add_argument('--pool-cache');a=p.parse_args();run(a.prepared,a.depth,a.out,a.budget,a.pool_cache)
