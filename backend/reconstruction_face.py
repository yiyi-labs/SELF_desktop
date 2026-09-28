"""Conservative, local-only head masks for new reconstruction jobs.

The mask is deliberately wider than the estimated face. It guides feature
matching and training; it is never applied to the source video or old assets.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


COMPONENT_MASK_NAMES = ("face_core", "face_boundary", "hair_visible",
                        "glasses_visible", "neck_cloth_visible", "room_visible",
                        "unknown_or_occluded")


def make_component_observations(confidence, hair_probability, landmarks, rgb):
    """Conservative *observed* labels; eyewear edges are candidates, not truth.

    Unknown is a 2D uncertainty band. It makes no assertion about invisible
    3D volume. In particular a missing hair label cannot carve unseen hair.
    This helper is opt-in: it does not change production reconstruction masks.
    """
    import cv2
    import numpy as np

    height, width = rgb.shape[:2]
    probabilities = np.stack([cv2.resize(np.asarray(layer).squeeze(),
        (width, height), interpolation=cv2.INTER_LINEAR) for layer in confidence])
    if probabilities.shape != (6, height, width):
        raise ValueError("component_probability_layout_invalid")
    hair_probability = cv2.resize(np.asarray(hair_probability).squeeze(),
                                   (width, height))
    labels = probabilities.argmax(0)
    certainty = probabilities.max(0)
    points = np.asarray(landmarks, np.float32)
    if points.shape != (468, 2) or not np.isfinite(points).all():
        raise ValueError("component_landmarks_invalid")
    oval = np.zeros((height, width), np.uint8)
    oval_indices = [10,338,297,332,284,251,389,356,454,323,361,288,397,
                    365,379,378,400,377,152,148,176,149,150,136,172,58,
                    132,93,234,127,162,21,54,103,67,109]
    cv2.fillConvexPoly(oval, cv2.convexHull(points[oval_indices].round().astype(np.int32)), 1)
    radius = max(5, round(np.linalg.norm(points[234]-points[454])*.025))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2*radius+1,)*2)
    hair = ((hair_probability >= .65) & (certainty >= .55)).astype(np.uint8)
    # Only high-contrast edges within an observed accessory/eye band. The
    # generic "others" class also contains brows/eyes/lips; never rename it
    # wholesale to glasses. Independent 3D support is required downstream.
    eye_band = np.zeros_like(oval)
    eye_points = points[[33,133,362,263,168,6]]
    eye_width = np.linalg.norm(points[33]-points[263])
    x0,x1 = np.clip([eye_points[:,0].min()-.15*eye_width,
                      eye_points[:,0].max()+.15*eye_width],0,width).astype(int)
    y0,y1 = np.clip([eye_points[:,1].min()-.16*eye_width,
                      eye_points[:,1].max()+.16*eye_width],0,height).astype(int)
    eye_band[y0:y1,x0:x1]=1
    edges = cv2.Canny(cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY),55,125)>0
    glasses = (eye_band.astype(bool) & (labels==5) & (certainty>.55) & edges)
    glasses = cv2.dilate(glasses.astype(np.uint8),np.ones((3,3),np.uint8))
    core = cv2.erode(oval,kernel)>0
    core &= ((labels==3)|(labels==5)) & (certainty>=.70)
    core &= cv2.dilate(hair,kernel)==0
    core &= cv2.dilate(glasses,kernel)==0
    cloth = ((labels==2)|(labels==4)) & (certainty>=.70) & (oval==0)
    dynamic = (probabilities[1:].sum(0)>.25)|(oval>0)
    room = (probabilities[0]>=.85) & (cv2.dilate(dynamic.astype(np.uint8),kernel)==0)
    boundary = (cv2.dilate(oval,kernel)>0) & ~core
    assigned = core|boundary|(hair>0)|(glasses>0)|cloth|room
    masks = dict(zip(COMPONENT_MASK_NAMES,
        [core,boundary,hair>0,glasses>0,cloth,room,~assigned]))
    masks = {key:value.astype(np.uint8)*255 for key,value in masks.items()}
    return masks, labels.astype(np.uint8), certainty.astype(np.float32)


HERE = Path(__file__).resolve().parent
SEGMENTER = HERE / "models" / "selfie_multiclass_256x256.tflite"
LANDMARKER = HERE / "models" / "face_landmarker.task"
MODEL_SHA256 = {
    SEGMENTER.name: "c6748b1253a99067ef71f7e26ca71096cd449bae fa8f101900ea23016507e0e0".replace(" ", ""),
    LANDMARKER.name: "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff",
}


def check_models() -> None:
    for path in (SEGMENTER, LANDMARKER):
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != MODEL_SHA256[path.name]:
            raise RuntimeError("face_model_missing_or_changed")


def head_box(landmarks, width: int, height: int) -> tuple[int, int, int, int]:
    """Expanded head envelope: no tight clipping at jaw, ear or hairline."""
    xs = [point.x * width for point in landmarks]
    ys = [point.y * height for point in landmarks]
    left, right = max(0., min(xs)), min(float(width), max(xs))
    top, bottom = max(0., min(ys)), min(float(height), max(ys))
    cx, cy = (left + right) / 2, (top + bottom) / 2
    face_w, face_h = right - left, bottom - top
    x1 = max(0, round(cx - face_w * .78))
    x2 = min(width, round(cx + face_w * .78))
    y1 = max(0, round(cy - face_h * .95))
    # Keep the jaw, but let recorded neck and clothing remain part of the
    # surrounding scene so there is no isolated floating head at the collar.
    y2 = min(height, round(cy + face_h * .62))
    return x1, y1, max(0, x2 - x1), max(0, y2 - y1)


def make_head_mask(confidence, box, width: int, height: int):
    """Use skin/hair probabilities inside a generous head envelope.

    Connected-component selection excludes a similarly colored hand or room
    object. Dilation protects fine hair and the profile silhouette.
    """
    import cv2
    import numpy as np

    x, y, w, h = box
    if w < width * .09 or h < height * .10:
        raise RuntimeError("face_too_small_for_reconstruction")
    scores = sum(cv2.resize(confidence[index], (width, height), interpolation=cv2.INTER_LINEAR)
                 for index in (1, 2, 3))
    envelope = np.zeros((height, width), dtype=np.uint8)
    envelope[y:y + h, x:x + w] = 1
    raw = ((scores >= .38) & (envelope > 0)).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(raw, 8)
    components = [(int(stats[i, cv2.CC_STAT_AREA]), i) for i in range(1, count)]
    if not components:
        raise RuntimeError("face_segment_missing")
    area, index = max(components)
    if area < max(500, round(w * h * .07)):
        raise RuntimeError("face_segment_too_small")
    selected = (labels == index).astype(np.uint8)
    # A wide dilation copies the room into the portrait as a bright halo.
    # The segmenter already resolves hair/ears; keep only a narrow uncertainty
    # band, independent of how large the face appears in the frame.
    radius = max(2, min(7, round(min(w, h) * .008)))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius * 2 + 1, radius * 2 + 1))
    selected = cv2.morphologyEx(selected, cv2.MORPH_CLOSE, kernel)
    selected = cv2.dilate(selected, kernel)
    # Landmarks may cover translucent hair poorly; retain the central face
    # even if a low-confidence segment has a small hole.
    central = np.zeros_like(selected)
    cv2.ellipse(central, (x + w // 2, y + h // 2),
                (max(1, round(w * .30)), max(1, round(h * .33))),
                0, 0, 360, 1, -1)
    selected = np.maximum(selected, central * envelope)
    fraction = float(np.count_nonzero(selected)) / (width * height)
    if not .008 <= fraction <= .55:
        raise RuntimeError("face_mask_unreliable")
    return selected * 255, fraction


def make_static_feature_mask(confidence, head_mask):
    """Shadow mask excluding all observed moving person/accessory classes."""
    import cv2
    import numpy as np

    if len(confidence) != 6 or any(layer.shape != head_mask.shape for layer in confidence):
        raise ValueError("static_feature_label_shape_changed")
    categories = np.stack(confidence).argmax(axis=0)
    person_core = ((np.maximum.reduce(confidence[1:6]) >= .45) &
                   np.isin(categories, (1, 2, 3, 4, 5)))
    person_core |= head_mask > 0
    return cv2.bitwise_not(cv2.dilate(
        person_core.astype(np.uint8) * 255,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (17, 17))))


def prepare(path: Path, frames: list[Path]) -> dict[str, tuple[int, int, int, int]]:
    """Produce per-frame masks and numeric QA; no image is persisted as QA."""
    import cv2
    import mediapipe as mp
    import numpy as np

    check_models()
    masks = path / "face_masks"
    masks.mkdir(exist_ok=True)
    scene_exclusions = path / "scene_exclusions"
    scene_exclusions.mkdir(exist_ok=True)
    component_dir = path / "person_components"
    component_dir.mkdir(exist_ok=True)
    static_feature_dir = path / "static_feature_masks"
    static_feature_dir.mkdir(exist_ok=True)
    boxes = {}
    fractions = []
    sharpness = []
    missing = []
    previous = None
    face_landmarks = {}
    face_options = mp.tasks.vision.FaceLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(LANDMARKER)), num_faces=1,
        min_face_detection_confidence=.35, min_face_presence_confidence=.4)
    segment_options = mp.tasks.vision.ImageSegmenterOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(SEGMENTER)),
        output_confidence_masks=True)
    with mp.tasks.vision.FaceLandmarker.create_from_options(face_options) as landmarker, \
         mp.tasks.vision.ImageSegmenter.create_from_options(segment_options) as segmenter:
        for frame in frames:
            bgr = cv2.imread(str(frame), cv2.IMREAD_COLOR)
            if bgr is None:
                raise RuntimeError("frame_decode_failed")
            height, width = bgr.shape[:2]
            image = mp.Image(image_format=mp.ImageFormat.SRGB,
                             data=np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)))
            result = landmarker.detect(image)
            if len(result.face_landmarks) != 1:
                missing.append(frame.name)
                continue
            box = head_box(result.face_landmarks[0], width, height)
            center = (box[0] + box[2] / 2, box[1] + box[3] / 2)
            if previous is not None:
                previous_center, previous_size = previous
                jump = np.hypot((center[0] - previous_center[0]) / width,
                                (center[1] - previous_center[1]) / height)
                size_ratio = box[2] / max(previous_size, 1)
                if jump > .35 or not .42 <= size_ratio <= 2.4:
                    missing.append(frame.name)
                    continue
            segmented = segmenter.segment(image)
            confidence = [layer.numpy_view().squeeze().copy() for layer in segmented.confidence_masks]
            if len(confidence) != 6:
                raise RuntimeError("face_model_labels_changed")
            # Keep hair, skin, clothes and uncertain accessory observations
            # distinct for later static-room and upper-body evidence checks.
            # These 2D labels are not 3D geometry and do not change the
            # established reconstruction masks in this stage.
            categories = np.stack(confidence).argmax(axis=0).astype(np.uint8)
            if not cv2.imwrite(str(component_dir / (frame.name + ".png")), categories):
                raise RuntimeError("person_component_write_failed")
            try:
                mask, fraction = make_head_mask(confidence, box, width, height)
            except RuntimeError:
                missing.append(frame.name)
                continue
            if not cv2.imwrite(str(masks / (frame.name + ".png")), mask):
                raise RuntimeError("face_mask_write_failed")
            # Shadow-only static feature candidate.  The current COLMAP
            # mapper is unchanged until these masks pass the E1 comparison.
            # Clothing and body skin must not become room evidence merely
            # because they lie outside the head mask.
            # Class 5 is an accessory (not a static wall feature): omitting
            # it leaks eyewear and other moving objects into camera evidence.
            static_feature = make_static_feature_mask(confidence, mask)
            if not cv2.imwrite(str(static_feature_dir / (frame.name + ".png")),
                               static_feature):
                raise RuntimeError("static_feature_mask_write_failed")
            # Neck and clothing must still contribute real scene seeds below
            # the tracked head. The head mask itself protects facial skin;
            # only hair and accessories outside it remain excluded.
            excluded_scores = sum(cv2.resize(confidence[index], (width, height),
                                              interpolation=cv2.INTER_LINEAR)
                                  for index in (1, 5))
            excluded = np.maximum((excluded_scores >= .38).astype(np.uint8) * 255, mask)
            if not cv2.imwrite(str(scene_exclusions / (frame.name + ".png")), excluded):
                raise RuntimeError("scene_exclusion_write_failed")
            boxes[frame.name] = box
            face_landmarks[frame.name] = np.asarray(
                [[mark.x * width, mark.y * height]
                 for mark in result.face_landmarks[0][:468]], dtype=np.float32)
            fractions.append(fraction)
            gray = cv2.cvtColor(bgr[box[1]:box[1] + box[3],
                                        box[0]:box[0] + box[2]], cv2.COLOR_BGR2GRAY)
            sharpness.append(float(cv2.Laplacian(gray, cv2.CV_32F).var()))
            previous = (center, box[2])
    # Masked COLMAP needs sufficient side views as well as frontal anchors.
    # Do not silently fall back to matching the room when face tracking fails.
    longest_gap = 0
    gap = 0
    for frame in frames:
        gap = 0 if frame.name in boxes else gap + 1
        longest_gap = max(longest_gap, gap)
    if len(boxes) < max(16, round(len(frames) * .70)) or longest_gap > 5:
        raise RuntimeError("face_tracking_incomplete_reshoot")
    np.savez_compressed(path / "face_landmarks.npz", **face_landmarks)
    report = {"sampledFrames": len(frames), "trackedFrames": len(boxes),
              "maskAreaMedian": round(float(np.median(fractions)), 4),
              "maskAreaMin": round(min(fractions), 4),
              "faceSharpnessMedian": round(float(np.median(sharpness)), 2),
              "model": "MediaPipe SelfieMulticlass + FaceLandmarker",
              "untrackedFrames": len(missing), "longestUntrackedGap": longest_gap}
    (path / "face_mask_quality.json").write_text(json.dumps(report, separators=(",", ":")), encoding="utf-8")
    return boxes
