"""Try long-baseline static pairs around the weak profile segment in isolation.

This reuses the *same* masked keypoints and estimated focal length. It never
touches the production SfM DB or substitutes dynamic portrait observations.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import time
from pathlib import Path

import pycolmap

from probe_static_alignment import best_model
from probe_static_frame_quality import quality, section_stats


def run(job: Path) -> dict:
    started = time.perf_counter()
    root = job / "static_sfm_probe_stride1"
    target = root / "targeted_global"
    target.mkdir(exist_ok=True)
    report_path = target / "report.json"
    with sqlite3.connect(root / "calibrated_global" / "colmap.db") as baseline:
        original_verified = baseline.execute(
            "SELECT count(*) FROM two_view_geometries WHERE rows>0").fetchone()[0]
    if report_path.exists():
        summary = json.loads(report_path.read_text(encoding="utf-8"))
        if summary["verifiedPairsBefore"] != original_verified:
            summary["verifiedPairsBefore"] = original_verified
            report_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps(summary), flush=True)
        return summary
    database = target / "colmap.db"
    if database.exists():
        raise ValueError("incomplete_targeted_database_exists")
    shutil.copy2(root / "calibrated_global" / "colmap.db", database)
    with sqlite3.connect(database) as connection:
        ids = {name: number for number, name in connection.execute("SELECT image_id,name FROM images")}
        existing = {row[0] for row in connection.execute("SELECT pair_id FROM two_view_geometries")}
    names = [f"frame_{number:04d}.png" for number in range(1, 161)]
    if set(names) != set(ids):
        raise ValueError("image_id_name_manifest_mismatch")
    pairs = set()
    for number in range(52, 113):
        for offset in (-50, -42, -34, -26, -20, 20, 26, 34, 42, 50):
            other = number + offset
            if not 1 <= other <= 160:
                continue
            one, two = names[number - 1], names[other - 1]
            pair_id = min(ids[one], ids[two]) * 2147483647 + max(ids[one], ids[two])
            if pair_id not in existing:
                pairs.add(tuple(sorted((one, two))))
    pair_file = target / "targeted_pairs.txt"
    pair_file.write_text("".join(f"{one} {two}\n" for one, two in sorted(pairs)), encoding="utf-8")
    matching_started = time.perf_counter()
    pycolmap.match_image_pairs(database,
        matching_options=pycolmap.FeatureMatchingOptions(num_threads=8),
        pairing_options=pycolmap.ImportedPairingOptions(match_list_path=str(pair_file)),
        device=pycolmap.Device.cpu)
    matching_seconds = time.perf_counter() - matching_started
    with sqlite3.connect(database) as connection:
        new_verified = connection.execute(
            "SELECT count(*) FROM two_view_geometries WHERE rows>0").fetchone()[0]
    models = pycolmap.global_mapping(database, job / "frames", target / "sparse")
    if not models:
        raise ValueError("targeted_global_mapping_failed")
    model = best_model(target / "sparse")
    frame_rows = quality(model, names)
    details = {"sections": section_stats(frame_rows), "perFrame": frame_rows}
    (target / "frame_quality.json").write_text(json.dumps(details, separators=(",", ":")), encoding="utf-8")
    report = {"inputPairsRequested": len(pairs), "verifiedPairsBefore": original_verified,
              "verifiedPairsAfter": new_verified, "registered": model.num_reg_images(),
              "points3D": model.num_points3D(), "sections": details["sections"],
              "matchingSeconds": round(matching_seconds, 2),
              "elapsedSeconds": round(time.perf_counter() - started, 2),
              "sameMasksFeaturesAndEstimatedFocal": True}
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)
    return report


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        raise SystemExit("probe_targeted_static_pairs.py JOB_DIR")
    run(Path(sys.argv[1]))
