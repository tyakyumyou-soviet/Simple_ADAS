import unittest

import numpy as np

from src.detection.hailo_detector import decode_yolo26


class Yolo26DecodeTests(unittest.TestCase):
    def test_decodes_grid_distances_and_class_logits(self):
        outputs = {}
        for size in (80, 40, 20):
            outputs[f"boxes{size}"] = np.zeros((1, size, size, 4), dtype=np.float32)
            outputs[f"scores{size}"] = np.full((1, size, size, 80), -20, dtype=np.float32)
        outputs["boxes80"][0, 10, 20] = [1, 2, 3, 4]
        outputs["scores80"][0, 10, 20, 2] = 2
        cls, y1, x1, y2, x2, score = decode_yolo26(outputs, 640, 640)[0]
        self.assertEqual(cls, 2)
        np.testing.assert_allclose([y1, x1, y2, x2], [8.5/80, 19.5/80, 14.5/80, 23.5/80])
        self.assertAlmostEqual(score, 1 / (1 + np.exp(-2)), places=6)

    def test_rejects_missing_head(self):
        with self.assertRaises(ValueError):
            decode_yolo26({"bad": np.zeros((1, 80, 80, 4))}, 640, 640)


if __name__ == "__main__":
    unittest.main()
