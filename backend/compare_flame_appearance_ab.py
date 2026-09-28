"""Fail-closed comparison of two *completed* same-protocol FLAME runs.

This deliberately does not select a production model. A partially prepared
candidate or an old Open result cannot masquerade as the new 900-step A/B.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from probe_flame_open_fit import HELD, SOURCE_SHA256, TRAIN


def compare(job: Path, run_id: str = "ab-20260927") -> dict:
    audits = {}
    for variant in ("open", "standard"):
        root = job / f"flame_{variant}_e2_20260927"
        path = root / f"private-optimized-subset-900-footprint-1.00-{run_id}" / "audit.json"
        if not path.is_file():
            raise FileNotFoundError(f"completed_900_step_ab_missing:{variant}:{path}")
        audits[variant] = json.loads(path.read_text(encoding="utf-8"))
    same = ("sourceSha256", "trainerSourceSha256", "runId", "stage",
            "actualOptimizerStepCount", "trainFrames", "heldColorAndLossExcluded",
            "fixedK", "orientation", "initialFootprintFactor")
    if any(audits["open"].get(key) != audits["standard"].get(key) for key in same):
        raise ValueError("ab_training_protocol_mismatch")
    if (audits["open"]["sourceSha256"] != SOURCE_SHA256 or
            audits["open"]["trainFrames"] != list(TRAIN) or
            audits["open"]["heldColorAndLossExcluded"] != list(HELD) or
            audits["open"]["actualOptimizerStepCount"] != 900 or
            audits["open"]["initialFootprintFactor"] != 1.0 or
            audits["open"]["stage"] != "subset" or
            audits["open"]["runId"] != run_id or
            audits["open"].get("splitEvents") or audits["standard"].get("splitEvents")):
        raise ValueError("ab_fidelity_or_holdout_gate_failed")
    rows = []
    for index in HELD:
        key = str(index)
        row = {"frame": index}
        for variant in ("open", "standard"):
            audit = audits[variant]
            row[variant] = {
                "initialRoiRgbL1IncludingMissing": audit["initialMetrics"][key][
                    "fixedRoiRgbL1IncludingMissing"],
                "optimizedRoiRgbL1IncludingMissing": audit["finalMetrics"][key][
                    "fixedRoiRgbL1IncludingMissing"],
                "faceRoiRgbL1IncludingMissing": audit["finalMetrics"][key][
                    "fixedFaceRgbL1IncludingMissing"],
                "hairRoiRgbL1IncludingMissing": audit["finalMetrics"][key][
                    "fixedHairRgbL1IncludingMissing"],
                "hairPrecisionProxy": audit["finalMetrics"][key]["hairMaskPrecisionProxy"]}
        rows.append(row)
    mean = {variant: {
        "initial": sum(row[variant]["initialRoiRgbL1IncludingMissing"] for row in rows)/len(rows),
        "optimized": sum(row[variant]["optimizedRoiRgbL1IncludingMissing"] for row in rows)/len(rows)}
        for variant in ("open", "standard")}
    report = {"status": "research_ab_ready_for_visual_review_not_model_selection",
              "sourceSha256": SOURCE_SHA256, "trainerSourceSha256": audits["open"]["trainerSourceSha256"],
              "runId": run_id, "fixedProtocol": {key: audits["open"][key] for key in same},
              "models": {variant: {"modelPath": audits[variant]["modelPath"],
                                   "modelSha256": audits[variant]["modelSha256"],
                                   "candidateCounts": audits[variant]["candidateCounts"],
                                   "parameterMeanAbsoluteChange": audits[variant][
                                       "parameterMeanAbsoluteChange"],
                                   "fullElapsedSeconds": audits[variant]["fullElapsedSeconds"],
                                   "cudaPeakAllocatedMiB": audits[variant]["cudaPeakAllocatedMiB"]}
                         for variant in ("open", "standard")},
              "heldFrameResults": rows, "meanHeldFixedRoiRgbL1": mean,
              "releaseDecision": "none; require local visual review, renderer gate, full scene and license",
              "standardLicense": "offline research only; not default app or product"}
    out = job / f"flame-appearance-ab-{run_id}.audit.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "means": mean, "path": str(out)}, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=Path)
    parser.add_argument("--run-id", default="ab-20260927")
    args = parser.parse_args()
    compare(args.job, args.run_id)
