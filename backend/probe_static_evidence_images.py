"""Private visual QA of actual masked SfM observations at selected frames."""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from probe_static_alignment import best_model


def run(job: Path) -> dict:
    root = job / "static_sfm_probe_stride1"
    output = root / "visual_evidence"
    output.mkdir(exist_ok=True)
    candidates = {"original-global": best_model(root / "calibrated_global" / "sparse"),
                  "targeted-global": best_model(root / "targeted_global" / "sparse")}
    names = ("frame_0040.png", "frame_0065.png", "frame_0080.png",
             "frame_0090.png", "frame_0125.png")
    entries = []
    for name in names:
        source = cv2.imread(str(job / "frames" / name), cv2.IMREAD_COLOR)
        mask = cv2.imread(str(root / "masks" / (name + ".png")), cv2.IMREAD_GRAYSCALE)
        if source is None or mask is None or source.shape[:2] != mask.shape:
            raise ValueError(f"source_or_mask_missing:{name}")
        original = cv2.resize(source, (540, 960), interpolation=cv2.INTER_AREA)
        for label, model in candidates.items():
            by_name = {image.name: image for image in model.images.values() if image.has_pose}
            image = by_name[name]
            annotated = source.copy()
            contours, _ = cv2.findContours(255 - mask, cv2.RETR_EXTERNAL,
                                            cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(annotated, contours, -1, (190, 150, 60), 2)
            count = 0
            for feature in image.points2D:
                if not feature.has_point3D():
                    continue
                x, y = np.asarray(feature.xy).round().astype(int)
                cv2.circle(annotated, (x, y), 4, (40, 230, 90), -1, cv2.LINE_AA)
                count += 1
            panel = cv2.resize(annotated, (540, 960), interpolation=cv2.INTER_AREA)
            both = np.concatenate((original, panel), axis=1)
            cv2.putText(both, f"{name}   {label}   static inliers={count}",
                        (18, 945), cv2.FONT_HERSHEY_SIMPLEX, .55, (255, 255, 255), 2, cv2.LINE_AA)
            path = output / f"{name.removesuffix('.png')}-{label}.png"
            if not cv2.imwrite(str(path), both):
                raise OSError("visual_evidence_write_failed")
            entries.append({"frame": name, "candidate": label, "inliers": count,
                            "file": str(path)})
    report = {"evidence": entries, "private": True,
              "note": "left: decoded source; right: static 3D observations and person exclusion contour"}
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"files": len(entries), "output": str(output)}), flush=True)
    return report


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        raise SystemExit("probe_static_evidence_images.py JOB_DIR")
    run(Path(sys.argv[1]))
