"""Join a frozen PLY's source lineage with shared-render visibility scores.

Scores measure current visible contribution, not the effect of deleting points.
The report deliberately recommends no automatic pruning or relabeling.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


KIND = {0: "registered_colmap_track", 1: "interpolated_scene_seed"}


def audit(provenance: Path, visibility: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError(output)
    with np.load(provenance) as source, np.load(visibility) as weights:
        ply_hash = str(source["plySha256"].item())
        if ply_hash != str(weights["plySha256"].item()):
            raise ValueError("ply_visibility_lineage_hash_mismatch")
        indices = source["pointIndex"]
        kind = source["initialSourceKind"]
        origin = source["initialSourceId"]
        person = source["personPartition"]
        editable = int(weights["editableSplats"].item())
        intrusion = weights["faceIntrusion"]
        room = weights["roomSupport"]
        if (len(indices) != len(kind) or len(kind) != len(person) or
                not np.array_equal(indices, np.arange(len(indices))) or
                not np.all(person[:editable] == 1) or
                not np.all(person[editable:] == 0) or
                len(intrusion) != len(kind) - editable or
                len(room) != len(intrusion) or
                not np.isfinite(intrusion).all() or
                not np.isfinite(room).all()):
            raise ValueError("lineage_visibility_partition_invalid")
        if np.any(intrusion < -1e-4) or np.any(room < -1e-4):
            raise ValueError("negative_visibility_score")
        env_kind = kind[editable:]
        env_origin = origin[editable:]
        report = {"status": "source_attribution_not_pruning_decision",
                  "plySha256": ply_hash,
                  "pointCount": len(kind), "environmentPointCount": len(intrusion),
                  "scoreMeaning": "sum of visible full-scene compositing weights in selected pixels",
                  "faceIntrusionTotal": float(intrusion.sum()),
                  "roomSupportTotal": float(room.sum()), "byInitialSource": {}}
        for code, label in KIND.items():
            chosen = env_kind == code
            intr = intrusion[chosen]
            sup = room[chosen]
            report["byInitialSource"][label] = {
                "points": int(chosen.sum()),
                "distinctInitialSources": int(len(np.unique(env_origin[chosen]))),
                "faceIntrusionScore": float(intr.sum()),
                "faceIntrusionFraction": float(intr.sum() / max(intrusion.sum(), 1e-9)),
                "roomSupportScore": float(sup.sum()),
                "faceVisibleOver10": int(np.count_nonzero(intr > 10)),
                "faceVisibleOver10WeakRoomSupport":
                    int(np.count_nonzero((intr > 10) & (sup < intr * .2))),
            }
        if np.any(~np.isin(env_kind, list(KIND))):
            raise ValueError("unknown_source_kind")
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("provenance", type=Path)
    parser.add_argument("visibility", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.provenance, args.visibility, args.output), indent=2))
