"""Recover recorded room observations in the portrait's world coordinates."""

from __future__ import annotations

import json
import math
from pathlib import Path


def make_environment_masks(path: Path, names: list[str]) -> Path:
    import cv2

    directory = path / "environment_masks"
    directory.mkdir(exist_ok=True)
    for name in names:
        excluded = cv2.imread(str(path / "scene_exclusions" / (name + ".png")), cv2.IMREAD_GRAYSCALE)
        if excluded is None:
            raise ValueError("environment_exclusion_mask_missing")
        # Preserve collar, shoulders and immediately adjacent room pixels.
        # A 3.5% moat erased roughly 38 source pixels around the person and
        # left a visible empty band between the high-detail face and scene.
        # A narrow uncertainty margin still avoids seeding blended hair edge.
        radius = max(3, min(9, round(min(excluded.shape) * .006)))
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius * 2 + 1,) * 2)
        background = cv2.bitwise_not(cv2.dilate(excluded, kernel))
        if not cv2.imwrite(str(directory / (name + ".png")), background):
            raise OSError("environment_mask_write_failed")
    return directory


def foreground_clearance(points, target, front, up, head_radii,
                         splat_radius=0., yaw_limit=65., step=13.):
    """Reject room centers whose Gaussian support may cross the head silhouette.

    Every camera orbit from -65 to +65 degrees is checked, including unshot
    views. Side room is allowed if its projection stays outside the head;
    anything behind the head must remain behind it at all those views.
    """
    import numpy as np

    xyz = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    center = np.asarray(target, dtype=np.float64)
    normal = np.asarray(front, dtype=np.float64)
    normal /= np.linalg.norm(normal)
    vertical = np.asarray(up, dtype=np.float64)
    vertical /= np.linalg.norm(vertical)
    right = np.cross(vertical, normal)
    right /= np.linalg.norm(right)
    rel = xyz - center
    rx, ry, rz = head_radii
    good = np.isfinite(xyz).all(axis=1)
    for yaw in np.arange(-yaw_limit, yaw_limit + .5, step):
        radians = math.radians(float(yaw))
        direction = normal * math.cos(radians) + right * math.sin(radians)
        across = np.cross(vertical, direction)
        across /= np.linalg.norm(across)
        lateral = np.abs(rel @ across)
        height = np.abs(rel @ vertical)
        depth = rel @ direction
        # An extra margin accounts for splat footprint rather than checking
        # only its center. Outside the projected head, room may come forward.
        covers_head = ((lateral <= rx * 1.15 + splat_radius) &
                       (height <= ry * 1.15 + splat_radius))
        good &= ~covers_head | (depth + splat_radius < -rz * .35)
    return good


def environment_view_support(path: Path, cameras, means, scales):
    """Require real room/clothing pixels and bound every splat's screen size."""
    import numpy as np
    from PIL import Image

    count = len(means)
    visible = np.zeros(count, dtype=np.uint16)
    supported = np.zeros(count, dtype=np.uint16)
    largest_radius = np.zeros(count, dtype=np.float32)
    size = np.exp(scales).max(axis=1)
    for name, pose, intrinsic, width, height in cameras:
        xyz = means @ pose[:3, :3].T + pose[:3, 3]
        depth = xyz[:, 2]
        projected = xyz @ intrinsic.T
        with np.errstate(divide="ignore", invalid="ignore"):
            u = projected[:, 0] / projected[:, 2]
            v = projected[:, 1] / projected[:, 2]
            radius = intrinsic[0, 0] * .5 * size / depth
        on_screen = ((depth > .01) & np.isfinite(u) & np.isfinite(v) &
                     (u >= 0) & (u < width) & (v >= 0) & (v < height))
        ids = np.flatnonzero(on_screen)
        visible[ids] += 1
        largest_radius[ids] = np.maximum(largest_radius[ids], radius[ids])
        with Image.open(path / "environment_masks" / (name.name + ".png")) as source:
            mask = np.asarray(source.convert("L"))
        supported[ids] += (mask[v[ids].astype(int), u[ids].astype(int)] > 0).astype(np.uint16)
    stable = (supported >= 3) & (supported >= visible * .18)
    # Smooth walls need broad Gaussians. The first 7.5 px cap turned a room
    # into isolated flakes; 30 px still rejects the 100+ px white clouds.
    compact = largest_radius <= 30.
    return stable, compact, largest_radius


def seed_recorded_scene(path: Path, model_path: Path | None = None) -> dict:
    """Add coarse room/clothing seeds from the one registered scene and video.

    Face and environment share these COLMAP cameras; there is no second room
    reconstruction or independent coordinate frame to splice into the face.
    Seed colors are observed pixels, and depths interpolate nearby measured
    tracks only within recorded room/body regions.
    """
    import cv2
    import numpy as np
    import pycolmap
    from scipy.spatial import cKDTree

    model = pycolmap.Reconstruction(model_path or path / "sparse" / "0")
    images = sorted((image for image in model.images.values() if image.has_pose),
                    key=lambda image: image.name)
    if len(images) < 16:
        raise ValueError("scene_registered_views_insufficient")
    make_environment_masks(path, [image.name for image in images])
    positions, colors, sampled = [], [], []
    for image in images[::max(6, len(images) // 14)]:
        frame = cv2.imread(str(path / "frames" / image.name), cv2.IMREAD_COLOR)
        mask = cv2.imread(str(path / "environment_masks" / (image.name + ".png")),
                          cv2.IMREAD_GRAYSCALE)
        if frame is None or mask is None or frame.shape[:2] != mask.shape:
            raise ValueError("scene_frame_or_mask_invalid")
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        intrinsic = np.asarray(model.cameras[image.camera_id].calibration_matrix())
        pose = np.asarray(image.cam_from_world().matrix())
        observations, depths = [], []
        for feature in image.points2D:
            if not feature.has_point3D():
                continue
            point = model.points3D[feature.point3D_id]
            if point.error > 3 or point.track.length() < 3:
                continue
            u, v = feature.xy
            if not (0 <= int(u) < mask.shape[1] and 0 <= int(v) < mask.shape[0]):
                continue
            if mask[int(v), int(u)] == 0:
                continue
            depth = (pose[:3, :3] @ np.asarray(point.xyz) + pose[:3, 3])[2]
            if depth > .01:
                observations.append([u, v])
                depths.append(depth)
        if len(depths) < 80:
            continue
        yy, xx = np.mgrid[12:mask.shape[0]:24, 12:mask.shape[1]:24]
        uv = np.stack([xx.ravel(), yy.ravel()], axis=1)
        uv = uv[mask[uv[:, 1], uv[:, 0]] > 0]
        if not len(uv):
            continue
        distances, indices = cKDTree(np.asarray(observations)).query(uv, k=4)
        neighbors = np.asarray(depths)[indices]
        median = np.median(neighbors, axis=1)
        spread = (neighbors.max(axis=1) - neighbors.min(axis=1)) / np.maximum(median, 1e-6)
        valid = (distances[:, 0] < 360) & (median > .5) & (median < 100)
        uv, distances, neighbors = uv[valid], distances[valid], neighbors[valid]
        if not len(uv):
            continue
        weights = 1 / np.maximum(distances, 5) ** 2
        interpolated = (neighbors * weights).sum(axis=1) / weights.sum(axis=1)
        depth = np.where(spread[valid] > .35, neighbors[:, 0], interpolated)
        camera_xyz = np.column_stack(((uv[:, 0] - intrinsic[0, 2]) / intrinsic[0, 0] * depth,
                                      (uv[:, 1] - intrinsic[1, 2]) / intrinsic[1, 1] * depth,
                                      depth))
        world_xyz = (camera_xyz - pose[:3, 3]) @ pose[:3, :3]
        positions.append(world_xyz.astype(np.float32))
        colors.append(rgb[uv[:, 1], uv[:, 0]])
        sampled.append(image.name)
    if not positions:
        raise ValueError("recorded_environment_depth_missing")
    xyz = np.concatenate(positions)
    rgb = np.concatenate(colors)
    # The room is context, while the face is the editable subject. A dense
    # 48k room seed consumed most splat growth and tablet fill rate. Retain a
    # broad, unbiased 20k sample; measured COLMAP room points stay in place.
    if len(xyz) > 20000:
        selected = np.random.default_rng(72).choice(len(xyz), 20000, replace=False)
        xyz, rgb = xyz[selected], rgb[selected]
    np.savez_compressed(path / "environment_seeds.npz", xyz=xyz, rgb=rgb)
    report = {"sourceViews": len(sampled), "seedPoints": len(xyz),
              "registeredFrames": len(images), "coordinateFrame": "one_unified_colmap_scene",
              "colorsFromRecordedVideo": True}
    (path / "environment_quality.json").write_text(
        json.dumps(report, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return report


def supported_static_surfaces(model, views, masks, rgb_images, output,
                              max_points=22000, max_edge_pixels=80):
    """Observed local triangles, not four-neighbour volume extrapolation.

    ``views`` contains pinhole/undistorted training views in this map's axes.
    Each accepted triangle has measured static vertices; a sample stays
    inside it and must be supported by two other visible room observations.
    Unknown/occluded observations are skipped, not used to carve room.
    These are research-supported surfaces, not independently calibrated truth.
    """
    import cv2
    import numpy as np
    from scipy.spatial import Delaunay

    images={im.name:im for im in model.images.values() if im.has_pose}
    point_map=model.points3D
    candidates={}
    for point_id,point in point_map.items():
        if point.error>2.5 or point.track.length()<3:
            continue
        support=[]
        color=[]
        conflict=0
        for el in point.track.elements:
            im=model.images[el.image_id]
            if im.name not in views:
                continue
            C,K=views[im.name]
            camera=C[:3,:3]@np.asarray(point.xyz)+C[:3,3]
            if camera[2]<=.01:
                continue
            pixel=K@camera; pixel=(pixel[:2]/pixel[2]).round().astype(int)
            u,v=pixel; mask=masks[im.name]
            if not (0<=u<mask.shape[1] and 0<=v<mask.shape[0]):
                continue
            if mask[v,u]:
                support.append(im.name);color.append(rgb_images[im.name][v,u])
            else:
                conflict+=1
        if len(support)>=3 and conflict==0:
            candidates[int(point_id)]=(np.asarray(point.xyz),np.median(color,axis=0),support)
    if len(candidates)<32:
        raise ValueError(f"static_surface_tracks_insufficient:{len(candidates)}")
    positions=[value[0] for value in candidates.values()]
    colors=[value[1] for value in candidates.values()]
    support=[len(value[2]) for value in candidates.values()]
    source_ids=list(candidates)
    source_kind=[0]*len(positions)
    lineage=[(index,index,index) for index in source_ids]
    rejected={"edge":0,"depthSpread":0,"normal":0,"multiView":0}
    names=list(views)
    blurred={name:cv2.GaussianBlur(rgb_images[name],(3,3),0) for name in names}
    for name in names:
        C,K=views[name];mask=masks[name];rgb=rgb_images[name]
        keys=[key for key,val in candidates.items() if name in val[2]]
        if len(keys)<40:
            continue
        xyz=np.stack([candidates[key][0] for key in keys])
        cam=xyz@C[:3,:3].T+C[:3,3]
        uv=cam@K.T;uv=uv[:,:2]/uv[:,2:]
        triangles=Delaunay(uv).simplices
        for tri in triangles:
            pix=uv[tri];world=xyz[tri];depth=cam[tri,2]
            edge=max(np.linalg.norm(pix[i]-pix[j]) for i,j in ((0,1),(1,2),(2,0)))
            if edge>max_edge_pixels or edge<7:
                rejected["edge"]+=1;continue
            if np.ptp(depth)/max(np.median(depth),1e-6)>.06:
                rejected["depthSpread"]+=1;continue
            normal=np.cross(world[1]-world[0],world[2]-world[0])
            norm=np.linalg.norm(normal)
            if norm<1e-8:
                continue
            normal/=norm
            ray=world.mean(0)-np.linalg.inv(C)[:3,3];ray/=np.linalg.norm(ray)
            if abs(normal@ray)<.25:
                rejected["normal"]+=1;continue
            # Barycentric samples remain on measured triangles. No fallback
            # to nearest depth across a wall, person, collar or opening.
            divisions=min(10,max(2,int(edge/9)))
            bary=np.array([(a/divisions,b/divisions,1-(a+b)/divisions)
                for a in range(1,divisions) for b in range(1,divisions-a)],np.float64)
            if not len(bary):
                continue
            pts=bary@world
            votes=np.zeros(len(pts),np.int16);conflict=np.zeros(len(pts),np.int16)
            color_sum=np.zeros((len(pts),3));initial_color=None
            for other in [name]+[n for n in names if n!=name]:
                O,OK=views[other];om=masks[other];orgb=rgb_images[other]
                cp=pts@O[:3,:3].T+O[:3,3]
                pu=cp@OK.T;xy=np.rint(pu[:,:2]/np.maximum(pu[:,2:],1e-8)).astype(int)
                u,v=xy.T
                valid=(cp[:,2]>.01)&(u>=2)&(v>=2)&(u<om.shape[1]-2)&(v<om.shape[0]-2)
                ix=u.clip(0,om.shape[1]-1);iy=v.clip(0,om.shape[0]-1)
                valid &= om[iy,ix]>0
                sampled=blurred[other][iy,ix]
                if initial_color is None:
                    initial_color=sampled.copy()
                agree=np.abs(sampled-initial_color).mean(1)<.10
                # A source core/foreground is not reliable empty room. It
                # cannot vote as static support, but also does not carve it.
                conflict += (valid & ~agree).astype(np.int16)
                votes += (valid & agree).astype(np.int16)
                color_sum += sampled*(valid & agree)[:,None]
            keep=(votes>=3)&(conflict<=1)
            rejected["multiView"]+=int((~keep).sum())
            for idx in np.flatnonzero(keep):
                positions.append(pts[idx]);colors.append(color_sum[idx]/votes[idx]);support.append(int(votes[idx]))
                source_ids.append(len(source_ids));source_kind.append(1)
                lineage.append(tuple(keys[i] for i in tri))
            if len(positions)>=max_points:
                break
        if len(positions)>=max_points:
            break
    data={"xyz":np.asarray(positions,np.float32),"rgb":np.asarray(colors,np.float32),
          "support":np.asarray(support,np.int16),"source_id":np.asarray(source_ids,np.int64),
          "source_kind":np.asarray(source_kind,np.uint8),"triangle_sources":np.asarray(lineage,np.int64)}
    np.savez_compressed(output,**data)
    report={"method":"bounded_static_triangle_surface_and_multiview_photometric_support",
            "measuredStaticPoints":len(candidates),"surfaceSamples":len(positions)-len(candidates),
            "total":len(positions),"trainingViews":names,"rejections":rejected,
            "sourceReliability":{"0":"static_SfM_track_3_views","1":"inside_static_triangle_3_view_support"},
            "lowConfidenceInserted":0,"no360pxExtrapolation":True}
    return data,report


def recover_environment_points(path: Path) -> dict:
    import numpy as np
    import pycolmap

    head = pycolmap.Reconstruction(path / "sparse" / "0")
    face_points = np.asarray([point.xyz for point in head.points3D.values()], dtype=np.float64)
    names = sorted(image.name for image in head.images.values() if image.has_pose)
    if len(names) < 16:
        raise ValueError("environment_cameras_missing")
    masks = make_environment_masks(path, names)
    database = path / "environment_colmap.db"
    database.unlink(missing_ok=True)
    # The face can move slightly relative to the room during recording.
    # Recover the room from its own stable features, then align the two worlds
    # with their common camera frames. Forcing the head poses onto the room
    # produces the disjoint bright fragments seen in the first real test.
    extraction = pycolmap.FeatureExtractionOptions(num_threads=4, max_image_size=1600)
    pycolmap.extract_features(database, path / "frames", image_names=names,
                               camera_mode=pycolmap.CameraMode.SINGLE,
                               reader_options=pycolmap.ImageReaderOptions(mask_path=masks),
                               extraction_options=extraction, device=pycolmap.Device.cpu)
    pycolmap.match_sequential(database, pairing_options=pycolmap.SequentialPairingOptions(
        overlap=18, quadratic_overlap=True, num_threads=4), device=pycolmap.Device.cpu)
    output = path / "environment_sparse"
    output.mkdir(exist_ok=True)
    models = pycolmap.incremental_mapping(database, path / "frames", output)
    if not models:
        raise ValueError("environment_pose_recovery_failed")
    room = max(models.values(), key=lambda value: (value.num_reg_images(), value.num_points3D()))
    common = {}
    head_by_name = {image.name: image for image in head.images.values() if image.has_pose}
    for image in room.images.values():
        if image.has_pose and image.name in head_by_name:
            common[image.name] = (image, head_by_name[image.name])
    if len(common) < max(16, math.ceil(len(names) * .7)) or room.num_points3D() < 600:
        raise ValueError("environment_view_coverage_insufficient")
    # COLMAP's robust Sim(3) alignment uses the same captured frame IDs; it
    # never infers an arbitrary position for a detached background asset.
    alignment = pycolmap.align_reconstructions_via_proj_centers(room, head, .05)
    if alignment is None:
        raise ValueError("environment_head_alignment_failed")
    rotation = np.asarray(alignment.rotation.matrix())
    translation = np.asarray(alignment.translation)
    residuals = np.asarray([
        np.linalg.norm(alignment.scale * rotation @ np.asarray(room_image.projection_center()) +
                       translation - np.asarray(head_image.projection_center()))
        for room_image, head_image in common.values()
    ])
    view = json.loads((path / "portrait.view.json").read_text(encoding="utf-8"))
    target = np.asarray(view["target"], dtype=np.float64)
    front = np.asarray(view["camera"], dtype=np.float64) - target
    front /= np.linalg.norm(front)
    up = np.asarray(view["up"], dtype=np.float64)
    up /= np.linalg.norm(up)
    right = np.cross(up, front)
    right /= np.linalg.norm(right)
    face_local = (face_points - target) @ np.stack([right, up, front], axis=1)
    radii = np.percentile(np.abs(face_local), 92, axis=0)
    radii = np.maximum(radii, .03)
    radii[1] = min(radii[1], radii[0] * 1.55)
    radii[2] = min(radii[2], radii[0] * .9)
    if np.median(residuals) > radii[0] * .12 or np.percentile(residuals, 90) > radii[0] * .25:
        raise ValueError("environment_head_alignment_unstable")
    room.transform(alignment)
    aligned_output = path / "environment_aligned" / "0"
    aligned_output.mkdir(parents=True, exist_ok=True)
    room.write(aligned_output)
    points = list(room.points3D.values())
    xyz = np.asarray([point.xyz for point in points], dtype=np.float64).reshape(-1, 3)
    colors = np.asarray([point.color for point in points], dtype=np.uint8).reshape(-1, 3)
    quality = np.asarray([point.error <= 3. and point.track.length() >= 3
                          for point in points], dtype=bool)
    # Keep all well-triangulated room and clothing seeds. Occlusion is checked
    # on the learned splat footprint at export, not by deleting sparse room
    # structure before optimization.
    kept = quality
    if kept.sum() < 200:
        raise ValueError("environment_geometry_insufficient")
    # Bounded seed density keeps the head the fidelity priority on 8 GB GPUs.
    selected = np.flatnonzero(kept)
    if len(selected) > 20000:
        selected = selected[np.linspace(0, len(selected) - 1, 20000).astype(int)]
    np.savez_compressed(path / "environment_seeds.npz", xyz=xyz[selected].astype(np.float32),
                        rgb=colors[selected], target=target.astype(np.float32),
                        front=front.astype(np.float32), up=up.astype(np.float32),
                        headRadii=radii.astype(np.float32))
    report = {"triangulatedPoints": len(points), "qualityPoints": int(quality.sum()),
              "clearedPoints": int(kept.sum()), "seedPoints": len(selected),
              "registeredFrames": room.num_reg_images(),
              "alignedCommonFrames": len(common),
              "alignmentMedianRelativeHeadWidth": round(float(np.median(residuals) / radii[0]), 4),
              "alignmentP90RelativeHeadWidth": round(float(np.percentile(residuals, 90) / radii[0]), 4),
              "worldCoordinates": "portrait_colmap", "maximumProtectedYawDegrees": 65}
    (path / "environment_quality.json").write_text(json.dumps(report, separators=(",", ":")),
                                                     encoding="utf-8")
    return report

# Prepare-only research path. The legacy supported_static_surfaces above remains
# byte-for-byte unchanged; no caller or production default selects this path.
def surface_source_key(namespace, kind, source_id):
    return (str(namespace), int(kind), str(source_id))


def _surface_token(*parts):
    import hashlib
    return hashlib.sha256('|'.join(map(str, parts)).encode()).hexdigest()


def _surface_point_votes(sampled, valid, reference):
    """Same point-level support/color/conflict rules as the legacy preparer."""
    import numpy as np
    agree = np.abs(sampled-sampled[reference:reference+1]).mean(-1) < .10
    positive = valid & agree; conflict = valid & ~agree
    votes = positive.sum(0); bad = conflict.sum(0)
    colors = (sampled*positive[:, :, None]).sum(0,dtype=np.float64)/np.maximum(votes[:, None], 1)
    return (votes >= 3) & (bad <= 1), votes, bad, colors, positive, conflict


def _surface_bits(mask):
    import numpy as np
    if len(mask) > 64:
        raise ValueError('explicit_multiword_evidence_adapter_required_above_64_views')
    return np.bitwise_or.reduce(mask.astype(np.uint64) *
        np.left_shift(np.uint64(1), np.arange(len(mask), dtype=np.uint64))[:, None], axis=0)


def collect_supported_surface_pool(model, views, masks, rgb_images, original_anchors,
                                   output, *, namespace, max_edge_pixels=80,
                                   wall_seconds=1200, rss_limit_bytes=10*1024**3,
                                   unknown_masks=None, progress=None):
    """Exhaustive OLD-rule proposals; no sampling budget is consulted here.

    Per-origin point evidence is retained. Whole triangles are hypothesis upper
    bounds, not continuous validated surface. No near-coordinate geometry merge.
    """
    import cv2
    import json
    import math
    import resource
    import time
    import numpy as np
    from scipy.spatial import Delaunay
    output = Path(output)
    if output.exists(): raise ValueError('never_overwrite_candidate_pool')
    output.mkdir(parents=True)
    start = time.perf_counter(); names = sorted(views); completed = []
    if set(names) != set(masks) or set(names) != set(rgb_images):
        raise ValueError('candidate_inputs_must_be_train_only_same_names')
    if len(names) > 64: raise ValueError('evidence_bitmap_capacity_not_silent_truncation')
    def checkpoint(stage):
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024
        if time.perf_counter()-start > wall_seconds or rss > rss_limit_bytes:
            state = {'complete':False,'stage':stage,'completedViews':completed,
                     'elapsed':time.perf_counter()-start,'peakRssBytes':rss,
                     'reason':'explicit_resource_limit_no_completed_pool'}
            (output/'incomplete.json').write_text(json.dumps(state,indent=2))
            raise RuntimeError('candidate_enumeration_incomplete:'+stage)
    try:
        # Retain native point-map iteration for the same Delaunay tie convention.
        images = {im.name:im for im in model.images.values() if im.has_pose}
        candidates = {}; anchor_reject = {'trackOrError':0,'supportOrConflict':0}
        for point_id,point in model.points3D.items():
            if point.error > 2.5 or point.track.length() < 3:
                anchor_reject['trackOrError'] += 1; continue
            support=[]; color=[]; conflict=0
            for element in point.track.elements:
                im=model.images[element.image_id]
                if im.name not in views: continue
                C,K=views[im.name]; camera=C[:3,:3]@np.asarray(point.xyz)+C[:3,3]
                if camera[2] <= .01: continue
                pixel=K@camera; u,v=(pixel[:2]/pixel[2]).round().astype(int); mask=masks[im.name]
                if not (0<=u<mask.shape[1] and 0<=v<mask.shape[0]):continue
                if mask[v,u]:support.append(im.name);color.append(rgb_images[im.name][v,u])
                else:conflict+=1
            if len(support)>=3 and conflict==0:
                candidates[int(point_id)]=(np.asarray(point.xyz),np.median(color,axis=0),support)
            else:anchor_reject['supportOrConflict']+=1
        expected = original_anchors['source_id'].tolist()
        if set(candidates) != set(expected): raise ValueError('old_anchor_selection_changed')
        for i,key in enumerate(expected):
            xyz,rgb,_=candidates[key]
            if not np.array_equal(xyz.astype(np.float32),original_anchors['xyz'][i]) or not np.array_equal(rgb.astype(np.float32),original_anchors['rgb'][i]):
                raise ValueError('old_anchor_geometry_or_color_changed:'+str(key))
        if len(candidates)<32:raise ValueError('static_surface_tracks_insufficient')
        blurred={name:cv2.GaussianBlur(rgb_images[name],(3,3),0) for name in names}
        per_view={}; surfaces={}; proposal_rows=[]
        # Collect every triangle proposal FIRST, irrespective of sample budget.
        for name in names:
            checkpoint('triangles:'+name)
            C,K=views[name]; keys=[key for key,val in candidates.items() if name in val[2]]
            counts=dict(raw=0,edge=0,depthSpread=0,degenerate=0,normal=0,noInteriorSamples=0,geometryAccepted=0)
            if len(keys)>=40:
                xyz=np.stack([candidates[key][0] for key in keys]); cam=xyz@C[:3,:3].T+C[:3,3]
                uv=cam@K.T;uv=uv[:,:2]/uv[:,2:]
                for tri in Delaunay(uv).simplices:
                    counts['raw']+=1; pix=uv[tri];world=xyz[tri];depth=cam[tri,2]
                    ids=tuple(keys[int(i)] for i in tri);canonical=tuple(sorted(ids))
                    sid=_surface_token(namespace,1,*canonical)
                    edge=max(np.linalg.norm(pix[i]-pix[j]) for i,j in ((0,1),(1,2),(2,0)))
                    spread=float(np.ptp(depth)/max(np.median(depth),1e-6))
                    normal=np.cross(world[1]-world[0],world[2]-world[0]);norm=np.linalg.norm(normal)
                    normal=normal/max(norm,1e-30)
                    ray=world.mean(0)-np.linalg.inv(C)[:3,3];ray/=np.linalg.norm(ray)
                    cosine=float(abs(normal@ray));divisions=min(10,max(2,int(edge/9)))
                    reason=('edge' if edge>max_edge_pixels or edge<7 else
                            'depthSpread' if spread>.06 else 'degenerate' if norm<1e-8 else
                            'normal' if cosine<.25 else 'noInteriorSamples' if divisions<3 else 'geometryAccepted')
                    counts[reason]+=1
                    record={'view':name,'surfaceId':sid,'orderedPointIds':ids,'normal':normal.tolist(),
                            'edge':float(edge),'depthSpread':spread,'cosine':cosine,'divisions':divisions,'firstDecision':reason}
                    proposal_rows.append(record)
                    if reason!='geometryAccepted':continue
                    stat='newGeometrySurface' if sid not in surfaces else 'repeatedGeometrySurface'
                    counts[stat]=counts.get(stat,0)+1
                    if sid not in surfaces:
                        surfaces[sid]={'ids':canonical,'proposals':[]}
                    surfaces[sid]['proposals'].append(record)
            per_view[name]=counts;completed.append(name)
            if progress:progress('triangles',name,counts)
        # The pool is not complete until point-level evidence is also evaluated.
        checkpoint('point-evidence-start')
        by_name={n:i for i,n in enumerate(names)};Cs=np.stack([views[n][0] for n in names]);Ks=np.stack([views[n][1] for n in names])
        wh=np.array([[masks[n].shape[1],masks[n].shape[0]] for n in names])
        points=[];surface_records=[];sample_evidence_count=0
        evidence_stream=(output/'sample-evidence.jsonl').open('w')
        for si,(sid,element) in enumerate(sorted(surfaces.items())):
            if si%64==0:checkpoint('point-evidence:'+str(si))
            proposals=element['proposals'];canonical=element['ids']
            world=np.stack([candidates[k][0] for k in canonical])
            # Exact rational barycentric identities merge the same sample across
            # different source ordering/divisions without Euclidean near merging.
            domain={}
            for pr in proposals:
                div=pr['divisions'];order=[canonical.index(i) for i in pr['orderedPointIds']]
                for a in range(1,div):
                    for b in range(1,div-a):
                        ints=[0,0,0]
                        for j,value in zip(order,[a,b,div-a-b]):ints[j]=value
                        divisor=math.gcd(math.gcd(*ints[:2]),ints[2]);key=tuple(i//divisor for i in ints)
                        domain.setdefault(key,[]).append(pr)
            keys=sorted(domain);bary=np.array([np.array(k)/sum(k) for k in keys]);xyz=bary@world
            cp=np.einsum('vij,pj->vpi',Cs[:,:3,:3],xyz)+Cs[:,:3,3,None].transpose(0,2,1)
            pu=np.einsum('vij,vpj->vpi',Ks,cp);xy=np.rint(pu[:,:,:2]/np.maximum(pu[:,:,2:],1e-8)).astype(np.int64)
            sampled=[];valid=[];unknown=[];excluded=[]
            for vi,n in enumerate(names):
                u,v=xy[vi].T;om=masks[n];ix=u.clip(0,om.shape[1]-1);iy=v.clip(0,om.shape[0]-1)
                inside=(cp[vi,:,2]>.01)&(u>=2)&(v>=2)&(u<om.shape[1]-2)&(v<om.shape[0]-2)
                valid.append(inside&(om[iy,ix]>0));sampled.append(blurred[n][iy,ix])
                unknown.append(inside&unknown_masks[n][iy,ix] if unknown_masks is not None else np.zeros(len(keys),bool))
                excluded.append(inside&~om[iy,ix].astype(bool))
            sampled=np.stack(sampled);valid=np.stack(valid);unknown=np.stack(unknown);excluded=np.stack(excluded)
            unknown_bits=_surface_bits(unknown);excluded_bits=_surface_bits(excluded)
            by_origin={}
            for pr in proposals:by_origin.setdefault(pr['view'],pr)
            evaluations={}
            for origin in sorted(by_origin):
                evaluations[origin]=_surface_point_votes(sampled,valid,by_name[origin])
            valid_count=0
            for pi,key in enumerate(keys):
                pid=_surface_token(namespace,1,sid,*key);best=None;legal_origins=[]
                for pr in sorted(domain[key],key=lambda r:r['view']):
                    origin=pr['view'];keep,votes,bad,colors,positive,conflicts=evaluations[origin]
                    support_bits=int(_surface_bits(positive[:,pi:pi+1])[0]);conflict_bits=int(_surface_bits(conflicts[:,pi:pi+1])[0])
                    evidence={'pointId':pid,'surfaceId':sid,'origin':origin,
                        'divisions':pr['divisions'],'baryNumerator':key,'accepted':bool(keep[pi]),
                        'supportBits':support_bits,'conflictBits':conflict_bits,
                        'unknownBits':int(unknown_bits[pi]),'maskExcludedBits':int(excluded_bits[pi]),
                        'rejectionLabels':(['votes<3'] if votes[pi]<3 else [])+(['conflict>1'] if bad[pi]>1 else [])}
                    evidence_stream.write(json.dumps(evidence,separators=(',',':'))+'\n');sample_evidence_count+=1
                    tally=per_view[origin];tally['sampleProposals']=tally.get('sampleProposals',0)+1
                    stat='sampleAccepted' if keep[pi] else 'sampleRejected'
                    tally[stat]=tally.get(stat,0)+1
                    if not keep[pi]:continue
                    legal_origins.append(origin)
                    rank=(-int(votes[pi]),int(bad[pi]),origin)
                    if best is None or rank<best[0]:
                        best=(rank,colors[pi],int(votes[pi]),support_bits,conflict_bits,pr)
                if best is None:continue
                valid_count+=1;pr=best[5]
                points.append({'pointId':pid,'surfaceId':sid,'xyz':xyz[pi].tolist(),'rgb':best[1].tolist(),
                    'support':best[2],'supportBits':best[3],'conflictBits':best[4],
                    'unknownBits':int(unknown_bits[pi]),'maskExcludedBits':int(excluded_bits[pi]),
                    'triangleSources':pr['orderedPointIds'],'canonicalPointIds':canonical,'baryNumerator':key,
                    'origin':pr['view'],'acceptedOrigins':sorted(set(legal_origins))})
            surface_records.append({'surfaceId':sid,'canonicalPointIds':canonical,'domainUniquePoints':len(keys),'legalPoints':valid_count,
                'proposals':[{'view':q['view'],'orderedPointIds':q['orderedPointIds'],'normal':q['normal'],'divisions':q['divisions']} for q in proposals],
                'orientation':'same immutable map vertices; opposite winding retained, two-sided surface hypothesis'})
            if progress and si%512==0:progress('samples',str(si),{'uniqueLegalSamples':len(points)})
        evidence_stream.close()
        checkpoint('complete')
        points.sort(key=lambda p:p['pointId'])
        for point in points:
            origin=point['acceptedOrigins'][0]
            per_view[origin]['firstLegalPointEvidence']=per_view[origin].get('firstLegalPointEvidence',0)+1
        usable=sum(r['legalPoints']>0 for r in surface_records)
        report={'complete':True,'namespace':namespace,'trainingViews':names,'completedViews':completed,
            'anchorCount':len(candidates),'anchorRejected':anchor_reject,'proposalCount':len(proposal_rows),
            'geometryUniqueSurfaces':len(surfaces),'usableUniqueSurfaces':usable,'legalUniqueSamples':len(points),
            'sampleEvidenceRows':sample_evidence_count,'perView':per_view,
            'rejectionSemantics':'triangle first rejection; point keep requires votes>=3 and conflict<=1; never missing surface area',
            'thresholds':{'trackErrorMax':2.5,'trackViewsMin':3,'anchorConflictMax':0,'edge':[7,max_edge_pixels],
                'relativeDepthSpreadMax':.06,'absNormalRayMin':.25,'sampleColorL1StrictMax':.10,'sampleVotesMin':3,'sampleConflictsMax':1},
            'seconds':time.perf_counter()-start,'peakRssBytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
            'randomness':'none; exact rational grids and stable IDs; sorted view evaluation',
            'surfaceHypothesesNotDepthTruth':True}
        for file,items in [('triangle-proposals.jsonl',proposal_rows),('surfaces.jsonl',surface_records),('legal-samples.jsonl',points)]:
            with (output/file).open('w') as stream:
                for row in items:stream.write(json.dumps(row,separators=(',',':'))+'\n')
        (output/'summary.json').write_text(json.dumps(report,indent=2))
        anchor_evidence={str(k):sorted(v[2]) for k,v in candidates.items()}
        (output/'anchor-evidence.json').write_text(json.dumps(anchor_evidence))
        return {'points':points,'surfaces':surface_records,'report':report,'anchorEvidence':anchor_evidence}
    except Exception as error:
        if 'evidence_stream' in locals():evidence_stream.close()
        if not (output/'incomplete.json').exists():
            (output/'incomplete.json').write_text(json.dumps({'complete':False,'error':repr(error),'completedViews':completed,'seconds':time.perf_counter()-start},indent=2))
        raise


def allocate_surface_pool(pool, anchors, views, masks, *, namespace, max_points,
                          retained_surfaces=(), coarse_pixels=32, fine_pixels=4, wall_seconds=600):
    """Deterministic lazy marginal-coverage greedy; only training observations.

    The world cells are an allocation aid, not new geometry. No repeated filling
    after both projected and spatial novelty are exhausted.
    """
    import heapq
    import time
    import numpy as np
    from scipy.spatial import cKDTree
    if not pool['report']['complete']:raise ValueError('incomplete_pool_cannot_allocate')
    if set(views)!=set(pool['report']['trainingViews']):raise ValueError('allocation_views_differ_from_train_pool')
    nanchor=len(anchors['xyz']);budget=max_points-nanchor
    if budget<0:raise ValueError('budget_cannot_drop_original_anchors')
    started=time.perf_counter()
    points=pool['points'];names=pool['report']['trainingViews'];N=len(points)
    xyz=np.array([p['xyz'] for p in points]).reshape(-1,3)
    spatial_step=float(np.median(cKDTree(anchors['xyz']).query(anchors['xyz'],k=2)[0][:,1]))
    spatial_step=max(spatial_step,1e-6)
    world_keys=[tuple(x) for x in np.floor(xyz/spatial_step).astype(np.int64)]
    seen_world=set(tuple(x) for x in np.floor(anchors['xyz']/spatial_step).astype(np.int64))
    def projection_cells(values, require_support):
        result=[[] for _ in range(len(values))];fine=[[] for _ in range(len(values))];co=0;fi=0
        for vi,name in enumerate(names):
            C,K=views[name];cam=values@C[:3,:3].T+C[:3,3];uv=cam@K.T;uv=uv[:,:2]/np.maximum(uv[:,2:],1e-8)
            u,v=np.rint(uv).astype(np.int64).T;h,w=masks[name].shape
            ok=(cam[:,2]>.01)&(u>=0)&(v>=0)&(u<w)&(v<h)
            inside=np.flatnonzero(ok);ok[inside]&=masks[name][v[inside],u[inside]].astype(bool)
            if require_support:ok &= np.array([(p['supportBits']>>vi)&1 for p in points],bool)
            cw=(w+coarse_pixels-1)//coarse_pixels;fw=(w+fine_pixels-1)//fine_pixels
            for j in np.flatnonzero(ok):
                result[j].append(co+(v[j]//coarse_pixels)*cw+u[j]//coarse_pixels)
                fine[j].append(fi+(v[j]//fine_pixels)*fw+u[j]//fine_pixels)
            co+=cw*((h+coarse_pixels-1)//coarse_pixels);fi+=fw*((h+fine_pixels-1)//fine_pixels)
        return [np.asarray(r,np.int64) for r in result],[np.asarray(r,np.int64) for r in fine],co,fi
    coarse,fine,nc,nf=projection_cells(xyz,True)
    ac,af,_,_=projection_cells(anchors['xyz'],False)
    covered_c=np.zeros(nc,bool);covered_f=np.zeros(nf,bool)
    for c,f in zip(ac,af):covered_c[c]=True;covered_f[f]=True
    selected=[];is_selected=np.zeros(N,bool);gains=[]
    xyz_keys=[row.astype(np.float32).tobytes() for row in xyz]
    seen_xyz={row.astype(np.float32).tobytes() for row in anchors['xyz']}
    def score(i):
        if xyz_keys[i] in seen_xyz:return 0,0,0,0
        c=int((~covered_c[coarse[i]]).sum());f=int((~covered_f[fine[i]]).sum());novel=world_keys[i] not in seen_world
        return 4*c+f+4*int(novel),c,f,int(novel)
    def take(i,reason):
        s,c,f,v=score(i)
        if not s:return False
        selected.append(i);is_selected[i]=True;covered_c[coarse[i]]=True;covered_f[fine[i]]=True;seen_world.add(world_keys[i]);seen_xyz.add(xyz_keys[i])
        gains.append((i,c,f,v,reason));return True
    # Retain old supported domains before allocating new marginal coverage.
    groups={}
    for i,point in enumerate(points):groups.setdefault(point['surfaceId'],[]).append(i)
    retained_missing=[]
    for sid in sorted(set(retained_surfaces)):
        options=groups.get(sid,[])
        if not options:retained_missing.append(sid);continue
        if len(selected)>=budget:break
        best=max(options,key=lambda i:(score(i)[0],-i))
        take(best,'old-domain')
    heap=[(-score(i)[0],i) for i in range(N) if not is_selected[i]];heapq.heapify(heap)
    while heap and len(selected)<budget:
        if time.perf_counter()-started>wall_seconds:raise RuntimeError('allocation_incomplete_resource_limit')
        upper,i=heapq.heappop(heap);current=score(i)[0]
        if current==0:continue
        if heap and -current>heap[0][0]:heapq.heappush(heap,(-current,i));continue
        take(i,'marginal-coverage')
    selected.sort(key=lambda i:points[i]['pointId'])
    chosen=[points[i] for i in selected]
    arr=lambda key,dtype:np.asarray([q[key] for q in chosen],dtype=dtype)
    sample_source=np.array([int(p['pointId'][:16],16)&((1<<63)-1) for p in chosen],np.int64)
    if len(np.unique(sample_source))!=len(sample_source):raise ValueError('stable_sample_source_id_collision')
    anchor_bits=np.array([sum(1<<names.index(n) for n in pool['anchorEvidence'][str(int(i))]) for i in anchors['source_id']],np.uint64)
    data={'xyz':np.concatenate([anchors['xyz'],arr('xyz',np.float32).reshape(-1,3)]),
          'rgb':np.concatenate([anchors['rgb'],arr('rgb',np.float32).reshape(-1,3)]),
          'support':np.concatenate([anchors['support'],arr('support',np.int16)]),
          'source_kind':np.concatenate([anchors['source_kind'],np.ones(len(chosen),np.uint8)]),
          'source_id':np.concatenate([anchors['source_id'],sample_source]),
          'triangle_sources':np.concatenate([anchors['triangle_sources'],arr('triangleSources',np.int64).reshape(-1,3)]),
          'surface_id':np.array(['']*nanchor+[q['surfaceId'] for q in chosen]),
          'point_id':np.array([_surface_token(namespace,0,int(i)) for i in anchors['source_id']]+[q['pointId'] for q in chosen]),
          'canonical_point_ids':np.concatenate([np.repeat(anchors['source_id'][:,None],3,axis=1),arr('canonicalPointIds',np.int64).reshape(-1,3)]),
          'sample_bary_numerator':np.concatenate([np.zeros((nanchor,3),np.int16),arr('baryNumerator',np.int16).reshape(-1,3)]),
          'sample_origin':np.array(['static-track']*nanchor+[q['origin'] for q in chosen]),
          'support_bits':np.concatenate([anchor_bits,arr('supportBits',np.uint64)]),
          'conflict_bits':np.concatenate([np.zeros(nanchor,np.uint64),arr('conflictBits',np.uint64)]),
          'unknown_bits':np.concatenate([np.zeros(nanchor,np.uint64),arr('unknownBits',np.uint64)]),
          'mask_excluded_bits':np.concatenate([np.zeros(nanchor,np.uint64),arr('maskExcludedBits',np.uint64)]),
          'evidence_scope':np.concatenate([np.zeros(nanchor,np.uint8),np.ones(len(chosen),np.uint8)])}
    report={'budget':max_points,'anchors':nanchor,'selectedSamples':len(chosen),'total':len(data['xyz']),
        'unusedBudget':max_points-len(data['xyz']),'legalPoolSamples':N,'notSelectedSamples':N-len(chosen),
        'selectedUniqueSurfaces':len(set(q['surfaceId'] for q in chosen)),
        'oldSurfaceIdsAbsentFromLegalPool':retained_missing,'coveredCoarseCells':int(covered_c.sum()),'coveredFineCells':int(covered_f.sum()),
        'coarsePixels':coarse_pixels,'finePixels':fine_pixels,'worldCellSize':spatial_step,
        'score':'4*newCoarseCells + newFineCells + 4*newWorldCell; overlap has zero marginal gain',
        'uniqueXYZ':len(np.unique(data['xyz'],axis=0)), 'trainOnly':True,'selectedPointIds':[q['pointId'] for q in chosen],
        'exactCoordinateDuplicatesNotReallocated':True,'geometryMerging':False,
        'sampleGains':gains,'defaultLegacyUnchanged':True}
    return data,report
