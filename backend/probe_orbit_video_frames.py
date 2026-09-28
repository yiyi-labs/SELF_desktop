"""Read back the one-asset PlayCanvas orbit video as an evidence contact sheet."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np


def run(video: Path) -> dict:
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError("fixed_orbit_video_not_decodable")
    frames = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frames.append(frame)
    cap.release()
    if len(frames) < 60:
        raise RuntimeError(f"fixed_orbit_video_too_short:{len(frames)}")
    indices = np.linspace(0, len(frames)-1, 7).round().astype(int)
    panels = []
    for index in indices:
        panel = cv2.resize(frames[index], (360, 640), interpolation=cv2.INTER_AREA)
        cv2.putText(panel, f"frame {index+1}/{len(frames)}", (12, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, .65, (240, 240, 240), 2, cv2.LINE_AA)
        panels.append(panel)
    contact = np.hstack(panels)
    output = video.parent / "private-fixed-orbit-contact.jpg"
    cv2.imwrite(str(output), contact, [cv2.IMWRITE_JPEG_QUALITY, 92])
    gray = [cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) for frame in frames]
    changes = [float(np.abs(gray[i].astype(np.float32)-gray[i-1]).mean())
               for i in range(1, len(gray))]
    report = {"videoSha256": hashlib.sha256(video.read_bytes()).hexdigest(),
              "decodedFrames": len(frames), "frameSize": list(frames[0].shape[:2][::-1]),
              "sampledIndicesZeroBased": indices.tolist(),
              "consecutiveGrayscaleDeltaMean": float(np.mean(changes)),
              "consecutiveGrayscaleDeltaP95": float(np.quantile(changes, .95)),
              "contactSheet": str(output)}
    (video.parent / "video-frames.audit.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    run(parser.parse_args().video)
