import unittest
from reconstruction_local_sampling import scheduled_local_name,scheduled_local_index,schedule_receipt


class LocalSampling(unittest.TestCase):
    def test_even_counts_receive_geometry_without_changing_appearance(self):
        for count in (32,34,38):
            names=[str(i) for i in range(count)]
            report=schedule_receipt(names,900)
            self.assertTrue(report['oldMissingGeometry']);self.assertFalse(report['newMissingGeometry'])
            for step in range(900):
                if not (step>=83 and step%4==3):
                    self.assertEqual(scheduled_local_name(names,step),names[step%count])
            geometry_counts=[row['geometry'] for row in report['after'].values()]
            self.assertLessEqual(max(geometry_counts)-min(geometry_counts),1)
            self.assertEqual(sum(row['geometry'] for row in report['after'].values()),205)
            self.assertEqual(sum(row['appearance'] for row in report['after'].values()),695)

    def test_odd_counts_keep_original_nonaliased_schedule(self):
        for count in (1,3,31,33,35,37,39,41):
            names=[str(i) for i in range(count)]
            report=schedule_receipt(names,900)
            self.assertFalse(report['newMissingGeometry'])
            self.assertEqual(report['before'],report['after'])

    def test_saved_next_step_exactly_reproduces_remainder(self):
        names=[str(i) for i in range(38)]
        uninterrupted=[scheduled_local_name(names,s) for s in range(900)]
        for boundary in (0,38,79,80,83,400,817,899):
            self.assertEqual(uninterrupted[boundary:],[scheduled_local_name(names,s) for s in range(boundary,900)])

    def test_validation_and_current_geometry_balance(self):
        for count,step in ((0,0),(2,-1),(True,0),(2,False),(2,1.5)):
            with self.assertRaises(ValueError):scheduled_local_index(count,step)
        with self.assertRaises(ValueError):schedule_receipt(['same','same'],900)
        report=schedule_receipt([str(i) for i in range(38)],900)
        counts=[row['geometry'] for row in report['after'].values()]
        self.assertEqual((min(counts),max(counts)),(5,6))


if __name__=='__main__':unittest.main()
