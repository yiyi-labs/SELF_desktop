import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np

from reconstruction_live_room_completion import (deduplicate_new_surface,reference_occluded_region,
    complete_observed_room,unrepresented_sample_mask,verified_completion_replay)
from reconstruction_live_dense_contract import digest,write_json


class RoomCompletionContract(unittest.TestCase):
    def test_uncovered_observed_room_not_limited_to_person_silhouette(self):
        old=dict(means=np.array([[0.,0.,2.]]),scales=np.array([[.1,.1,.01]]),normal=np.array([[0.,0.,1.]]))
        xyz=np.array([[0.,0.,2.],[3.,0.,2.],[-3.,0.,2.],[np.nan,0.,2.],[8.,0.,2.]])
        basis=np.tile(np.eye(3),(5,1,1));scales=np.tile([.1,.1,.01],(5,1))
        keep=unrepresented_sample_mask(xyz,basis,scales,np.array([1,1,1,1,0],bool),[old])
        np.testing.assert_array_equal(keep,[False,True,True,False,False])
        np.testing.assert_array_equal(old['means'],[[0.,0.,2.]])

    def test_only_compatible_new_samples_are_deduplicated(self):
        old=dict(means=np.array([[0.,0,2.]]),scales=np.array([[.1,.1,.01]]),normal=np.array([[0.,0,1.]]))
        fresh=dict(means=np.array([[0.,0,2.],[.02,0,2.],[0,0,2.2],[0.,0,2.]]),
            scales=np.tile([.1,.1,.01],(4,1)),normal=np.array([[0.,0,1.],[0.,0,1.],[0.,0,1.],[1.,0,0.]]))
        copy=old['means'].copy()
        np.testing.assert_array_equal(deduplicate_new_surface(fresh,[old]),[False,False,True,True])
        np.testing.assert_array_equal(old['means'],copy)

    def test_reference_occlusion_is_not_room_or_foreground(self):
        z=np.zeros((21,21),bool);face=z.copy();face[8:13,8:13]=True
        labels=dict(face_core=face,face_boundary=z,hair_visible=z,glasses_visible=z,
            unknown_or_occluded=z,room_visible=~face,neck_cloth_visible=z)
        prediction=dict(depth=np.ones((21,21)),K=np.array([[10.,0,10],[0,10.,10],[0,0,1]]),
            W2C=np.eye(4),nativeToProcessed=np.eye(3))
        result=reference_occluded_region(np.array([[0.,0,2],[0.,0,.8],[1.,0,2]]),labels,{},'ref',None,{},prediction)
        np.testing.assert_array_equal(result,[True,False,False])

    def test_empty_reference_set_retains_exact_parent_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);asset=root/'room.npz';np.savez(asset,means=np.zeros((3,3)))
            proof=root/'proof.json';write_json(proof,dict(qualified=True,roomAssetHash=digest(asset)))
            depth=root/'depth-manifest.json';write_json(depth,{})
            write_json(root/'request.json',dict(prepared='not_read_when_no_candidates'))
            parent=root/'parent.json';bundle=dict(sourceSha256='capture',reference='main',
                depthManifestPath=str(depth),depthManifestHash=digest(depth),
                components={'room':dict(path=str(asset),sha256=digest(asset),count=3,typedSupport=True,
                    surfaceCorrectionReceipt=str(proof),surfaceCorrectionReceiptSha256=digest(proof))})
            write_json(parent,bundle)
            with patch('reconstruction_live_room_completion.select_completion_references',return_value={'selected':[]}):
                result=complete_observed_room(parent,root/'completion')
            self.assertEqual(result['components'],bundle['components'])
            self.assertEqual(result['roomCompletion']['status'],'original_bundle_retained')
            self.assertEqual(result['roomCompletion']['addedCount'],0)
            self.assertEqual(result['roomCompletion']['additionalPointBudget'],30000)
            self.assertEqual(json.loads(Path(result['manifestPath']).read_text()),result)

    def test_budget_cannot_expand_without_bound(self):
        for budget in (30001,0,True,8000.5):
            with self.assertRaisesRegex(ValueError,'budget_contract'):
                complete_observed_room('unused','unused',extra_budget=budget)

    def replay_fixture(self,root):
        prepared=root/'prepared';prepared.mkdir()
        write_json(prepared/'preparation.json',{'sourceHash':'capture'})
        np.savez(prepared/'local_geometry.npz',C=np.eye(4))
        asset=root/'room.npz';np.savez(asset,means=np.zeros((3,3)),uid=np.arange(3))
        proof=root/'proof.json';write_json(proof,dict(qualified=True,roomAssetHash=digest(asset)))
        depth=root/'depth-manifest.json';write_json(depth,{})
        write_json(root/'request.json',dict(prepared=str(prepared),sourceHash='capture'))
        parent=root/'parent.json';bundle=dict(sourceSha256='capture',reference='main',
            preparedSha256=digest(prepared/'preparation.json'),localGeometrySha256=digest(prepared/'local_geometry.npz'),
            depthManifestPath=str(depth),depthManifestHash=digest(depth),
            components={'room':dict(path=str(asset),sha256=digest(asset),count=3,typedSupport=True,trainNames=['main'],
                surfaceCorrectionReceipt=str(proof),surfaceCorrectionReceiptSha256=digest(proof))})
        write_json(parent,bundle)
        old=root/'old';old.mkdir();selection=old/'selection.json'
        candidates=[dict(reference=n,window=i) for i,n in enumerate(('other-a','other-b'))]
        write_json(selection,dict(sourceSha256='capture',primaryReference='main',selected=candidates,
            selectionUsesOnlyOriginalTrain=True))
        additions=[]
        for i,c in enumerate(candidates):
            folder=old/f'aux-{i}';folder.mkdir();report=folder/'report.json';surface=folder/'surface.npz';extra=folder/'extra.npz'
            write_json(report,dict(sourceHash='capture',accepted=True,**c))
            np.savez(surface,sourceHash=np.asarray('capture'))
            np.savez(extra,means=np.ones((2,3)),uid=np.arange(2)+10*(i+1))
            receipt=folder/'proof.json';write_json(receipt,dict(kind='shared-static-track-surface-correction',qualified=True,
                sourceSha256='capture',preparedSha256=bundle['preparedSha256'],localGeometrySha256=bundle['localGeometrySha256'],
                roomAssetHash=digest(extra),referenceName=c['reference'],solverReportPath=str(report),solverReportSha256=digest(report),
                surfacePath=str(surface),surfaceSha256=digest(surface)))
            additions.append(dict(index=i+1,path=str(receipt),sha256=digest(receipt),assetPath=str(extra),assetSha256=digest(extra),count=2))
        manifest=old/'result.json';record={**bundle,'parentManifestPath':str(parent),'parentManifestHash':digest(parent),
            'components':{'room':{**bundle['components']['room'],'additionalSurfaceReceipts':additions}},
            'roomCompletion':dict(selectionPath=str(selection),selectionSha256=digest(selection),
                outcomes=[{**c,'status':'conditional_surface_added','count':2} for c in candidates])}
        write_json(manifest,record)
        return parent,bundle,manifest,record

    def test_replay_preserves_selection_and_solves_with_new_bounded_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);parent,bundle,manifest,record=self.replay_fixture(root)
            originals={p:digest(p) for p in root.rglob('*') if p.is_file()}
            budgets=[]
            def export(solved,parent_path,output,budget,**kwargs):
                output.mkdir();budgets.append(budget);i=len(budgets)
                np.testing.assert_equal(json.loads((solved/'report.json').read_text())['accepted'],True)
                np.savez(output/'addition.npz',means=np.ones((budget,3))*i,uid=np.arange(budget)+i*100000,
                    source_receipt_index=np.full(budget,i,np.int16))
                return dict(assetPath=str(output/'addition.npz'),count=budget,trainNames=[f'other-{i}'])
            with patch('reconstruction_live_room_completion.select_completion_references',side_effect=AssertionError('selection rerun')),\
                 patch('reconstruction_live_shared_room_surface.run_shared_surface',side_effect=AssertionError('solver rerun')),\
                 patch('reconstruction_live_shared_room_surface.export_shared_room_initialization',side_effect=export):
                result=complete_observed_room(parent,root/'replay',extra_budget=30000,replay_manifest=manifest)
            self.assertEqual(budgets,[15000,15000]);self.assertEqual(result['roomCompletion']['addedCount'],30000)
            self.assertFalse(result['roomCompletion']['replay']['solverInvoked'])
            self.assertEqual(digest(root/'replay/selection.json'),record['roomCompletion']['selectionSha256'])
            with np.load(result['components']['room']['path']) as a:
                np.testing.assert_array_equal(a['means'][:3],np.zeros((3,3)))
                np.testing.assert_array_equal(a['uid'][:3],np.arange(3))
            for p,h in originals.items():self.assertEqual(digest(p),h)

    def test_replay_rejects_changed_recorded_files_before_export(self):
        for target in ('selection','solver','surface','proof','asset','prepared','parent'):
            with self.subTest(target=target),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);parent,bundle,manifest,record=self.replay_fixture(root)
                addition=record['components']['room']['additionalSurfaceReceipts'][0]
                proof=json.loads(Path(addition['path']).read_text())
                paths=dict(selection=record['roomCompletion']['selectionPath'],solver=proof['solverReportPath'],
                    surface=proof['surfacePath'],proof=addition['path'],asset=addition['assetPath'],
                    prepared=root/'prepared/local_geometry.npz',parent=parent)
                with Path(paths[target]).open('ab') as f:f.write(b'changed')
                with self.assertRaises((ValueError,json.JSONDecodeError)):
                    verified_completion_replay(manifest,parent,bundle)

    def test_replay_rejects_other_capture_geometry_or_unselected_solve(self):
        for target in ('source','geometry','outcome','selection'):
            with self.subTest(target=target),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);parent,bundle,manifest,record=self.replay_fixture(root)
                if target=='source':record['sourceSha256']='another-capture'
                elif target=='geometry':record['localGeometrySha256']='another-fit'
                elif target=='outcome':record['roomCompletion']['outcomes'][0]['status']='validation_failed'
                else:
                    selected=Path(record['roomCompletion']['selectionPath']);s=json.loads(selected.read_text())
                    s['selected'][0]['reference']='unselected';write_json(selected,s)
                    record['roomCompletion']['selectionSha256']=digest(selected)
                write_json(manifest,record)
                with self.assertRaisesRegex(ValueError,'room_completion_replay_'):
                    verified_completion_replay(manifest,parent,bundle)

    def test_replay_requires_explicit_proof_not_guessed_auxiliary_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);parent,bundle,manifest,record=self.replay_fixture(root)
            record['components']['room']['additionalSurfaceReceipts'].pop();write_json(manifest,record)
            with self.assertRaisesRegex(ValueError,'qualified_solve_missing'):
                verified_completion_replay(manifest,parent,bundle)


if __name__=='__main__':unittest.main()
