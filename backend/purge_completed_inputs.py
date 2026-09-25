"""Audit and optionally remove legacy PC captures after reconstruction.

The live worker now removes inputs itself. This one-time migration operates only
on terminal tasks in the fixed, ignored SELF task directory. It leaves the
published model assets and job record in place.
"""

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE / ".data" / "reconstruction"
JOB_ID = re.compile(r"[a-f0-9]{32}")


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as source:
        for piece in iter(lambda: source.read(1024 * 1024), b""):
            value.update(piece)
    return value.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if ROOT.is_symlink() or not ROOT.is_dir():
        raise SystemExit("fixed SELF task directory is unavailable or redirected")
    root = ROOT.resolve(strict=True)
    summary = {"mode": "apply" if args.apply else "dry_run",
               "readyChecked": 0, "failedChecked": 0,
               "filesToRemove": 0, "bytesToRemove": 0, "blocked": 0}
    for job in sorted(root.iterdir()):
        if not JOB_ID.fullmatch(job.name) or not job.is_dir():
            continue
        if job.is_symlink() or job.resolve(strict=True).parent != root:
            raise RuntimeError("job path escapes fixed SELF task directory")
        manifest_path = job / "job.json"
        if not manifest_path.is_file():
            continue
        record = json.loads(manifest_path.read_text(encoding="utf-8"))
        state = record.get("state")
        if state not in {"gaussian_ready", "complete", "failed"}:
            continue
        keep = {"job.json", "cancel.requested"}
        if state in {"gaussian_ready", "complete"}:
            assets = record.get("assets", {})
            if not isinstance(assets, dict) or not assets:
                summary["blocked"] += 1
                continue
            valid = True
            for asset in assets.values():
                name = asset.get("file", "")
                if not isinstance(name, str) or Path(name).name != name:
                    valid = False
                    break
                file = job / name
                if (file.is_symlink() or not file.is_file() or
                        file.stat().st_size != asset.get("bytes") or
                        digest(file) != asset.get("sha256")):
                    valid = False
                    break
                keep.add(name)
            if not valid:
                summary["blocked"] += 1
                continue
            summary["readyChecked"] += 1
        else:
            summary["failedChecked"] += 1
        for item in job.iterdir():
            if item.name in keep:
                continue
            if item.is_symlink() or item.resolve(strict=True).parent != job:
                raise RuntimeError("task item escapes its directory")
            if item.is_file():
                summary["bytesToRemove"] += item.stat().st_size
            summary["filesToRemove"] += 1
            if args.apply:
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
    print(json.dumps(summary, sort_keys=True))
    if summary["blocked"]:
        raise SystemExit("some completed assets failed integrity checks; their inputs were retained")


if __name__ == "__main__":
    main()
