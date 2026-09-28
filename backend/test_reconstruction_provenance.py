from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np

from audit_reconstruction_provenance import audit


class ProvenanceJoinTest(unittest.TestCase):
    def test_hash_and_partition_guard_and_source_totals(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            lineage, weights, output = (root / name for name in
                                        ("lineage.npz", "weights.npz", "report.json"))
            np.savez(lineage, plySha256="frozen", pointIndex=np.arange(4),
                     initialSourceKind=np.array([0, 0, 1, 0], dtype=np.uint8),
                     initialSourceId=np.array([2, 3, 4, 5]),
                     personPartition=np.array([1, 0, 0, 0], dtype=np.uint8))
            np.savez(weights, plySha256="frozen", editableSplats=1,
                     faceIntrusion=np.array([2., 3., 5.]),
                     roomSupport=np.array([10., 2., 4.]))
            result = audit(lineage, weights, output)
            self.assertEqual(result["faceIntrusionTotal"], 10.)
            self.assertEqual(result["byInitialSource"]["registered_colmap_track"]
                             ["faceIntrusionScore"], 7.)
            self.assertEqual(result["byInitialSource"]["interpolated_scene_seed"]
                             ["roomSupportScore"], 2.)
            np.savez(weights, plySha256="other", editableSplats=1,
                     faceIntrusion=np.array([2., 3., 5.]),
                     roomSupport=np.array([10., 2., 4.]))
            with self.assertRaisesRegex(ValueError, "hash_mismatch"):
                audit(lineage, weights, root / "bad.json")


if __name__ == "__main__":
    unittest.main()
