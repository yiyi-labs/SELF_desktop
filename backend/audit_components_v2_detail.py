"""Post-training audit; does not optimize, publish, or replace a frozen asset."""
import argparse
import json
from pathlib import Path

import numpy as np
import torch

from reconstruction_components_v2 import load_prepared,write_json
from reconstruction_joint_visibility import sha256_file,COMPONENTS
from reconstruction_shared_v2 import mesh_depth,make_frame,audit


def run(root,lineage_only=False):
    view=json.loads((root/"portrait.view.json").read_text());data=load_prepared(root)
    digest=sha256_file(root/"portrait.gaussian.ply")
    if digest!=view["assetSha256"]:raise ValueError("view_asset_hash_changed")
    data["reference"]=view["sourceFrame"]
    detail=None
    if not lineage_only:
        faces=data["geometry"].faces.numpy();names=data["development"]+[data["reference"]]
        data["depths"]={name:mesh_depth((data["local"][name]["mesh"],faces),data["local"][name]["F"],
            data["K"],data["rgb"][name].shape[1],data["rgb"][name].shape[0])*data["scale"] for name in names}
        params=torch.nn.ParameterDict({key:torch.nn.Parameter(torch.from_numpy(value).cuda())
            for key,value in np.load(root/"trained_parameters.npz").items()})
        detail=audit(params,data,root/"supplemental-part-audit",True,{name:make_frame(data,name,half=True) for name in names})
    sidecar=dict(np.load(root/"portrait.components.npz"))
    if str(sidecar["asset_sha256"])!=digest:raise ValueError("component_asset_hash_changed")
    count=len(sidecar["component"])
    for name,array in sidecar.items():
        if array.ndim and len(array)!=count:raise ValueError(f"component_field_length_mismatch:{name}")
    report={"assetHash":digest,"sourceHash":data["sourceHash"],"referenceFrame":data["reference"],
        "sourcePreparationHash":sha256_file(root/"preparation.json"),"count":count,"parts":{},
        "limits":["Parsing and edge-mask coverage are proxies, not independent annotated geometry truth",
            "All views are development; no claim of new-world camera certification"]}
    for i,name in enumerate(COMPONENTS):
        selected=sidecar["component"]==i;support=sidecar["support"][selected,0]
        generation=sidecar["generation"][selected,0]
        descendants=generation>0
        report["parts"][name]={"count":int(selected.sum()),"descendants":int(descendants.sum()),
            "supportMinMedianMax":np.quantile(support,[0,.5,1]).tolist() if len(support) else [],
            "descendantSupportMinMedianMax":np.quantile(support[descendants],[0,.5,1]).tolist() if descendants.any() else [],
            "bound":int((sidecar["tri_id"][selected,0]>=0).sum()),
            "sourceKinds":{str(int(kind)):int((sidecar["source_kind"][selected]==kind).sum())
                           for kind in np.unique(sidecar["source_kind"][selected])}}
    report["metrics"]=detail
    report["qualityAuditStatus"]="not_run_lineage_only" if lineage_only else "actual_gpu_rendered"
    (root/"supplemental-part-audit").mkdir(exist_ok=True)
    write_json(root/"supplemental-part-audit"/"lineage-and-quality.json",report)
    print(json.dumps({"assetHash":digest,"parts":report["parts"]}),flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("root",type=Path)
    parser.add_argument("--lineage-only",action="store_true");args=parser.parse_args();run(args.root,args.lineage_only)
