"""Read our tensor/NumPy checkpoint schema without arbitrary pickle execution."""
from pathlib import Path
import hashlib
import numpy as np
import torch


def file_sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def load_checkpoint(path, *, expected_hash=None, device='cpu'):
    path = Path(path)
    if expected_hash is not None and file_sha256(path) != expected_hash:
        raise ValueError('checkpoint_hash_changed')
    allowed_names = {'numpy.ndarray', 'numpy.dtype',
                     'numpy._core.multiarray._reconstruct', 'numpy._core.multiarray.scalar'}
    unexpected = set(torch.serialization.get_unsafe_globals_in_checkpoint(path)) - allowed_names
    if unexpected:
        raise ValueError('unsupported_checkpoint_globals:' + ','.join(sorted(unexpected)))
    types = ('int8', 'int16', 'int32', 'int64', 'uint8', 'uint16', 'uint32',
             'uint64', 'float16', 'float32', 'float64', 'bool', 'str', 'bytes',
             'object', 'complex64', 'complex128')
    allowed = [np._core.multiarray._reconstruct, np._core.multiarray.scalar, np.ndarray, np.dtype]
    allowed += [type(np.dtype(t)) for t in types]
    with torch.serialization.safe_globals(allowed):
        result = torch.load(path, map_location=device, weights_only=True)
    if not isinstance(result, dict) or 'model' not in result:
        raise ValueError('checkpoint_schema_missing_model')
    return result


def restore_tensors(module, saved):
    """Resize only declared topology tensors, then require an exact full restore."""
    current = module.state_dict()
    if current.keys() != saved.keys():
        raise ValueError('checkpoint_fields_differ:' + str(sorted(current.keys() ^ saved.keys())))
    parameters = dict(module.named_parameters())
    buffers = dict(module.named_buffers())
    for name, value in saved.items():
        if not isinstance(value, torch.Tensor) or current[name].dtype != value.dtype:
            raise ValueError('checkpoint_type_changed:' + name)
        if current[name].shape != value.shape:
            parent, _, leaf = name.rpartition('.')
            owner = module.get_submodule(parent) if parent else module
            if name in parameters:
                setattr(owner, leaf, torch.nn.Parameter(torch.empty_like(value),
                        requires_grad=parameters[name].requires_grad))
            elif name in buffers:
                setattr(owner, leaf, torch.empty_like(value))
            else:
                raise ValueError('undeclared_checkpoint_tensor:' + name)
    module.load_state_dict(saved, strict=True)
    if any(not torch.equal(value, module.state_dict()[name]) for name, value in saved.items()):
        raise ValueError('checkpoint_restore_not_exact')
