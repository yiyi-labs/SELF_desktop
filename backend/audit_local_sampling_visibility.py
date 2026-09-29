"""Bounded, zero-training point audit. Never prepares, renders or publishes assets.

Consumes frozen proposal/evidence logs. Only d=2 gets one research centroid;
all point decisions use the existing 59-view rule. Audit labels are separate.
"""
from pathlib import Path
import argparse
import collections
import hashlib
import json
import math
import resource
import time
import numpy as np
from reconstruction_scene import _surface_token, _surface_point_votes, _surface_bits


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')


def read_rows(path):
    with Path(path).open(encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]


def original_grid(d):
    return np.array([(a / d, b / d, 1 - (a + b) / d)
                     for a in range(1, d) for b in range(1, d - a)], np.float64)


def research_grid(d, triangle_passed):
    if not triangle_passed:
        return np.empty((0, 3), np.float64)
    if d == 2:
        return np.array([[1/3, 1/3, 1/3]], np.float64)
    return original_grid(d)


def point_identity(namespace, ids, numerator):
    canonical = sorted(ids)
    weights = [numerator[ids.index(i)] for i in canonical]
    divisor = math.gcd(*weights)
    weights = tuple(int(x // divisor) for x in weights)
    sid = _surface_token(namespace, 1, *canonical)
    return sid, _surface_token(namespace, 1, sid, *weights), weights


def project(points, C, K):
    cp = np.einsum('ij,pj->pi', C[:3, :3], points) + C[:3, 3]
    pu = np.einsum('ij,pj->pi', K, cp)
    uv = pu[:, :2] / np.maximum(pu[:, 2:], 1e-8)
    return uv, cp[:, 2]


def triangle_check(world, C, K):
    uv, depth = project(world, C, K)
    edge = max(np.linalg.norm(uv[i] - uv[j]) for i,j in ((0,1),(1,2),(2,0)))
    spread = float(np.ptp(depth) / max(np.median(depth), 1e-6))
    normal = np.cross(world[1]-world[0], world[2]-world[0]); norm = np.linalg.norm(normal)
    normal = normal / max(norm, 1e-30)
    ray = world.mean(0) - np.linalg.inv(C)[:3,3]; ray /= np.linalg.norm(ray)
    cosine = float(abs(normal @ ray)); d = min(10,max(2,int(edge/9)))
    reason = ('edge' if edge > 80 or edge < 7 else 'depthSpread' if spread > .06 else
              'degenerate' if norm < 1e-8 else 'normal' if cosine < .25 else
              'noInteriorSamples' if d < 3 else 'geometryAccepted')
    return reason, d


def in_window(uv, depth, rect):
    x0,y0,x1,y1 = rect
    return bool(np.all(depth > .01) and np.all((uv[:,0] >= x0) & (uv[:,0] <= x1) &
                                             (uv[:,1] >= y0) & (uv[:,1] <= y1)))


def original_decision(sampled, valid, reference):
    if len(sampled) != 59 or len(valid) != 59:
        raise ValueError('all_original_59_observations_required')
    keep, votes, bad, _, positive, conflicts = _surface_point_votes(sampled, valid, reference)
    return keep, votes, bad, _surface_bits(positive), _surface_bits(conflicts)


def interpretation(valid, detailed, kernel_room_count):
    # No independent first-surface depth exists in this audit. A room label is
    # not proof of visibility. Pixel-kernel mixing is a risk, not a causal verdict.
    if not valid:
        return '5_original_rule_excluded'
    if detailed and kernel_room_count < 9:
        return '4_boundary_mixing_or_projection_unresolved'
    return '3_room_pixel_candidate_visibility_unknown'


def bits_names(bits, names):
    return [n for i,n in enumerate(names) if bits & (1 << i)]


def verify_frozen(manifest):
    bad = [p for p,h in manifest.items() if not Path(p).is_file() or sha(p) != h]
    if bad:
        raise ValueError('frozen_inputs_changed:' + repr(bad[:10]))


def run(args):
    import cv2
    import pycolmap
    start = time.perf_counter()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    pool = args.stage2 / 'candidate-pool'
    cfg = json.loads(args.windows.read_text())
    meta = json.loads((args.stage2 / 'config.json').read_text())
    prep = json.loads((args.prepared / 'preparation.json').read_text())
    summary = json.loads((pool / 'summary.json').read_text())
    names = summary['trainingViews']; namespace = meta['namespace']
    if len(names) != 59 or set(names) != set(prep['train']) or names != meta['trainingViews']:
        raise ValueError('frozen_training_names_differ')
    win = {x['imageName']: x for x in cfg['windows']}
    if len(win) != 9 or not set(win).issubset(names) or set(win) & set(prep['development']):
        raise ValueError('nine_train_views_only')
    map_path = args.original_backend / prep['staticMap']
    # Snapshot entire frozen candidate/prepared/replay tree, original geometry,
    # all 59 decision images/masks, actual map and current production sources.
    files = list(args.stage2.rglob('*')) + list(map_path.glob('*.bin'))
    files += [args.windows, args.prepared/'preparation.json', args.prepared/'local_geometry.npz',
              args.prepared/'static_surface_seeds.npz', Path(__file__),
              Path(__file__).with_name('reconstruction_scene.py')]
    for name in names:
        files += [args.prepared/'rectified_observations'/name,
                  args.prepared/'rectified_observations'/(name+'.npz')]
    frozen = {str(p.resolve()): sha(p) for p in files if p.is_file()}
    write_json(out/'frozen-inputs-before.json', frozen)
    expected_sources = json.loads((args.stage2/'review/delivery-source-hashes.json').read_text())
    for name,h in expected_sources.items():
        if sha(Path(__file__).with_name(name)) != h:
            raise ValueError('stage2_source_changed:'+name)
    if sha(args.prepared/'static_surface_seeds.npz') != meta['oldPreparedSha256']:
        raise ValueError('old_prepared_changed')
    for name,h in meta['mapFiles'].items():
        if sha(map_path/name) != h:
            raise ValueError('map_changed:'+name)
    for name,w in win.items():
        if sha(args.prepared/'rectified_observations'/name) != w['rgbSha256'] or sha(args.prepared/'rectified_observations'/(name+'.npz')) != w['maskSha256']:
            raise ValueError('window_image_changed:'+name)
    g = np.load(args.prepared/'local_geometry.npz', allow_pickle=False)
    K = g['K']; cs = dict(zip(g['world_names'].tolist(),g['C']))
    model = pycolmap.Reconstruction(str(map_path))
    image_map = {im.name:im for im in model.images.values() if im.has_pose}
    for name in names:
        mc = np.eye(4); mc[:3] = image_map[name].cam_from_world().matrix()
        if not np.allclose(cs[name],mc,atol=1e-12,rtol=0):
            raise ValueError('camera_name_mapping_changed:'+name)
    proposals = read_rows(pool/'triangle-proposals.jsonl')
    legal = read_rows(pool/'legal-samples.jsonl')
    evidence = read_rows(pool/'sample-evidence.jsonl')
    canonical_by_sid = {r['surfaceId']: sorted(r['orderedPointIds']) for r in proposals}
    legal_by_sid = collections.defaultdict(set)
    legal_by_pid = {r['pointId']:r for r in legal}
    tested_by_pid = collections.defaultdict(list)
    for r in legal: legal_by_sid[r['surfaceId']].add(r['pointId'])
    for r in evidence: tested_by_pid[r['pointId']].append(r)
    selected = []
    for p in proposals:
        if p['view'] not in win: continue
        world = np.stack([model.points3D[i].xyz for i in p['orderedPointIds']])
        uv,z = project(world,cs[p['view']],K)
        if not in_window(uv,z,win[p['view']]['rect']): continue
        check,d = triangle_check(world,cs[p['view']],K)
        if check != p['firstDecision'] or d != p['divisions']:
            raise ValueError('cached_triangle_check_mismatch')
        selected.append(dict(p,group=win[p['view']]['group'],projectedVertices=uv.tolist()))
    with (out/'local-triangle-proposals.jsonl').open('w') as f:
        for p in selected: f.write(json.dumps(p)+'\n')
    selected_keys = {(p['surfaceId'],p['view']):p for p in selected}
    old_rows = [r for r in evidence if (r['surfaceId'],r['origin']) in selected_keys]
    candidates = []
    for p in selected:
        if p['firstDecision'] != 'noInteriorSamples' or p['divisions'] != 2: continue
        assert research_grid(p['divisions'], p['firstDecision'] == 'noInteriorSamples').shape == (1,3)
        sid,pid,bary = point_identity(namespace,p['orderedPointIds'],[1,1,1])
        if sid != p['surfaceId']: raise ValueError('identity_mismatch')
        candidates.append({'pointId':pid,'surfaceId':sid,'origin':p['view'],'divisions':2,
                           'baryNumerator':list(bary),'group':p['group'],
                           'originalGeneratorProposed':False,'candidateGeneratorProposed':True,
                           'alreadyTestedCentroid':pid in tested_by_pid,
                           'alreadyLegalCentroid':pid in legal_by_pid,
                           'surfaceHadLegalSamples':bool(legal_by_sid[sid]),
                           'originalWinding':p['orderedPointIds']})
    all_points = {}
    for r in old_rows+candidates:
        ids = canonical_by_sid[r['surfaceId']]; bary=np.asarray(r['baryNumerator'],np.float64)
        world = np.stack([model.points3D[i].xyz for i in ids])
        xyz = (bary / bary.sum()) @ world
        all_points[r['pointId']] = {'surfaceId':r['surfaceId'],'canonicalPointIds':ids,
                                    'baryNumerator':r['baryNumerator'],'xyz':xyz.tolist()}
    pids = sorted(all_points); index = {pid:i for i,pid in enumerate(pids)}
    xyz = np.asarray([all_points[pid]['xyz'] for pid in pids],np.float64).reshape(-1,3)
    if not len(xyz): raise ValueError('no_bounded_points_do_not_expand_windows_automatically')
    write_json(out/'point-identities.json', {'namespace':namespace,'source_kind':1,'points':all_points})
    # Streaming images keeps peak memory small. Never loads a development RGB.
    sampled=[]; raw=[]; valid=[]; unknown=[]; excluded=[]; coordinates=[]; depths=[]
    kernel_counts=[]; kernel_ranges=[]; inside_all=[]
    for name in names:
        p=args.prepared/'rectified_observations'/name
        rgb=cv2.cvtColor(cv2.imread(str(p)),cv2.COLOR_BGR2RGB).astype(np.float32)/255
        masks=np.load(str(p)+'.npz',allow_pickle=False); room=masks['room_visible'].astype(bool)
        uv,z=project(xyz,cs[name],K);xy=np.rint(uv).astype(np.int64);u,v=xy.T;h,w=room.shape
        ix=u.clip(0,w-1);iy=v.clip(0,h-1)
        inside=(z>.01)&(u>=2)&(v>=2)&(u<w-2)&(v<h-2)
        blur=cv2.GaussianBlur(rgb,(3,3),0)
        sampled.append(blur[iy,ix]); raw.append(rgb[iy,ix]);valid.append(inside&room[iy,ix])
        unknown.append(inside&masks['unknown_or_occluded'][iy,ix]);excluded.append(inside&~room[iy,ix])
        localroom=np.stack([room[(iy+dy).clip(0,h-1),(ix+dx).clip(0,w-1)] for dy in (-1,0,1) for dx in (-1,0,1)])
        patch=np.stack([rgb[(iy+dy).clip(0,h-1),(ix+dx).clip(0,w-1)] for dy in (-1,0,1) for dx in (-1,0,1)])
        kernel_counts.append(localroom.sum(0));kernel_ranges.append((patch.max(0)-patch.min(0)).mean(-1))
        coordinates.append(uv);depths.append(z);inside_all.append(inside)
    sampled=np.stack(sampled);valid=np.stack(valid);unknown=np.stack(unknown);excluded=np.stack(excluded)
    uv=np.stack(coordinates);depth=np.stack(depths);kc=np.stack(kernel_counts);kr=np.stack(kernel_ranges);inside=np.stack(inside_all)
    np.savez_compressed(out/'point-observations.npz',point_ids=np.asarray(pids),names=np.asarray(names),xyz=xyz,
                        K=K,C=np.stack([cs[n] for n in names]),uv=uv,depth=depth,rgb3x3=sampled,rgbRaw=np.stack(raw),
                        valid=valid,inside=inside,unknown=unknown,excluded=excluded,kernelRoomCount=kc,kernelRgbRange=kr)
    evaluations={n:original_decision(sampled,valid,names.index(n)) for n in win}
    unknown_bits=_surface_bits(unknown);excluded_bits=_surface_bits(excluded)
    mismatch=[]
    for r in old_rows:
        pi=index[r['pointId']];e=evaluations[r['origin']]
        actual=(bool(e[0][pi]),int(e[3][pi]),int(e[4][pi]),int(unknown_bits[pi]),int(excluded_bits[pi]))
        expected=(r['accepted'],r['supportBits'],r['conflictBits'],r['unknownBits'],r['maskExcludedBits'])
        if actual != expected: mismatch.append({'pointId':r['pointId'],'origin':r['origin'],'actual':actual,'expected':expected})
    write_json(out/'cached-decision-regression.json',{'rows':len(old_rows),'mismatches':mismatch})
    if mismatch: raise ValueError('old_decision_mismatch_do_not_continue:'+str(len(mismatch)))
    records=[]
    for kind,rows in [('d2_centroid',candidates),('original_rejected',[r for r in old_rows if not r['accepted']])]:
        for r in rows:
            pi=index[r['pointId']];ri=names.index(r['origin']);e=evaluations[r['origin']]
            sb,cb=int(e[3][pi]),int(e[4][pi]);u,v=np.rint(uv[ri,pi]).astype(int)
            source={'imageName':r['origin'],'uv':uv[ri,pi].tolist(),'pixel':[int(u),int(v)],
                    'sampledPixel':[int(np.clip(u,0,1079)),int(np.clip(v,0,1919))],
                    'positiveDepth':bool(depth[ri,pi]>.01),'boundaryValid':bool(inside[ri,pi]),
                    'roomValid':bool(valid[ri,pi]),'clamped':bool(u<0 or v<0 or u>=1080 or v>=1920),
                    'rgb3x3':sampled[ri,pi].tolist(),'kernelRoomPixels':int(kc[ri,pi]),
                    'kernelRgbRange':float(kr[ri,pi]),'depth':float(depth[ri,pi])}
            labels={}
            for vi,n in enumerate(names):
                if cb & (1<<vi) or not valid[vi,pi]:
                    labels[n]={'category':interpretation(valid[vi,pi],n in win,kc[vi,pi]),
                               'detailedReviewAllowed':n in win,'kernelRoomPixels':int(kc[vi,pi]),
                               'rgbDifference':float(np.abs(sampled[vi,pi]-sampled[ri,pi]).mean()),
                               'originalConflict':bool(cb & (1<<vi))}
            row=dict(r,kind=kind,group=win[r['origin']]['group'],
                     original_decision={'accepted':bool(e[0][pi]),'votes':int(e[1][pi]),'conflicts':int(e[2][pi]),
                       'supportBits':sb,'conflictBits':cb,'supportViews':bits_names(sb,names),'conflictViews':bits_names(cb,names),
                       'evaluatedViewCount':59},
                     audit_interpretation={'sourceReference':source,'targets':labels,
                       'verifiedFalseRejection':False,'verifiedGenuineContradiction':False,
                       'independentFirstSurfaceDepthAvailable':False,'changesOriginalDecision':False})
            records.append(row)
    with (out/'local-point-decisions.jsonl').open('w') as f:
        for r in records:f.write(json.dumps(r,separators=(',',':'))+'\n')
    results=[]
    for group in sorted({w['group'] for w in win.values()}):
        ps=[p for p in selected if p['group']==group];cr=[r for r in records if r['kind']=='d2_centroid' and r['group']==group]
        sidset={r['surfaceId'] for r in cr};pidset={r['pointId'] for r in cr};ok={r['pointId'] for r in cr if r['original_decision']['accepted']}
        results.append({'group':group,'cachedTriangleEventsInWindow':len(ps),'triangleFirstDecisions':dict(collections.Counter(p['firstDecision'] for p in ps)),
           'd2Events':len(cr),'uniqueD2Triangles':len(sidset),'trianglesAlreadyHaveLegalSamples':sum(bool(legal_by_sid[s]) for s in sidset),
           'trianglesNoLegalSamplesBefore':sum(not legal_by_sid[s] for s in sidset),
           'centroidsAlreadyTested':sum(pid in tested_by_pid for pid in pidset),'centroidsAlreadyLegal':sum(pid in legal_by_pid for pid in pidset),
           'centroidsNeverTested':sum(pid not in tested_by_pid for pid in pidset),
           'acceptedCentroidEvents':sum(r['original_decision']['accepted'] for r in cr),'acceptedUniqueCentroids':len(ok),
           'newlyLegalUniqueCentroids':len(ok-set(legal_by_pid)),
           'firstLegalTriangles':len({r['surfaceId'] for r in cr if r['pointId'] in ok and not r['surfaceHadLegalSamples']}),
           'additionalSamplesOnExistingSurfaces':len({r['pointId'] for r in cr if r['pointId'] in ok and r['pointId'] not in legal_by_pid and r['surfaceHadLegalSamples']}),
           'stillRejectedUniqueCentroids':len(pidset-ok)})
    source_stats={}
    for kind in ['original_rejected','d2_centroid']:
        rr=[r for r in records if r['kind']==kind]; src=[r['audit_interpretation']['sourceReference'] for r in rr]
        source_stats[kind]={'events':len(rr),'uniquePoints':len({r['pointId'] for r in rr}),
                           'invalidReferenceEvents':sum(not x['roomValid'] for x in src),
                           'clampedReferenceEvents':sum(x['clamped'] for x in src),
                           'nonpositiveDepthReferenceEvents':sum(not x['positiveDepth'] for x in src),
                           'crossMaskKernelReferenceEvents':sum(x['kernelRoomPixels']<9 for x in src),
                           'targetConflictCategories':dict(collections.Counter(v['category'] for r in rr for v in r['audit_interpretation']['targets'].values() if v['originalConflict']))}
    verify_frozen(frozen)
    output={'completed':True,'sourceHash':prep['sourceHash'],'namespace':namespace,'windowsSha256':sha(args.windows),
            'oldDecisionRegressionRows':len(old_rows),'oldDecisionMismatches':len(mismatch),
            'windows':results,'sourceReferenceAudit':source_stats,'uniqueEvaluatedPoints':len(pids),
            'trainingSteps':0,'optimizerCreated':False,'renderCalled':False,'productionChanged':False,
            'assetsExported':False,'published':False,'frozenInputsUnchanged':len(frozen),
            'seconds':time.perf_counter()-start,'peakRssBytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
            'limitations':['Triangle-centroid legality does not validate the full surface.',
                           'No independent occluding geometry; no confirmed false rejections from room RGB alone.',
                           'Nine views limit detailed inspection; all 59 original views determine votes/conflicts.']}
    write_json(out/'summary.json',output)
    print(json.dumps(output,indent=2),flush=True)


if __name__ == '__main__':
    p=argparse.ArgumentParser()
    for name in ['stage2','prepared','original-backend','windows','output']:
        p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args()
    already_existed=a.output.exists()
    try: run(a)
    except Exception as error:
        if a.output.is_dir() and not already_existed:
            failure=a.output/'failure.json'
            if not failure.exists():write_json(failure,{'error':repr(error),'trainingSteps':0,'preserved':True})
        raise