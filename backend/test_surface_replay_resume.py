"""Resume auditing must not silently reselect or accept modified prepared inputs."""
import json
from pathlib import Path
import tempfile
import unittest
import prepare_surface_candidate_audit as audit


class FrozenResumeContracts(unittest.TestCase):
    def fixture(self, root):
        collector=root/'collector.py';collector.write_text('frozen preparation code')
        asset=root/'prepared.npz';asset.write_bytes(b'opaque frozen asset')
        snapshot=root/'algorithm-source';snapshot.mkdir()
        adapter=snapshot/Path(audit.__file__).name;adapter.write_text('executed adapter snapshot')
        frozen={'outputs':{'prepared.npz':{'sha256':audit.sha(asset)}},
                'inputs':{str(collector):{'sha256':audit.sha(collector)},
                          str(Path(audit.__file__).resolve()):{'sha256':audit.sha(adapter)}}}
        (root/'preparation-summary.json').write_text(json.dumps(frozen))
        return collector,asset,adapter

    def test_only_reporting_adapter_may_differ_from_executed_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.fixture(root);inputs=audit.Inputs()
            audit.verify_frozen_prepare(root,inputs);inputs.verify()
            self.assertIn(str(Path(audit.__file__).resolve()),inputs.records)
            self.assertIn(str(root/'algorithm-source'/Path(audit.__file__).name),inputs.records)

    def test_modified_collector_or_prepared_is_rejected(self):
        for which in [0,1]:
            with tempfile.TemporaryDirectory() as d:
                root=Path(d);files=self.fixture(root);files[which].write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError,'frozen_(input|output)_changed'):
                    audit.verify_frozen_prepare(root,audit.Inputs())

    def test_executed_adapter_snapshot_cannot_be_replaced(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);_,_,snapshot=self.fixture(root);snapshot.write_text('changed')
            with self.assertRaisesRegex(ValueError,'executed_adapter_snapshot_changed'):
                audit.verify_frozen_prepare(root,audit.Inputs())

if __name__=='__main__':unittest.main()
