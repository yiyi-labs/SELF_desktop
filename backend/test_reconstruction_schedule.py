import unittest

from reconstruction_schedule import training_view_and_mode


class TrainingScheduleTest(unittest.TestCase):
    def test_every_view_receives_face_and_scene_updates(self):
        for count in (150, 230, 144, 157):
            observed = [set() for _ in range(count)]
            for step in range(count * 8):
                index, mode = training_view_and_mode(step, count)
                observed[index].add(mode)
            for modes in observed:
                self.assertIn("face", modes)
                self.assertIn("scene", modes)


if __name__ == "__main__":
    unittest.main()
