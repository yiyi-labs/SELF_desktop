import unittest
from live_room_reference import choose_reference_candidates


class RoomReferenceEligibility(unittest.TestCase):
    def row(self,name,window=0,fit=25,held=13,shared=4):
        return dict(reference=name,window=window,fitTrackCount=fit,heldTrackCount=held,sharedPrimaryTrackCount=shared,eligible=fit>=20 and held>=12)

    def test_one_missing_held_does_not_relax_threshold_or_change_primary(self):
        rows=[self.row('primary',fit=48,held=11,shared=100),self.row('pnp',fit=0,held=0),self.row('other')]
        before=[dict(r) for r in rows]
        self.assertEqual([r['reference'] for r in choose_reference_candidates(rows,'primary')],['other'])
        self.assertEqual(rows,before)

    def test_same_reference_depth_windows_are_not_multiple_independent_attempts(self):
        rows=[self.row('one',0,shared=9),self.row('one',1,shared=9),self.row('two',2),self.row('three',3)]
        result=choose_reference_candidates(rows,'primary',20)
        self.assertEqual([r['reference'] for r in result],['one','three'])
        self.assertEqual(len(result),2)


if __name__=='__main__':unittest.main()
