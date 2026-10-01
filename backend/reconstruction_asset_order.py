"""Preserve point order and provenance for fixed-topology research updates.
Does not change the production editor or reinterpret SH as skin material.
"""
import numpy as np
import torch
from reconstruction_portrait_model import GaussianState


def replace_rows(original, patch, rows):
    rows=torch.as_tensor(rows,device=original.means.device,dtype=torch.long)
    n=len(original.means)
    if rows.ndim!=1 or len(rows)!=len(patch.means) or len(torch.unique(rows))!=len(rows):
        raise ValueError('replacement_rows_not_unique')
    if torch.any((rows<0)|(rows>=n)) or not torch.equal(original.parts[rows],patch.parts):
        raise ValueError('replacement_scope_or_semantics')
    return GaussianState(*(getattr(original,k).index_copy(0,rows,getattr(patch,k)) for k in GaussianState.__dataclass_fields__))


def appended_to_original(count, selected):
    selected=np.asarray(selected,np.int64)
    if selected.ndim!=1 or len(np.unique(selected))!=len(selected) or np.any((selected<0)|(selected>=count)):
        raise ValueError('invalid_fixed_topology_rows')
    keep=np.ones(count,bool);keep[selected]=False
    emitted=np.r_[np.flatnonzero(keep),selected]
    return np.argsort(emitted)


def permute_float_ply(source, target, permutation):
    """Byte-exact vertex permutation; log scales/logit alpha/SH untouched."""
    permutation=np.asarray(permutation,np.int64)
    with open(source,'rb') as stream:
        lines=[]
        while True:
            line=stream.readline()
            if not line:raise ValueError('missing_ply_header')
            lines.append(line)
            if line.strip()==b'end_header':break
        header=b''.join(lines);text=header.decode('ascii').splitlines()
        if text[:2]!=['ply','format binary_little_endian 1.0']:raise ValueError('unsupported_ply_format')
        elements=[l for l in text if l.startswith('element ')]
        if len(elements)!=1 or not elements[0].startswith('element vertex '):raise ValueError('non_vertex_ply')
        count=int(elements[0].split()[2]);props=[l.split() for l in text if l.startswith('property ')]
        if any(p[1]!='float' for p in props):raise ValueError('non_float_ply')
        raw=stream.read()
    size=4*len(props)
    if len(raw)!=count*size or len(permutation)!=count or not np.array_equal(np.sort(permutation),np.arange(count)):
        raise ValueError('invalid_vertex_permutation')
    rows=np.frombuffer(raw,dtype=np.uint8).reshape(count,size)
    from pathlib import Path
    target=Path(target)
    with target.open('xb') as stream:stream.write(header);stream.write(rows[permutation].tobytes())
    return count