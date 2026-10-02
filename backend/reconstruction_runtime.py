"""Explicit test-engine routing on the unchanged reconstruction protocol."""
import json
import hashlib
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

LEGACY="gsplat-colmap"
PORTRAIT_TEST="portrait-first-soft-surface-test"
NATIVE_VERSION="portrait-native-fullframe-20261002-research"


def pipeline_entry(profile,backend):
    """Allow only the fixed local test adapter, with explicit source identity."""
    mode=profile.get("executionAdapter","legacy")
    if mode=="legacy":return backend/"reconstruction_portrait_pipeline.py",300
    if mode!="native-fullframe" or profile.get("algorithmVersion")!=NATIVE_VERSION:
        raise ValueError("unknown_test_execution_adapter")
    required=("reconstruction_live_fullframe.py","reconstruction_portrait_pipeline.py",
              "reconstruction_portrait_model.py","appearance_direction_contract.py")
    hashes=profile.get("entrySourceHashes",{})
    if set(hashes)!=set(required):raise ValueError("incomplete_test_source_contract")
    for name in required:
        if hashlib.sha256((backend/name).read_bytes()).hexdigest()!=hashes[name]:
            raise ValueError("test_source_hash_changed:"+name)
    return backend/required[0],0


def engine_profile(root):
    file=Path(root)/"engine-profile.json"
    if not file.is_file():return {"engine":LEGACY}
    value=json.loads(file.read_text(encoding="utf-8-sig"))
    if value.get("engine") not in (LEGACY,PORTRAIT_TEST):raise ValueError("unknown_reconstruction_engine")
    if value.get("engine")==PORTRAIT_TEST and value.get("userTestingAuthorized") is not True:
        raise ValueError("test_engine_requires_explicit_authorization")
    if value.get("engine")==PORTRAIT_TEST:
        pipeline_entry(value,Path(__file__).resolve().parent)
    return value


def verified_preparation(profile,source_hash,backend):
    """A same-capture observation cache is reusable, never cross-person data."""
    directory=profile.get("preparedCache")
    if not directory:return None
    path=(backend/str(directory)).resolve()
    private=(backend/".sources").resolve()
    if not path.is_relative_to(private):raise ValueError("prepared_cache_outside_private_workspace")
    file=path/"preparation.json"
    if not file.is_file():return None
    metadata=json.loads(file.read_text(encoding="utf-8"))
    if metadata["sourceHash"]!=source_hash:return None
    # load_prepared performs the source, colour checkpoint and model checks.
    return path


def reconstruct_test(path,job,profile,update,extract_frames,prepare_faces,command,file_sha256):
    backend=Path(__file__).resolve().parent
    prepared=verified_preparation(profile,job["sha256"],backend)
    quality={"algorithm":PORTRAIT_TEST,"sourceSha256":job["sha256"],"userPreviewAuthorized":True,
             "releaseApproved":False,"fidelityGatePassed":False,"observationsCacheReused":prepared is not None}
    if prepared is None:
        update(path,"running",29,"正在读懂这次拍摄",algorithm=PORTRAIT_TEST)
        frames=extract_frames(path);faces=prepare_faces(path,frames)
        update(path,"running",40,"正在寻找你的立体轮廓")
        from reconstruction_live_prepare import prepare_capture
        prepared=prepare_capture(path,path/"portrait-preparation",frames,faces)
    update(path,"running",61,"正在汇聚这颗星辰",algorithm=PORTRAIT_TEST)
    output=path/"portrait-training"
    entry,joint_steps=pipeline_entry(profile,backend)
    command([sys.executable,str(entry),str(prepared),str(output),
             "--soft","--local-steps","900","--room-steps","300","--joint-steps",str(joint_steps)],7200,
             cwd=backend,diagnostic_file=path/"portrait-test-training.log")
    report=json.loads((output/"report.json").read_text())
    if report["sourceSha256"]!=job["sha256"]:raise ValueError("test_result_source_mismatch")
    if profile.get("executionAdapter")=="native-fullframe" and report["engineVersion"]!=NATIVE_VERSION:
        raise ValueError("test_result_algorithm_mismatch")
    manifests={}
    for kind,filename in (("gaussian","portrait.gaussian.ply"),("view","portrait.view.json")):
        src=output/filename;target=path/filename
        shutil.copyfile(src,target)
        manifests[kind]={"file":filename,"bytes":target.stat().st_size,"sha256":file_sha256(target)}
    if manifests["gaussian"]["sha256"]!=report["plySha256"]:raise ValueError("test_result_asset_hash_changed")
    # Retain source/component linkage with the normal asset lifetime. Source
    # video and temporary frames are removed by the existing worker cleanup.
    shutil.copyfile(output/"portrait.components.npz",path/"portrait.provenance.npz")
    audit={"algorithm":PORTRAIT_TEST,"sourceSha256":job["sha256"],
        "assetSha256":report["plySha256"],"observationsCacheReused":quality["observationsCacheReused"],
        "engineVersion":report["engineVersion"],"steps":report["trainings"],
        "sourceFiles":report["sourceFiles"],"seconds":report["seconds"],
        "allocatedPeakMiB":report["allocatedPeakMiB"],"reservedPeakMiB":report["reservedPeakMiB"],
        "releaseApproved":False,"userPreviewAuthorized":True}
    (path/"portrait.algorithm.json").write_text(json.dumps(audit,indent=2),encoding="utf-8")
    quality.update(engineVersion=report["engineVersion"],assetSha256=report["plySha256"],
        seconds=report["seconds"],allocatedPeakMiB=report["allocatedPeakMiB"],
        reservedPeakMiB=report["reservedPeakMiB"],pointCount=report["pointCount"],
        steps={s["stage"]:s["steps"] for s in report["trainings"]},
        remainingLimitations=report["limitations"])
    return manifests,quality
