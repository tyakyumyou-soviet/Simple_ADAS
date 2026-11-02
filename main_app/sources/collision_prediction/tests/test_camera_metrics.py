import unittest

from src.ui.camera_metrics import camera_follow_ratio


class CameraFollowRatioTests(unittest.TestCase):
    def test_following_variable_input(self):
        self.assertAlmostEqual(camera_follow_ratio(16.7, 16.7), 1.0)
        self.assertAlmostEqual(camera_follow_ratio(25.0, 25.0), 1.0)
        self.assertAlmostEqual(camera_follow_ratio(10.0, 20.0), 0.5)

    def test_startup_and_independent_sample_windows(self):
        self.assertIsNone(camera_follow_ratio(0.0, 16.7))
        self.assertIsNone(camera_follow_ratio(16.7, None))
        self.assertIsNone(camera_follow_ratio(16.7, 0.0))
        self.assertEqual(camera_follow_ratio(17.0, 16.7), 1.0)


if __name__ == "__main__":
    unittest.main()
