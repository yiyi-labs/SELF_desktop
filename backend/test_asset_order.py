import tempfile,unittest
from pathlib import Path
import numpy as np,torch
from reconstruction_asset_order import replace_rows,appended_to_original,permute_float_ply
from reconstruction_portrait_model import GaussianState

def state(x,parts):
    n=len(x);return GaussianState(x,torch.tensor([[1.,0,0,0]]).repeat(n,1),torch.ones(n,3),torch.ones(n)*.5,torch.zeros(n,4,3),torch.tensor(parts))

class OrderContractTests(unittest.TestCase):
    def test_gradient_and_other_rows(self):
        x=torch.arange(15.,requires_grad=True).reshape(5,3);p=torch.ones(2,3,requires_grad=True)
        a=state(x,[0,1,2,1,4]);b=state(p,[1,1]);s=replace_rows(a,b,[3,1])
        torch.testing.assert_close(s.means[[0,2,4]],x[[0,2,4]])
        s.means.sum().backward();torch.testing.assert_close(p.grad,torch.ones_like(p))
        self.assertTrue(torch.equal(s.parts,a.parts))
    def test_invalid_scope(self):
        a=state(torch.zeros(3,3),[0,1,2]);b=state(torch.zeros(2,3),[1,1])
        for rows in ([1,1],[1,3],[0,1]):
            with self.assertRaises(ValueError):replace_rows(a,b,rows)
    def test_exact_binary_fields_and_permutation(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'a.ply';target=root/'b.ply'
            v=np.array([[1.,-.2,np.inf],[2.,-3.,np.nan],[4.,5.,-6.]],dtype='<f4')
            source.write_bytes(b'ply\nformat binary_little_endian 1.0\nelement vertex 3\nproperty float x\nproperty float opacity\nproperty float f_dc_0\nend_header\n'+v.tobytes())
            perm=appended_to_original(3,[0]);self.assertEqual(perm.tolist(),[2,0,1])
            old=source.read_bytes();permute_float_ply(source,target,perm);self.assertEqual(source.read_bytes(),old)
            self.assertEqual(target.read_bytes().split(b'end_header\n')[1],v[perm].tobytes())
            with self.assertRaises(FileExistsError):permute_float_ply(source,target,perm)
    def test_invalid_permutation(self):
        for rows in ([0,0],[4],[-1]):
            with self.assertRaises(ValueError):appended_to_original(3,rows)

if __name__=='__main__':unittest.main()