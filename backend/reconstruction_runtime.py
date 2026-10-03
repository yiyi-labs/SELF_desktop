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


def training_profile_options(profile):
    local_steps=int(profile.get('localSteps',900));room_steps=int(profile.get('roomSteps',300))
    hair_steps=profile.get('hairCompositeSteps',0)
    skin_steps=profile.get('skinCompositingSteps',0)
    observed_face=profile.get('observedFaceDomain',False)
    if not isinstance(observed_face,bool):
        raise ValueError('test_observed_face_domain_requires_boolean')
    if observed_face and profile.get('executionAdapter')!='native-fullframe':
        raise ValueError('test_observed_face_domain_requires_native_adapter')
    if not 1<=local_steps<=900 or not 1<=room_steps<=600:
        raise ValueError('test_live_training_budget_outside_contract')
    if isinstance(hair_steps,bool) or not isinstance(hair_steps,int) or not 0<=hair_steps<=240:
        raise ValueError('test_hair_composite_budget_outside_contract')
    if isinstance(skin_steps,bool) or not isinstance(skin_steps,int) or not 0<=skin_steps<=240:
        raise ValueError('test_skin_compositing_budget_outside_contract')
    dense=profile.get('denseSurfaces') is True
    shared=profile.get('sharedRoomSurface') is True
    if hair_steps and not dense:raise ValueError('test_hair_composite_requires_dense_surfaces')
    if shared and not dense:raise ValueError('test_shared_room_requires_dense_surfaces')
    if skin_steps and not (dense and observed_face):raise ValueError('test_skin_compositing_requires_observed_dense_face')
    # These stages alter the training contract, not the USB/asset schema.
    # No truthy strings, implicit opt-ins, or research body experiment can
    # silently enter the live profile.
    additions={key:profile.get(key,False) for key in
               ('opaquePerson','opaqueBody','surfaceFootprint','roomWindowRecovery')}
    for key,value in additions.items():
        if not isinstance(value,bool):raise ValueError('test_'+key+'_requires_boolean')
        if value and profile.get('executionAdapter')!='native-fullframe':
            raise ValueError('test_'+key+'_requires_native_adapter')
    if additions['opaqueBody']:
        raise ValueError('test_opaque_body_is_research_only')
    if additions['opaquePerson'] and not observed_face:
        raise ValueError('test_opaque_person_requires_observed_face')
    if additions['surfaceFootprint'] and not observed_face:
        raise ValueError('test_surface_footprint_requires_observed_face')
    if additions['roomWindowRecovery'] and not (dense and shared):
        raise ValueError('test_room_window_recovery_requires_shared_dense_surfaces')
    return {'localSteps':local_steps,'roomSteps':room_steps,'hairCompositeSteps':hair_steps,
            'skinCompositingSteps':skin_steps,
            'denseSurfaces':dense,'sharedRoomSurface':shared,'surfaceRefine':profile.get('surfaceRefine') is True,
            'observedFaceDomain':observed_face,**additions}


def pipeline_entry(profile,backend):
    """Allow only the fixed local test adapter, with explicit source identity."""
    mode=profile.get("executionAdapter","legacy")
    if mode=="legacy":return backend/"reconstruction_portrait_pipeline.py",300
    if mode!="native-fullframe" or profile.get("algorithmVersion")!=NATIVE_VERSION:
        raise ValueError("unknown_test_execution_adapter")
    if profile.get("implementationSha256"):
        from reconstruction_code_identity import source_identity
        if source_identity(backend)["implementationSha256"]!=profile["implementationSha256"]:
            raise ValueError("test_source_hash_changed:dependency_closure")
        return backend/"reconstruction_live_fullframe.py",0
    required=("reconstruction_live_fullframe.py","reconstruction_portrait_pipeline.py",
              "reconstruction_portrait_model.py","appearance_direction_contract.py")
    hashes=profile.get("entrySourceHashes",{})
    if set(hashes)!=set(required):raise ValueError("incomplete_test_source_contract")
    for name in required:
        if hashlib.sha256((backend/name).read_bytes()).hexdigest()!=hashes[name]:
            raise ValueError("test_source_hash_changed:"+name)
    return backend/required[0],0


def engine_profile(root,backend=None):
    file=Path(root)/"engine-profile.json"
    if not file.is_file():return {"engine":LEGACY}
    value=json.loads(file.read_text(encoding="utf-8-sig"))
    if value.get("engine") not in (LEGACY,PORTRAIT_TEST):raise ValueError("unknown_reconstruction_engine")
    if value.get("engine")==PORTRAIT_TEST and value.get("userTestingAuthorized") is not True:
        raise ValueError("test_engine_requires_explicit_authorization")
    if value.get("engine")==PORTRAIT_TEST:
        pipeline_entry(value,Path(backend or Path(__file__).resolve().parent))
        training_profile_options(value)
    return value


def worker_identity_status(root,loaded_identity,backend=None):
    """A heartbeat cannot certify files different from this worker's imports.

    This is a cheap source/profile check, not a GPU smoke test. Once imports
    differ, restart is required; changing the profile cannot bless old code.
    """
    from reconstruction_code_identity import source_identity
    backend=Path(backend or Path(__file__).resolve().parent)
    result={"sourceIdentityVerified":False,
            "loadedImplementationSha256":loaded_identity.get("implementationSha256")}
    try:
        current=source_identity(backend)
        result["currentImplementationSha256"]=current["implementationSha256"]
        if current["implementationSha256"]!=loaded_identity.get("implementationSha256"):
            result["reason"]="worker_source_changed_restart_required"
            return result
        profile=engine_profile(root,backend)
        result.update(sourceIdentityVerified=True,engine=profile["engine"],
            algorithmVersion=profile.get("algorithmVersion","legacy"),
            executionAdapter=profile.get("executionAdapter","legacy"),
            profileImplementationSha256=profile.get("implementationSha256"),
            executionProfileSha256=hashlib.sha256(json.dumps(training_profile_options(profile)
                if profile['engine']==PORTRAIT_TEST else {'engine':LEGACY},sort_keys=True).encode()).hexdigest())
    except (OSError,ValueError,SyntaxError,KeyError) as error:
        # Only known short contract labels, never captured paths/profile data.
        label=str(error) if isinstance(error,ValueError) else type(error).__name__
        result["reason"]=(label if label.startswith(("test_","unknown_","incomplete_"))
                          else "worker_identity_unavailable:"+type(error).__name__)[:120]
    return result


def observed_face_execution_receipt(output,report):
    """Validate the actual supervision/prior identity, not the requested flag.

    Mask hashes are producer records, not independent segmentation truth. The
    original JSON and prior bytes must agree before the worker may publish.
    """
    value=report.get('observedFaceDomain')
    if value is None:return {'applied':False}
    if not isinstance(value,dict):raise ValueError('test_observed_face_receipt_invalid')
    output=Path(output);saved=output/'observed-face-domain.json'
    if not saved.is_file() or json.loads(saved.read_text())!=value:
        raise ValueError('test_observed_face_receipt_missing_or_changed')
    hashes=value.get('maskHashes')
    valid_hash=lambda x:isinstance(x,str) and len(x)==64 and all(c in '0123456789abcdef' for c in x)
    if (not isinstance(hashes,dict) or not hashes
            or any(not isinstance(k,str) or not k or not valid_hash(v) for k,v in hashes.items())
            or not valid_hash(value.get('appearanceSha256'))
            or not valid_hash(value.get('oldAppearanceSha256'))
            or value.get('heldoutColoursUsed') is not False):
        raise ValueError('test_observed_face_identity_invalid')
    prior=output/'observed-face-initial-appearance.npz'
    if not prior.is_file() or hashlib.sha256(prior.read_bytes()).hexdigest()!=value['appearanceSha256']:
        raise ValueError('test_observed_face_prior_missing_or_changed')
    if report.get('appearanceHash')!=value['appearanceSha256']:
        raise ValueError('test_observed_face_training_prior_mismatch')
    return {'applied':True,'method':value.get('method'),'maskHashes':hashes,
            'maskManifestSha256':hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest(),
            'appearanceSha256':value['appearanceSha256'],'oldAppearanceSha256':value['oldAppearanceSha256'],
            'surfaceCount':value.get('surfaceCount'),'heldoutColoursUsed':False,
            'receiptSha256':hashlib.sha256(saved.read_bytes()).hexdigest(),
            'maskEvidence':'recorded_semantic_observations_not_independent_geometry_truth'}


def training_execution_receipt(output,report):
    """Report actual initialization/training without inventing missing counts."""
    output=Path(output)
    initialization={"status":"unrecorded"}
    imported=output/"portrait-import.json"
    if imported.is_file():
        source=json.loads(imported.read_text(encoding="utf-8"))
        initialization={"status":"recorded","head":source.get("pointCount"),
                        "surface":source.get("surfaceCount"),"hair":source.get("hairCount"),
                        "environment":source.get("environmentCount"),
                        "bodyMotion":source.get("bodyMotion")}
    initial_checkpoint=output/"local-init.pt"
    if initial_checkpoint.is_file():
        from reconstruction_checkpoint import load_checkpoint,file_sha256 as checkpoint_hash
        import torch
        state=load_checkpoint(initial_checkpoint,device="cpu")["model"]
        # Keep distinct schemas: portrait role 1 means fine surface detail,
        # whereas scene component 1 means skin; never relabel it as glasses.
        for field,label in (("environment_parts","environmentPartCounts"),
                            ("portrait.role","portraitRoleCounts")):
            if field in state:
                values,counts=torch.unique(state[field],return_counts=True)
                initialization[label]={str(int(k)):int(v) for k,v in zip(values,counts)}
        initialization["checkpointSha256"]=checkpoint_hash(initial_checkpoint)
    parts=output/"portrait.components.npz"
    final_groups=None
    if parts.is_file():
        import numpy as np
        with np.load(parts,allow_pickle=False) as provenance:
            if "component" in provenance:
                values,counts=np.unique(provenance["component"],return_counts=True)
                final_groups={str(int(k)):int(v) for k,v in zip(values,counts)}
    stages=[]
    for s in report['trainings']:
        row={'name':s['stage'],'completedSteps':s['steps'],'seconds':s.get('seconds'),'densityEvents':s.get('densityEvents',[])}
        for key in ('status','geometryChanged','modelChanged','allComponentsRendered'):
            if key in s:row[key]=s[key]
        if 'qualifiedViews' in s:row['qualifiedViewCount']=len(s['qualifiedViews'])
        stages.append(row)
    hair_rows=[s for s in report['trainings'] if s['stage']=='hair-composite']
    requested_hair=report.get('hairCompositeSteps')
    actual_hair=sum(s['steps'] for s in hair_rows) if hair_rows else 0 if requested_hair==0 else None
    dense=report.get('denseSurfaces') or {};room=dense.get('components',{}).get('room')
    return {"initialization":initialization,"finalPartCounts":final_groups,
            "pointCount":report["pointCount"],
            "stages":stages,"hairCompositeRequestedSteps":requested_hair,
            "hairCompositeCompletedSteps":actual_hair,
            "sharedRoomSurfaceApplied":bool(room.get('typedSupport')) if room is not None else None,
            "observedFaceDomain":observed_face_execution_receipt(output,report),
            "surfaceRefine":report.get("surfaceRefine"),
            "jointSteps":report.get("jointSteps"),"resumeKind":report.get("resumeKind")}


def repair_execution_receipt(output,report,options=None):
    """Bind opt-in repair claims to the files that actually ran.

    A zero-change or rejected candidate remains a recorded execution, never a
    quality pass. Original JSON/NPZ files are retained with the checkpoint.
    """
    output=Path(output)
    def digest(file):return hashlib.sha256(Path(file).read_bytes()).hexdigest()
    actual={'opaquePerson':report.get('opaquePerson',False),
            'opaqueBody':report.get('opaqueBody',False),
            'surfaceFootprint':report.get('surfaceFootprint') is not None,
            'roomWindowRecovery':report.get('roomWindowRecovery',False)}
    if any(not isinstance(actual[k],bool) for k in ('opaquePerson','opaqueBody','roomWindowRecovery')):
        raise ValueError('test_repair_report_flags_invalid')
    if options is not None:
        for key,value in actual.items():
            if value!=options[key]:raise ValueError('test_repair_requested_actual_mismatch:'+key)
    if actual['opaqueBody']:raise ValueError('test_opaque_body_is_research_only')
    result={key:{'applied':value} for key,value in actual.items()}
    if actual['opaquePerson']:
        file=output/'opaque-interiors.json'
        if not file.is_file() or digest(file)!=report.get('opaqueInteriorsReceiptSha256'):
            raise ValueError('test_opaque_interiors_receipt_missing_or_changed')
        masks=json.loads(file.read_text())
        if not isinstance(masks,dict) or not masks:
            raise ValueError('test_opaque_interiors_receipt_empty')
        result['opaquePerson'].update(scope='head_only',receiptSha256=digest(file),
            observationCount=len(masks),qualityPassed=False)
    if actual['surfaceFootprint']:
        value=report['surfaceFootprint'];file=output/'surface-footprint.json'
        if not isinstance(value,dict) or not file.is_file() or json.loads(file.read_text())!=value:
            raise ValueError('test_surface_footprint_receipt_missing_or_changed')
        domain=report.get('observedFaceDomain') or {}
        if digest(file)!=domain.get('surfaceFootprintSha256'):
            raise ValueError('test_surface_footprint_prior_receipt_mismatch')
        diagnostics=output/'surface-footprint-diagnostics.npz'
        if not diagnostics.is_file():raise ValueError('test_surface_footprint_diagnostics_missing')
        if value.get('sourceSha256')!=report.get('sourceSha256') or value.get('priorStage')!='fresh_initialization':
            raise ValueError('test_surface_footprint_source_or_stage_mismatch')
        result['surfaceFootprint'].update(receiptSha256=digest(file),
            diagnosticsSha256=digest(diagnostics),changedCount=value.get('changedCount'),
            normalVariancePreserved=value.get('normalVariancePreserved'),qualityPassed=False)
    if actual['roomWindowRecovery']:
        value=report.get('roomWindowRecoveryReceipt');file=output/'room-window-recovery.json'
        if not isinstance(value,dict) or not file.is_file() or json.loads(file.read_text())!=value:
            raise ValueError('test_room_window_recovery_receipt_missing_or_changed')
        dense=report.get('denseSurfaces') or {}
        result_value=value.get('result')
        if not isinstance(result_value,dict) or result_value!=dense.get('roomWindowRecovery'):
            raise ValueError('test_room_window_recovery_dense_receipt_mismatch')
        manifest=Path(value.get('manifestPath',''))
        if not manifest.is_file() or digest(manifest)!=value.get('manifestSha256'):
            raise ValueError('test_room_window_recovery_manifest_changed')
        manifest_value=json.loads(manifest.read_text())
        if (manifest_value.get('sourceSha256')!=report.get('sourceSha256') or
                manifest_value.get('roomWindowRecovery')!=result_value):
            raise ValueError('test_room_window_recovery_manifest_identity')
        result['roomWindowRecovery'].update(receiptSha256=digest(file),
            manifestSha256=value['manifestSha256'],status=result_value.get('status'),
            addedCount=result_value.get('addedCount'),
            originalPrefixBitwiseUnchanged=result_value.get('originalPrefixBitwiseUnchanged'),qualityPassed=False)
    return result


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


def release_preparation_cuda_cache():
    """Preparation returns disk paths; release only unreferenced cached memory.

    The training child has its own allocator. Its peak is not the complete
    parent/child device peak, so retain the parent accounting separately.
    """
    import gc
    import torch
    if not torch.cuda.is_initialized():return {"cudaInitialized":False}
    result={"cudaInitialized":True,"scope":"preparation_parent_since_last_peak_reset",
        "allocatedPeakMiB":torch.cuda.max_memory_allocated()/2**20,
        "reservedPeakMiB":torch.cuda.max_memory_reserved()/2**20,
        "allocatedBeforeReleaseMiB":torch.cuda.memory_allocated()/2**20,
        "reservedBeforeReleaseMiB":torch.cuda.memory_reserved()/2**20}
    gc.collect();torch.cuda.empty_cache()
    result.update(allocatedAfterReleaseMiB=torch.cuda.memory_allocated()/2**20,
                  reservedAfterReleaseMiB=torch.cuda.memory_reserved()/2**20)
    return result


def retain_local_fit_state(prepared,state_dir):
    """Keep fitted parameters and optimizer after original pixels expire."""
    prepared=Path(prepared);destination=Path(state_dir)/"local-fit"
    files=[prepared/name for name in ("local-fit-init.pt","local-fit-mid.pt","local-fit-state.pt",
        "local_geometry.npz","preparation.json","automatic-prepare-audit.json") if (prepared/name).is_file()]
    if not (prepared/"local-fit-state.pt").is_file():return {"status":"legacy_fit_optimizer_unavailable"}
    destination.mkdir()
    hashes={}
    for file in files:
        target=destination/file.name;shutil.copyfile(file,target)
        original=hashlib.sha256(file.read_bytes()).hexdigest()
        if hashlib.sha256(target.read_bytes()).hexdigest()!=original:raise ValueError('local_fit_retention_hash_mismatch')
        hashes[file.name]=original
    return {"status":"fit_state_retained","relativeDirectory":"local-fit","sha256":hashes,
        "originalManifestPreserved":True,"originalPixelsRetained":False,
        "resumeBoundary":"landmark_fit_and_parameters; image_training_needs_original_images"}


def reconstruct_test(path,job,profile,update,extract_frames,prepare_faces,command,file_sha256):
    backend=Path(__file__).resolve().parent
    options=training_profile_options(profile)
    prepared=verified_preparation(profile,job["sha256"],backend)
    quality={"algorithm":PORTRAIT_TEST,"sourceSha256":job["sha256"],"userPreviewAuthorized":True,
             "releaseApproved":False,"fidelityGatePassed":False,"observationsCacheReused":prepared is not None}
    if prepared is None:
        update(path,"running",29,"正在读懂这次拍摄",algorithm=PORTRAIT_TEST)
        frames=extract_frames(path);faces=prepare_faces(path,frames)
        update(path,"running",40,"正在寻找你的立体轮廓")
        from reconstruction_live_prepare import prepare_capture
        prepared=prepare_capture(path,path/"portrait-preparation",frames,faces)
        quality['preparationParentGpu']=release_preparation_cuda_cache()
    update(path,"running",61,"正在汇聚这颗星辰",algorithm=PORTRAIT_TEST)
    output=path/"portrait-training"
    entry,joint_steps=pipeline_entry(profile,backend)
    local_steps=options['localSteps'];room_steps=options['roomSteps'];hair_steps=options['hairCompositeSteps']
    skin_steps=options['skinCompositingSteps']
    argv=[sys.executable,str(entry),str(prepared),str(output),"--soft","--local-steps",str(local_steps),
          "--room-steps",str(room_steps),"--joint-steps",str(joint_steps)]
    if profile.get("surfaceRefine") is True:argv.append("--surface-refine")
    if profile.get("denseSurfaces") is True:argv.append("--dense-surfaces")
    if options['sharedRoomSurface']:argv.append('--shared-room-surface')
    if hair_steps:argv.extend(('--hair-steps',str(hair_steps)))
    if skin_steps:argv.extend(('--skin-steps',str(skin_steps)))
    if options['observedFaceDomain']:argv.append('--observed-face-domain')
    for key,flag in (('opaquePerson','--opaque-person'),('surfaceFootprint','--surface-footprint'),
                     ('roomWindowRecovery','--room-window-recovery')):
        if options[key]:argv.append(flag)
    def progress(row):
        stage=row.get("stage");step=row.get("step")
        if stage=="surface":
            complete=row.get('completedStages');total=row.get('totalStages')
            if isinstance(complete,int) and isinstance(total,int) and 0<=complete<=total and total>0:
                update(path,"running",61+round(5*complete/total),"正在描绘这片光影",algorithm=PORTRAIT_TEST,
                    stage={"name":stage,"completedSteps":complete,"totalSteps":total})
            return
        if stage=='hair-composite':
            if hair_steps and isinstance(step,int) and not isinstance(step,bool) and 0<=step<=hair_steps:
                update(path,'running',90+round(2*step/hair_steps),'正在汇聚这颗星辰',algorithm=PORTRAIT_TEST,
                    stage={'name':stage,'completedSteps':step,'totalSteps':hair_steps})
            return
        if stage=='skin-compositing':
            if skin_steps and isinstance(step,int) and not isinstance(step,bool) and 0<=step<=skin_steps:
                update(path,'running',92+round(2*step/skin_steps),'正在汇聚这颗星辰',algorithm=PORTRAIT_TEST,
                    stage={'name':stage,'completedSteps':step,'totalSteps':skin_steps})
            return
        if stage not in ("local","T3") or not isinstance(step,int):return
        percent=66+round(12*step/local_steps) if stage=="local" else 78+round(12*step/room_steps)
        update(path,"running",min(90,percent),"正在汇聚这颗星辰",algorithm=PORTRAIT_TEST,
               stage={"name":stage,"completedSteps":step,"totalSteps":local_steps if stage=="local" else room_steps})
    command(argv,7200,cwd=backend,diagnostic_file=path/"portrait-test-training.log",progress=progress)
    report=json.loads((output/"report.json").read_text())
    if report["sourceSha256"]!=job["sha256"]:raise ValueError("test_result_source_mismatch")
    if profile.get("executionAdapter")=="native-fullframe" and report["engineVersion"]!=NATIVE_VERSION:
        raise ValueError("test_result_algorithm_mismatch")
    if options['observedFaceDomain'] != (report.get('observedFaceDomain') is not None):
        raise ValueError('test_observed_face_requested_actual_mismatch')
    if options['skinCompositingSteps']!=report.get('skinCompositingSteps',0):
        raise ValueError('test_skin_compositing_requested_actual_mismatch')
    if options['skinCompositingSteps']:
        receipts=[s for s in report['trainings'] if s['stage']=='skin-compositing']
        if len(receipts)!=1 or receipts[0]['steps'] not in (0,options['skinCompositingSteps']):
            raise ValueError('test_skin_compositing_receipt_missing')
        saved=output/'skin-compositing-training.json'
        if not saved.is_file() or json.loads(saved.read_text())!=receipts[0]:
            raise ValueError('test_skin_compositing_receipt_changed')
    # Validate before copying any candidate to the transport's asset paths.
    observed_face_execution_receipt(output,report)
    repair_receipt=repair_execution_receipt(output,report,options)
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
    audit["implementation"]=report.get("implementation")
    audit["surfaceStage"]=report.get("surfaceStage")
    audit["denseSurfaces"]=report.get("denseSurfaces")
    audit["executionReceipt"]=training_execution_receipt(output,report)
    audit["executionReceipt"]['repairs']=repair_receipt
    audit["preparationParentGpu"]=quality.get('preparationParentGpu')
    # Keep recoverable learned parameters/Adam/RNG with the result, while the
    # existing cleanup still deletes the recording and all decoded pixels.
    state_dir=path/"portrait-state";state_dir.mkdir()
    for file in output.glob("*.pt"):shutil.copyfile(file,state_dir/file.name)
    for filename in ("config.json","report.json","portrait-import.json",
                       "observed-face-domain.json","observed-face-initial-appearance.npz","skin-compositing-training.json",
                       "opaque-interiors.json","surface-footprint.json","surface-footprint-diagnostics.npz",
                       "room-window-recovery.json"):
        if (output/filename).is_file():shutil.copyfile(output/filename,state_dir/filename)
    audit['localFitRecovery']=retain_local_fit_state(prepared,state_dir)
    if report.get('denseSurfaces'):
        from reconstruction_surface_recovery import retain_runtime_surface_initialization
        audit['surfaceRecovery']=retain_runtime_surface_initialization(output,state_dir,report)
    audit["stateFiles"]={f.name:file_sha256(f) for f in state_dir.iterdir() if f.is_file()}
    (path/"portrait.algorithm.json").write_text(json.dumps(audit,indent=2),encoding="utf-8")
    quality.update(engineVersion=report["engineVersion"],assetSha256=report["plySha256"],
        seconds=report["seconds"],allocatedPeakMiB=report["allocatedPeakMiB"],
        reservedPeakMiB=report["reservedPeakMiB"],pointCount=report["pointCount"],
        steps={s["stage"]:s["steps"] for s in report["trainings"]},
        implementationSha256=report.get("implementation",{}).get("implementationSha256"),
        gitCommit=report.get("implementation",{}).get("gitCommit"),
        executionReceipt=audit["executionReceipt"],
        remainingLimitations=report["limitations"])
    return manifests,quality
