"""Isolated complete-scene training trial on an already retained capture.

Inputs are symlinked read-only by convention; every training output is in a
new run directory.  This script never writes to the source job or tablet.
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

from reconstruction_joint_visibility import sha256_file
from reconstruction_train_joint import train


INPUTS = ("capture.mp4", "frames", "face_masks", "environment_masks",
          "face_camera_poses.npz", "face_regions.json", "environment_seeds.npz",
          "sparse")


def run(source: Path, output: Path, steps: int = 900,
        clean_research: bool = False, detail_research: bool = False) -> dict:
    if output.exists():
        raise FileExistsError(output)
    if steps < 400:
        raise ValueError("research_steps_below_diagnostic_minimum")
    output.mkdir(parents=True)
    for name in INPUTS:
        item = source / name
        if not item.exists():
            raise FileNotFoundError(item)
        (output / name).symlink_to(item.resolve(), target_is_directory=item.is_dir())
    shutil.copyfile(source / "portrait.view.json", output / "portrait.view.json")
    (output / "job.json").write_text('{"progress":0}', encoding="utf-8")
    started = time.perf_counter()
    train(output, steps=steps, enforce_quality_gate=False,
          shared_research=True, clean_research=clean_research,
          detail_research=detail_research)
    ply = output / "portrait.gaussian.ply"
    metrics = json.loads((output / "training_metrics.json").read_text())
    result = {"status": "isolated_research_not_publishable",
              "sourceCaptureSha256": sha256_file(source / "capture.mp4"),
              "sourceBaselinePlySha256": sha256_file(source / "portrait.gaussian.ply"),
              "candidatePlySha256": sha256_file(ply),
              "steps": steps, "trainingMetrics": metrics,
              "observedFaceInteriorCleanResearch": clean_research,
              "sourceEdgeDetailResearch": detail_research,
              "elapsedSeconds": round(time.perf_counter()-started, 2),
              "limits": ["Mixed person/room COLMAP cameras are not trusted static observations",
                         "Head relative motion is estimated from canonical MediaPipe, not fitted FLAME",
                         "Clothing remains in the static group; neck motion is unresolved",
                         "A short research run does not establish E3/E4 visual quality"]}
    (output / "research-audit.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--steps", type=int, default=900)
    parser.add_argument("--clean-research", action="store_true")
    parser.add_argument("--detail-research", action="store_true")
    args = parser.parse_args()
    result = run(args.source, args.output, args.steps, args.clean_research,
                 args.detail_research)
    print(json.dumps({key: result[key] for key in
                      ("status", "sourceCaptureSha256", "candidatePlySha256",
                       "steps", "elapsedSeconds")}, ensure_ascii=False))
