"""Add static, hash-checked portrait previews to completed local 3DGS jobs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

from portrait_preview import create, create_3d_lod


def backfill(root: Path) -> list[str]:
    updated = []
    for job_dir in root.iterdir():
        if not job_dir.is_dir() or not re.fullmatch(r"[0-9a-f]{32}", job_dir.name):
            continue
        job_path = job_dir / "job.json"
        if not job_path.is_file():
            continue
        job = json.loads(job_path.read_text(encoding="utf-8"))
        if job.get("state") != "gaussian_ready" or not {"gaussian", "view"}.issubset(job.get("assets", {})):
            continue
        preview = create(job_dir)
        lod = create_3d_lod(job_dir)
        with preview.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        manifest = {"file": preview.name, "bytes": preview.stat().st_size, "sha256": digest}
        with lod.open("rb") as source:
            lod_digest = hashlib.file_digest(source, "sha256").hexdigest()
        lod_manifest = {"file": lod.name, "bytes": lod.stat().st_size, "sha256": lod_digest}
        if job["assets"].get("preview") == manifest and job["assets"].get("preview3d") == lod_manifest:
            continue
        job["assets"]["preview"] = manifest
        job["assets"]["preview3d"] = lod_manifest
        temp = job_path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(job, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(temp, job_path)
        updated.append(job_dir.name)
    return updated


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: backfill_previews.py RECONSTRUCTION_JOB_ROOT")
    print(json.dumps({"updatedJobIds": backfill(Path(sys.argv[1]))}))
