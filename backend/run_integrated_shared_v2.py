"""Independent SELF research run; never a production worker or tablet sender."""
import argparse
import json
import time
from pathlib import Path

from reconstruction_components_v2 import prepare,load_prepared,supported_cloth,triangulated_garment,write_json


def run(args):
    start=time.perf_counter()
    if args.prepared:
        if not (args.output/"preparation.json").is_file():raise ValueError("missing_preparation")
        data=load_prepared(args.output)
    else:
        if args.output.exists():raise FileExistsError(args.output)
        args.output.mkdir(parents=True)
        data=prepare(args.source,args.output,args.fit_root,args.appearance,args.static_map,args.trust,
                     enrich_neighbours=args.enrich_local_neighbours,masks_from=args.masks_from)
        cloth,audit=supported_cloth(args.source,args.static_map,data)
        import numpy as np
        np.savez_compressed(args.output/"cloth_supported_seeds.npz",**cloth)
        write_json(args.output/"cloth-support-audit.json",audit)
        write_json(args.output/"preparation-time.json",{"seconds":time.perf_counter()-start})
    if args.prepare_only:
        print(json.dumps({"prepared":str(args.output),"train":len(data["train"]),
            "development":len(data["development"]),"seconds":time.perf_counter()-start}),flush=True)
        return
    if args.cloth_multiview:
        audit=triangulated_garment(data,args.output)
        print(json.dumps({"actualClothMultiviewSeeds":audit["acceptedSeeds"]}),flush=True)
    from reconstruction_shared_v2 import train
    train(data,args.output,args.steps,antialiased=args.antialiased)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("source",type=Path);parser.add_argument("output",type=Path)
    parser.add_argument("--fit-root",type=Path,required=True)
    parser.add_argument("--appearance",type=Path,required=True)
    parser.add_argument("--static-map",type=Path,required=True)
    parser.add_argument("--trust",type=Path,required=True)
    parser.add_argument("--steps",type=int,default=1800)
    parser.add_argument("--antialiased",action="store_true")
    parser.add_argument("--prepare-only",action="store_true")
    parser.add_argument("--prepared",action="store_true")
    parser.add_argument("--enrich-local-neighbours",action="store_true")
    parser.add_argument("--masks-from",type=Path)
    parser.add_argument("--cloth-multiview",action="store_true")
    run(parser.parse_args())
