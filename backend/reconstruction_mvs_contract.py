"""Read pinned OpenMVS binary PLY with explicit view provenance, no dependency.
Only known scalar/list property encodings are accepted; truncated data fails.
"""
import struct
from pathlib import Path
import numpy as np

def read_mvs_cloud(path):
    types={'float32':('f',4),'float':('f',4),'uint8':('B',1),'uchar':('B',1),'uint32':('I',4),'int32':('i',4)}
    with Path(path).open('rb') as f:
        props=[];count=None;fmt=None
        while True:
            line=f.readline()
            if not line:raise ValueError('missing PLY header')
            words=line.decode('ascii').strip().split()
            if words[:1]==['format']:fmt=words[1]
            elif words[:2]==['element','vertex']:count=int(words[2])
            elif words[:1]==['element'] and words[1]!='vertex':raise ValueError('unsupported additional element')
            elif words[:1]==['property']:props.append(words[1:])
            elif words==['end_header']:break
        if fmt!='binary_little_endian' or count is None:raise ValueError('unsupported PLY format')
        rows=[]
        for _ in range(count):
            row={}
            for p in props:
                if p[0]=='list':
                    code,size=types[p[1]];n=struct.unpack('<'+code,f.read(size))[0];code,size=types[p[2]];row[p[3]]=list(struct.unpack('<'+code*n,f.read(size*n)))
                else:code,size=types[p[0]];row[p[1]]=struct.unpack('<'+code,f.read(size))[0]
            rows.append(row)
        if f.read(1):raise ValueError('unexpected trailing bytes')
    return {'xyz':np.array([[r[k] for k in ('x','y','z')] for r in rows]),'normal':np.array([[r[k] for k in ('nx','ny','nz')] for r in rows]),'rgb':np.array([[r[k] for k in ('red','green','blue')] for r in rows])/255,'views':[r['view_indices'] for r in rows],'weights':[r['view_weights'] for r in rows]}

def explicit_retirement_mask(point_uids,source_ids,source_kinds,source_id,uids):
    """Stable audited identities only. A source family is never a deletion set."""
    point_uids=np.asarray(point_uids);uids=np.asarray(uids,dtype=np.int64)
    if not len(uids) or len(np.unique(uids))!=len(uids):raise ValueError('unique_nonempty_retirement_UIDs_required')
    result=np.isin(point_uids,uids)
    if int(result.sum())!=len(uids):raise ValueError('missing_or_duplicated_point_UID')
    if not np.all((np.asarray(source_ids)[result]==source_id)&(np.asarray(source_kinds)[result]==0)):raise ValueError('source_namespace_mismatch')
    return result
