"""Candidate-only component replacement with complete-scene rollback checks.
No publishing path. Projected centres or point counts never certify coverage.
"""
from dataclasses import dataclass
import copy
import numpy as np

@dataclass(frozen=True)
class PatchLimits:
    alpha_loss: float = .02
    missing_fraction_increase: float = .005
    rgb_regression: float = .003
    structure_regression: float = .003
    foreground_contribution_increase: float = .005


def compare_patch_views(before, after, limits=PatchLimits()):
    """Fixed masks, native full-scene render, per-view gates. No pooled mean pass.

    Both mappings contain exact per-pixel arrays, not summaries over covered
    pixels. Unknown observations must already be excluded in the fixed masks.
    This numerical screen is NOT a final geometry/visual release decision.
    """
    if set(before) != set(after) or not before:
        raise ValueError('same_nonempty_observation_set_required')
    failures=[]; rows={}
    for name,b in before.items():
        a=after[name]
        for key in ('alpha','rgb','mask','target','foreground'):
            if a[key].shape != b[key].shape:raise ValueError('canvas_changed:'+key)
        if not np.array_equal(a['mask'],b['mask']) or not np.array_equal(a['target'],b['target']):
            raise ValueError('fixed_supervision_changed')
        mask=b['mask'].astype(bool)
        if not mask.any():raise ValueError('empty_fixed_patch')
        if not all(np.isfinite(v[k]).all() for v in (a,b) for k in ('rgb','alpha','foreground')):
            raise ValueError('nonfinite_render')
        mean=lambda v:float(v[mask].mean())
        row={}
        for tag,v in [('before',b),('after',a)]:
            rgb_error=np.abs(v['rgb']-v['target']).mean(-1)
            row[tag]=dict(alpha=mean(v['alpha']),missing=mean((v['alpha']<.8).astype(float)),rgb=mean(rgb_error),foreground=mean(v['foreground']))
            edges=[]
            for axis in (0,1):
                ma=[slice(None)]*2;mb=ma.copy();ma[axis]=slice(1,None);mb[axis]=slice(None,-1)
                good=mask[tuple(ma)]&mask[tuple(mb)]
                err=np.abs(np.diff(v['rgb'],axis=axis)-np.diff(v['target'],axis=axis)).mean(-1)
                if good.any():edges.append(float(err[good].mean()))
            row[tag]['structure']=float(np.mean(edges)) if edges else 0.
        x,y=row['before'],row['after'];bad=[]
        if y['alpha']<x['alpha']-limits.alpha_loss:bad.append('lost_alpha')
        if y['missing']>x['missing']+limits.missing_fraction_increase:bad.append('lost_coverage')
        if y['rgb']>x['rgb']+limits.rgb_regression:bad.append('rgb_regression')
        if y['structure']>x['structure']+limits.structure_regression:bad.append('structure_regression')
        if y['foreground']>x['foreground']+limits.foreground_contribution_increase:bad.append('wrong_foreground')
        row['failures']=bad;rows[name]=row;failures.extend(name+':'+s for s in bad)
    return dict(passed=not failures,failures=failures,views=rows,releaseQualityPassed=False)


class PatchTransaction:
    """CPU identity contract + caller's full checkpoint; no automatic fallback.

    The caller must save model/Adam/strategy/RNG/sampler before constructing a
    trial representation. Failed trials restore all of these, not just RGB.
    Point fields remain exact outside the explicitly retired parent indices.
    """
    def __init__(self, old_arrays, retired, new_arrays):
        self.original={k:np.array(v,copy=True) for k,v in old_arrays.items()}
        self.retired=np.asarray(retired,dtype=np.int64)
        n=len(self.original['uid'])
        if len(np.unique(self.retired))!=len(self.retired) or np.any(self.retired<0) or np.any(self.retired>=n):
            raise ValueError('invalid_retired_identity')
        if set(new_arrays)!=set(self.original):raise ValueError('point_contract_changed')
        keep=np.ones(n,bool);keep[self.retired]=False;self.keep=keep
        for label,arr in [('old',self.original),('new',new_arrays)]:
            count=len(arr['uid'])
            if any(v.ndim==0 or len(v)!=count for v in arr.values()):raise ValueError('point_field_length:'+label)
            if len(np.unique(arr['uid']))!=count:raise ValueError('duplicate_source_uid:'+label)
        if np.intersect1d(self.original['uid'][keep],new_arrays['uid']).size:raise ValueError('source_uid_collision')
        self.trial={k:np.concatenate((v[keep],new_arrays[k]),axis=0) for k,v in self.original.items()}
        self.decision=None
    def decide(self, screen, *, geometry_supported):
        self.decision=bool(screen['passed'] and geometry_supported)
        # Unknown/failed geometry cannot be accepted by good-looking colours.
        return {k:v.copy() for k,v in (self.trial if self.decision else self.original).items()}
