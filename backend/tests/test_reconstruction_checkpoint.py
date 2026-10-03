import tempfile
import unittest
from pathlib import Path
import numpy as np
import torch
from reconstruction_checkpoint import load_checkpoint,restore_tensors,file_sha256


class UnknownGlobal:
    def __reduce__(self):return len,('untrusted schema',)


class CheckpointTests(unittest.TestCase):
    def test_safe_numpy_and_tensor_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'model.pt'
            torch.save({'model':{'a':torch.tensor([1.,2.])},'extra':{'parts':np.array([1,4],np.int16)}},path)
            actual=load_checkpoint(path,expected_hash=file_sha256(path))
            self.assertTrue(torch.equal(actual['model']['a'],torch.tensor([1.,2.])))
            np.testing.assert_array_equal(actual['extra']['parts'],[1,4])

    def test_numpy_sampler_scalar_is_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'sampler.pt'
            torch.save({'model':{},'sampler':{'remaining':[np.str_('frame_1')],
                'value':np.float32(.25)}},path)
            actual=load_checkpoint(path,expected_hash=file_sha256(path))
            self.assertEqual(actual['sampler']['remaining'][0],'frame_1')
            self.assertEqual(float(actual['sampler']['value']),.25)

    def test_unapproved_global_is_not_executed(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'unknown.pt'
            torch.save({'model':{},'extra':UnknownGlobal()},path)
            with self.assertRaisesRegex(ValueError,'unsupported_checkpoint_globals'):
                load_checkpoint(path,expected_hash=file_sha256(path))

    def test_hash_change_is_rejected_before_loading(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'invalid.pt';path.write_bytes(b'not a checkpoint')
            with self.assertRaisesRegex(ValueError,'checkpoint_hash_changed'):
                load_checkpoint(path,expected_hash='0'*64)

    def test_restore_requires_every_declared_field(self):
        module=torch.nn.Module();module.register_buffer('source_uid',torch.tensor([2,3]))
        with self.assertRaisesRegex(ValueError,'checkpoint_fields_differ'):
            restore_tensors(module,{})
        with self.assertRaisesRegex(ValueError,'checkpoint_type_changed'):
            restore_tensors(module,{'source_uid':torch.tensor([2.,3.])})

    def test_restore_topology_preserves_parameter_and_buffer_roles(self):
        module=torch.nn.Module();module.weight=torch.nn.Parameter(torch.zeros(2,3),requires_grad=False)
        module.register_buffer('source_uid',torch.tensor([2,3]))
        saved={'weight':torch.arange(12,dtype=torch.float32).reshape(4,3),'source_uid':torch.tensor([2,3,6,7])}
        restore_tensors(module,saved)
        self.assertFalse(module.weight.requires_grad)
        self.assertIn('weight',dict(module.named_parameters()))
        self.assertIn('source_uid',dict(module.named_buffers()))
        for name,value in saved.items():self.assertTrue(torch.equal(module.state_dict()[name],value))


if __name__=='__main__':unittest.main()
