"""Download a pinned official DA3 depth-only tool; no production imports."""
import argparse, hashlib, json, urllib.request, os
from pathlib import Path

def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(1048576),b""):h.update(block)
    return h.hexdigest()

def run(root):
    root=Path(root).resolve()
    spec=json.loads((root/"upstream.json").read_text())
    model=root/"model"; model.mkdir(exist_ok=False)
    revision=spec["modelCommit"]; repo=spec["model"]
    tree=json.loads(urllib.request.urlopen(
        f"https://huggingface.co/api/models/{repo}/tree/{revision}",timeout=60).read())
    by={x["path"]:x for x in tree}
    rows=[]
    for name in ["config.json","README.md","model.safetensors"]:
        path=model/name; partial=path.with_suffix(path.suffix+".partial")
        url=f"https://huggingface.co/{repo}/resolve/{revision}/{name}"
        with urllib.request.urlopen(url,timeout=120) as src,partial.open("xb") as dst:
            total=0
            while True:
                block=src.read(1048576)
                if not block:break
                dst.write(block); total+=len(block)
                if total% (32*1048576)==0:print(name,total,flush=True)
        digest=sha(partial); expected=by[name].get("lfs",{}).get("oid")
        if expected is not None and digest!=expected:raise ValueError("official_LFS_hash_mismatch")
        partial.rename(path)
        rows.append({"name":name,"bytes":total,"sha256":digest,"officialLfsSha256":expected})
    (root/"weights-lock.json").write_text(json.dumps({
        **spec,"files":rows,"license":"Apache-2.0 for DA3-BASE; official model card retained",
        "role":"depth geometry proposals; no GS head, no generated RGB"},indent=2))
    print("PINNED_WEIGHTS_READY",flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--root",required=True);run(p.parse_args().root)
