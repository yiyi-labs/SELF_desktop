"""Check whether conservative static KLT tracks can bridge weak profile views.

No interpolated cameras or synthetic parallax are produced. KLT tracks are
an independent correspondence diagnostic on existing selected RGB frames.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import cv2
import numpy as np


def run(job: Path) -> dict:
    started = time.perf_counter()
    root = job / "static_sfm_probe_stride1"
    frames, safe_masks = [], []
    for index in range(1, 161):
        name = f"frame_{index:04d}.png"
        frame = cv2.imread(str(job / "frames" / name), cv2.IMREAD_GRAYSCALE)
        mask = cv2.imread(str(root / "masks" / (name + ".png")), cv2.IMREAD_GRAYSCALE)
        if frame is None or mask is None:
            raise ValueError(f"source_or_mask_missing:{name}")
        image = cv2.resize(frame, (540, 960), interpolation=cv2.INTER_AREA)
        safe = cv2.resize(mask, (540, 960), interpolation=cv2.INTER_NEAREST)
        safe = cv2.erode(safe, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11)))
        frames.append(image)
        safe_masks.append(safe)
    tracks = []
    for start in range(0, 160, 8):
        seed = cv2.goodFeaturesToTrack(frames[start], maxCorners=400, qualityLevel=.008,
                                       minDistance=8, mask=safe_masks[start], blockSize=5)
        if seed is None:
            continue
        active = seed.reshape(-1, 2)
        history = [[(start + 1, float(point[0]), float(point[1]))] for point in active]
        for current in range(start + 1, min(start + 42, 160)):
            if len(active) == 0:
                break
            predicted, valid, _ = cv2.calcOpticalFlowPyrLK(
                frames[current - 1], frames[current], active.reshape(-1, 1, 2), None,
                winSize=(31, 31), maxLevel=3,
                criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, .01))
            back, backward_valid, _ = cv2.calcOpticalFlowPyrLK(
                frames[current], frames[current - 1], predicted, None,
                winSize=(31, 31), maxLevel=3,
                criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, .01))
            xy = predicted.reshape(-1, 2)
            error = np.linalg.norm(back.reshape(-1, 2) - active, axis=1)
            finite = np.isfinite(xy).all(axis=1)
            safe_xy = np.where(np.isfinite(xy), xy, 0)
            x = np.clip(safe_xy[:, 0].astype(int), 0, 539)
            y = np.clip(safe_xy[:, 1].astype(int), 0, 959)
            good = finite & (valid[:, 0] > 0) & (backward_valid[:, 0] > 0) & (error < 1.5) & \
                (xy[:, 0] >= 0) & (xy[:, 0] < 540) & (xy[:, 1] >= 0) & (xy[:, 1] < 960) & \
                (safe_masks[current][y, x] > 0)
            for kept, record, point in zip(good, history, xy):
                if kept:
                    record.append((current + 1, float(point[0]), float(point[1])))
                elif len(record) >= 2:
                    tracks.append(record)
            history = [record for kept, record in zip(good, history) if kept]
            active = xy[good]
        tracks.extend(record for record in history if len(record) >= 2)
    spans = [track[-1][0] - track[0][0] for track in tracks]
    long = [track for track in tracks if len(track) >= 8]
    bridge = [track for track in long if track[0][0] <= 60 and track[-1][0] >= 100]
    middle = [track for track in long if track[0][0] <= 80 and track[-1][0] >= 95]
    per_section = []
    for start in range(1, 161, 20):
        supports = [sum(start <= observation[0] <= start + 19 for observation in track)
                    for track in long]
        per_section.append({"range": [start, start + 19],
                            "longTracksObservedAtLeastOnce": sum(value > 0 for value in supports),
                            "longTracksObservedFiveTimes": sum(value >= 5 for value in supports)})
    report = {"seedsEverySelectedFrames": 8, "maxTrackLengthFrames": 42,
              "staticMarginHalfResolutionPixels": 5,
              "tracksTwoPlus": len(tracks), "tracksEightPlus": len(long),
              "trackSpanP90SelectedFrames": round(float(np.quantile(spans, .9)), 2),
              "tracksBridging61To100": len(bridge),
              "tracksAcross80To95": len(middle), "sections": per_section,
              "elapsedSeconds": round(time.perf_counter() - started, 2),
              "note": "KLT tracks require geometric triangulation/holdout validation before camera use"}
    (root / "klt_tracks.audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)
    return report


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        raise SystemExit("probe_static_klt_tracks.py JOB_DIR")
    run(Path(sys.argv[1]))
