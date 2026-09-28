"""Compare incremental SfM on the exact calibrated, targeted static graph.

This works only on a copied database and cannot publish a portrait.  The
global candidate uses the same graph in ``targeted_global/colmap.db``.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path

import pycolmap

from probe_static_alignment import best_model
from probe_static_frame_quality import quality, section_stats


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(job: Path) -> dict:
    root = job / "static_sfm_probe_stride1"
    source_db = root / "targeted_global" / "colmap.db"
    if not source_db.is_file():
        raise FileNotFoundError(source_db)
    source_hash = sha256(source_db)
    out = root / "fair_incremental_targeted_v2"
    out.mkdir(exist_ok=True)
    copied_db = out / "colmap.db"
    shutil.copy2(source_db, copied_db)
    if source_hash != sha256(copied_db):
        raise ValueError("calibrated_database_copy_mismatch")
    names = [item["name"] for item in json.loads(
        (job / "frame_manifest.audit.json").read_text(encoding="utf-8"))["frames"]]
    if len(names) != 160 or len(set(names)) != 160:
        raise ValueError("manifest_mismatch")
    started = time.perf_counter()
    sparse = out / "sparse"
    sparse.mkdir(exist_ok=True)
    candidates = pycolmap.incremental_mapping(copied_db, job / "frames", sparse)
    if not candidates:
        raise ValueError("incremental_mapping_failed")
    model = best_model(sparse)
    rows = quality(model, names)
    report = {
        "inputGraphSha256": source_hash,
        "sourceGraphUnchanged": sha256(source_db) == source_hash,
        "solverModifiedOnlyCopiedDatabase": sha256(copied_db) != source_hash,
        "globalComparison": "targeted_global on identical copied input graph",
        "registered": model.num_reg_images(),
        "staticPoints": model.num_points3D(),
        "sections": section_stats(rows),
        "perFrame": rows,
        "seconds": round(time.perf_counter() - started, 2),
        "note": "same initial estimated K/masks/features/verified graph, independently optimized camera K may differ; neither is independently calibrated",
    }
    (out / "report.json").write_text(json.dumps(report, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "perFrame"}), flush=True)
    return report


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        raise SystemExit("probe_static_fair_incremental.py JOB_DIR")
    run(Path(sys.argv[1]))
