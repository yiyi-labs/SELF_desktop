"""Optional eyewear evidence; eye edges are never an eyewear classifier.

This research contract is separate from legacy ``glasses_visible`` masks,
which contain generic eye-band edges. It changes no old asset or publisher.
Missing/occluded observations are unknown, not evidence of bare eyes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class EyewearObservation:
    frame: str
    source_hash: str
    state: Literal["present", "absent", "unknown"]
    provenance: Literal["audited_semantics", "validated_parser", "edge_candidate"]
    eye_region_visible: bool
    confidence: float


def eyewear_policy(observations, *, source_hash, geometry_views=()):
    """Conservative sequence decision, with conflicting evidence preserved.

    The same glasses must be observed in at least three distinct frames
    before adding a new 3-D accessory. Geometry is a separate requirement;
    a classifier or a dark brow does not establish frame depth. These are
    research thresholds, not a claimed calibrated detection accuracy.
    """
    by_frame = {}
    for item in observations:
        if item.source_hash != source_hash:
            raise ValueError("accessory_source_mismatch")
        if item.frame in by_frame:
            raise ValueError("duplicate_accessory_observation")
        if item.state not in ("present", "absent", "unknown"):
            raise ValueError("invalid_accessory_state")
        if item.provenance not in ("audited_semantics", "validated_parser", "edge_candidate"):
            raise ValueError("invalid_accessory_provenance")
        if not 0 <= item.confidence <= 1:
            raise ValueError("invalid_accessory_confidence")
        by_frame[item.frame] = item
    usable = [r for r in by_frame.values() if r.eye_region_visible
              and r.confidence >= .85 and r.provenance != "edge_candidate"]
    positive = {r.frame for r in usable if r.state == "present"}
    negative = {r.frame for r in usable if r.state == "absent"}
    if positive and negative:
        state = "mixed_or_uncertain"
    elif len(positive) >= 3:
        state = "present_observed"
    elif len(negative) >= 3:
        state = "absent_observed"
    else:
        state = "unknown"
    supported = positive.intersection(geometry_views)
    create = state == "present_observed" and len(supported) >= 3
    return {"state": state, "createIndependentAccessory": create,
            "positiveFrames": sorted(positive), "negativeFrames": sorted(negative),
            "geometryAndSemanticFrames": sorted(supported),
            "eyeSurfacePolicy": "retain_observed_eye_brow_skin_pixels",
            "unknownPolicy": "do_not_invent_or_erase_eyewear; keep_observations",
            "mixedPolicy": "separate_observation_states_before_rigid_fitting",
            "publicationApproved": False}


def candidate_policy(data, segments, observations=()):
    """Used by the actual line experiment before exporting candidate geometry.

    Empty parts are valid. Generic masks, line counts and 3-D points alone
    never create eyewear. New semantic records must match the source and
    real local observations; they are not inferred from a filename or person.
    """
    observations = list(observations)
    if any(o.frame not in data["local"] for o in observations):
        raise ValueError("accessory_frame_not_in_observations")
    support = {item[0] for segment in segments for item in segment["support"]}
    result = eyewear_policy(observations, source_hash=data["sourceHash"], geometry_views=support)
    result["legacyEyeBandLabel"] = "edge_candidate_not_glasses_semantics"
    result["candidateSegments"] = len(segments)
    result["automaticPromotion"] = False
    return result
