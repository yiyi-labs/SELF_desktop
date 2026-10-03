import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from live_dense_contract import digest,write_json
from live_room_retry import select_second_reference,retry_room_reference,complete_room_recovery


class SecondReferenceContract(unittest.TestCase):
    def candidate(self,name,held=12,fit=20,window=2):
        return dict(reference=name,window=window,eligible=True,mapTrackEvidence=True,
                    trackCounts={'fit':fit,'validation':held},newAreaCells=100)

    def test_uses_independent_track_support_not_name_or_pixel_rgb(self):
        selection={'candidates':[self.candidate('failed',30),self.candidate('new-a',15),self.candidate('new-z',25)]}
        outcomes=[{'reference':'failed','window':2,'status':'independent_validation_failed'}]
        self.assertEqual(select_second_reference(selection,outcomes)['reference'],'new-z')

    def test_never_attempts_a_third_reference(self):
        selection={'candidates':[self.candidate('third',30)]}
        outcomes=[{'reference':n,'window':2,'status':'independent_validation_failed'} for n in ('first','second')]
        self.assertIsNone(select_second_reference(selection,outcomes))

    def test_no_retry_of_success_or_insufficient_independent_evidence(self):
        selection={'candidates':[self.candidate('other',11)]}
        fail=[{'reference':'first','window':2,'status':'independent_validation_failed'}]
        self.assertIsNone(select_second_reference(selection,fail))
        selection['candidates'][0]['trackCounts']['validation']=12
        self.assertIsNone(select_second_reference(selection,[{**fail[0],'status':'conditional_surface_added'}]))

    def test_solver_budget_is_finite(self):
        for n in (0,41,True):
            with self.assertRaisesRegex(ValueError,'budget'):retry_room_reference('missing','missing','missing',max_evaluations=n)

    def entry_fixture(self,folder,*,eligible=True):
        folder=Path(folder);selection=folder/'selection.json'
        write_json(selection,{'candidates':[self.candidate('second',12 if eligible else 11)]})
        result=dict(manifestPath=str(folder/'result.json'),components={'room':{'additionalSurfaceReceipts':[]}},
            roomWindowRecovery=dict(outcomes=[{'reference':'first','window':2,'status':'independent_validation_failed'}],
                selectionPath=str(selection),selectionSha256=digest(selection),addedCount=0))
        write_json(folder/'result.json',result);return result

    def test_automatic_stage_returns_nested_final_identity_and_keeps_first_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);first=self.entry_fixture(root);raw=(root/'result.json').read_bytes()
            def second(parent,attempt,output,**kwargs):
                self.assertEqual(Path(parent),root/'result.json');self.assertEqual(Path(attempt),root)
                self.assertEqual(kwargs,{'max_evaluations':27,'max_surfaces':1,'extra_budget':5000,'allow_typed_conditional':False})
                Path(output).mkdir();result={**first,'manifestPath':str(Path(output)/'result.json'),'roomWindowSecondReference':{'status':'conditional_surface_added'}}
                write_json(Path(output)/'result.json',result);return result
            with patch('live_room_retry.retry_room_reference',side_effect=second) as solver:
                result=complete_room_recovery(first,root,max_evaluations=27,max_surfaces=1,extra_budget=5000,allow_typed_conditional=False)
                solver.assert_called_once()
            self.assertEqual((root/'result.json').read_bytes(),raw)
            self.assertEqual(Path(result['manifestPath']),root/'second-reference/result.json')
            self.assertEqual(json.loads(Path(result['manifestPath']).read_text()),result)

    def test_no_eligible_reference_or_full_budget_preserves_first_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);first=self.entry_fixture(root,eligible=False)
            with patch('live_room_retry.retry_room_reference',side_effect=AssertionError('no solve')):
                self.assertIs(complete_room_recovery(first,root),first)
            first=self.entry_fixture(root)
            proof=root/'proof.json';write_json(proof,{'windowRecovery':{'verified':True},'actualAdded':5000})
            first['components']['room']['additionalSurfaceReceipts']=[{'path':str(proof)}]
            write_json(root/'result.json',first)
            with patch('live_room_retry.retry_room_reference',side_effect=AssertionError('budget full')):
                self.assertIs(complete_room_recovery(first,root,extra_budget=5000),first)

    def test_automatic_stage_does_not_swallow_program_errors_or_retry_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);first=self.entry_fixture(root)
            with patch('live_room_retry.retry_room_reference',side_effect=RuntimeError('unexpected program error')):
                with self.assertRaisesRegex(RuntimeError,'program error'):complete_room_recovery(first,root)
            first['roomWindowSecondReference']={'status':'original_bundle_retained'}
            with patch('live_room_retry.retry_room_reference',side_effect=AssertionError('second repeat')):
                self.assertIs(complete_room_recovery(first,root),first)
