"""Protect reliable observed empty regions without treating unknown as empty."""
import torch

def extra_foreground_loss(current,baseline,reliable_empty):
    if current.shape!=baseline.shape or current.shape!=reliable_empty.shape or reliable_empty.dtype!=torch.bool:
        raise ValueError('foreground_observation_contract')
    error=(current-baseline.detach()).clamp_min(0).square()
    return error[reliable_empty].mean() if reliable_empty.any() else current.sum()*0