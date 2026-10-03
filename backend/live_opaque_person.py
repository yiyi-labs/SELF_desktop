"""Observed opaque interiors for a person in the common scene composition.

This is a training contract, not a display filter. A room point cannot satisfy
person coverage. Conditional colour separates source radiance from accumulated
transmittance; original premultiplied RGB remains supervised by the caller.
Hair, lenses, unknown pixels and part boundaries are not forced opaque.
"""
from dataclasses import dataclass, asdict
import cv2
import numpy as np
import torch


@dataclass(frozen=True)
class OpaquePersonConfig:
    # Fixed before any comparison; these are auxiliary to existing RGB losses.
    transmission_weight: float = .2
    colour_weight: float = .35
    structure_weight: float = .08
    erosion_width_fraction: float = .005
    minimum_erosion_pixels: int = 1
    maximum_erosion_pixels: int = 8
    conditional_min_contribution: float = .02
    numerical_epsilon: float = 1e-5


DEFAULT_CONFIG = OpaquePersonConfig()


def _cpu_bool(value):
    if isinstance(value, torch.Tensor):
        value = value.detach().cpu().numpy()
    return np.asarray(value, dtype=bool)


def prepare_opaque_interiors(labels, config=DEFAULT_CONFIG):
    """Prepare once per observation, on its native uncropped pixel grid.

    Existing observed semantic labels provide confidence/exclusion evidence.
    Missing observations stay empty. Erosion radius/counts are recorded; it
    changes the extra loss support only, never clips or deletes any geometry.
    """
    required = ('hair_visible', 'glasses_visible', 'unknown_or_occluded')
    if any(key not in labels for key in required):
        raise ValueError('opaque_person_missing_exclusion_observation')
    protected = [_cpu_bool(labels[key]) for key in required]
    shape = protected[0].shape
    if len(shape) != 2 or any(mask.shape != shape for mask in protected):
        raise ValueError('opaque_person_native_mask_shape')
    exclude = np.logical_or.reduce(protected)
    inputs = {'skin': 'training_skin', 'cloth': 'observed_cloth',
              'body_skin': 'observed_body_skin'}
    masks = {}
    receipt = {}
    claimed = np.zeros(shape, bool)
    for name, key in inputs.items():
        observed = _cpu_bool(labels[key]) if key in labels else np.zeros(shape, bool)
        if observed.shape != shape:
            raise ValueError('opaque_person_native_mask_shape:' + key)
        # Different physical semantic regions cannot double-count a pixel.
        valid = observed & ~exclude & ~claimed
        claimed |= observed
        y, x = np.where(valid)
        radius = (max(config.minimum_erosion_pixels,
                      min(config.maximum_erosion_pixels,
                          int(round((x.max()-x.min()+1)*config.erosion_width_fraction))))
                  if len(x) else 0)
        interior = (cv2.erode(valid.astype(np.uint8), np.ones((2*radius+1, 2*radius+1), np.uint8),
                              borderType=cv2.BORDER_CONSTANT, borderValue=0).astype(bool)
                    if radius else valid.copy())
        masks['opaque_' + name] = interior
        receipt[name] = dict(source=key, sourceAvailable=key in labels,
                             observedPixels=int(observed.sum()),
                             exclusionPixels=int((observed & exclude).sum()),
                             eligibleBeforeErosion=int(valid.sum()),
                             erosionRadiusNativePixels=radius,
                             opaqueInteriorPixels=int(interior.sum()))
    return masks, {'config': asdict(config), 'regions': receipt,
                   'interpretation': 'observed_opaque_interiors_not_complete_silhouette',
                   'partIds': [1, 4], 'nativeShape': list(shape),
                   'changesGeometryOrPublishedMasks': False}


def person_rgb_features(rgb, parts):
    """Three extra raster channels, using the SAME ordering/transmittance.

    1 is the retained FLAME skin/detail layer (including neck), 4 the measured
    body/cloth layer. Actual lens observations are excluded by the masks.
    Components 0=room, 2=hair, 3=accessory do not fill opaque skin/cloth coverage.
    """
    if rgb.ndim != 2 or rgb.shape[1] != 3 or parts.shape != (len(rgb),):
        raise ValueError('opaque_person_feature_shape')
    return rgb * ((parts == 1) | (parts == 4))[:, None].to(rgb.dtype)


def conditional_person_colour(rendered, config=DEFAULT_CONFIG):
    if 'person_rgb' not in rendered or 'q' not in rendered:
        raise ValueError('opaque_person_requires_common_composite_rgb_and_q')
    contribution = rendered['q'][..., 1] + rendered['q'][..., 4]
    rgb = rendered['person_rgb']
    if rgb.shape != (*contribution.shape, 3):
        raise ValueError('opaque_person_render_shape')
    # The denominator is NOT detached: colour gradients must not reward
    # becoming transparent. Coverage has its own, separate objective.
    conditional = rgb / contribution.clamp_min(config.conditional_min_contribution)[..., None]
    return conditional, contribution


def observed_structure_error(prediction, target, mask):
    """Native first differences, only within one observed physical region.

    No sharpened target, fabricated mask-edge contrast or feature hallucination.
    Regions stay separate, so cloth/skin and lips/background are never bridged.
    """
    zero = prediction.sum()*0
    terms = []
    for axis in (0, 1):
        valid = (mask[1:] & mask[:-1]) if axis == 0 else (mask[:, 1:] & mask[:, :-1])
        if valid.any():
            delta = (prediction.diff(dim=axis)-target.diff(dim=axis)).abs().mean(-1)
            terms.append(delta[valid].mean())
    return torch.stack(terms).mean() if terms else zero


def opaque_person_loss(rendered, frame, *, scope='head', config=DEFAULT_CONFIG):
    """Add to (not replace) the existing full-frame RGB/geometry objectives.

    Caller must precompute opaque masks in the native labels. Full projection
    then ROI slicing applies to these masks exactly as to RGB. Scope 'head' is
    T0 skin; scope 'body' is T3 only where its motion observation is valid. Every opaque
    pixel participates in transmission, including missing pixels. Conditional
    colour cannot be inferred without any contribution; these pixels retain
    the caller's original RGB error plus this coverage loss.
    """
    conditional, contribution = conditional_person_colour(rendered, config)
    target = frame['rgb']
    labels = frame['masks']
    if target.shape != conditional.shape:
        raise ValueError('opaque_person_target_shape')
    if scope not in ('head', 'body', 'person'):
        raise ValueError('opaque_person_unknown_scope')
    names = {'head': ('skin',), 'body': ('cloth', 'body_skin'),
             'person': ('skin', 'cloth', 'body_skin')}[scope]
    terms = []
    details = {}
    for name in names:
        key = 'opaque_' + name
        if key not in labels:
            raise ValueError('opaque_person_masks_not_prepared:' + key)
        mask = torch.as_tensor(labels[key], device=target.device, dtype=torch.bool)
        if mask.shape != contribution.shape:
            raise ValueError('opaque_person_mask_render_shape:' + key)
        if not mask.any():
            details[name] = dict(pixels=0, conditionalPixels=0)
            continue
        q = contribution[mask]
        # -log(eps+(1-eps)*q) has a finite, useful gradient at q=0.
        # No opacity, point scale or geometry is clamped to force acceptance.
        transmission = -(config.numerical_epsilon + (1-config.numerical_epsilon)*q).log().mean()
        visible = mask & (contribution.detach() >= config.conditional_min_contribution)
        colour = ((conditional[visible]-target[visible]).abs().mean()
                  if visible.any() else conditional.sum()*0)
        structure = observed_structure_error(conditional, target, visible)
        loss = (config.transmission_weight*transmission + config.colour_weight*colour
                + config.structure_weight*structure)
        terms.append(loss)
        details[name] = dict(pixels=int(mask.sum()), conditionalPixels=int(visible.sum()),
                             transmission=float(transmission.detach()),
                             conditionalRgbL1=float(colour.detach()),
                             nativeStructureL1=float(structure.detach()),
                             meanPersonContribution=float(q.detach().mean()),
                             lowPersonContributionFraction=float((q.detach()<.95).float().mean()))
    return (torch.stack(terms).mean() if terms else rendered['person_rgb'].sum()*0), details
