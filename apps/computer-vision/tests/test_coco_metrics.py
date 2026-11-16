import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from ferqueue_cv.coco_metrics import compute_coco_metrics


@unittest.skipUnless(importlib.util.find_spec('numpy') and importlib.util.find_spec('pycocotools'),
                     'Tes metrik numerik memerlukan NumPy dan pycocotools.')
class CocoMetricsTests(unittest.TestCase):
    def setUp(self):
        # Unsorted, non-contiguous IDs ensure class names follow COCO's category axis.
        self.groundtruth = {
            'images': [{'id': 1, 'width': 600, 'height': 400}, {'id': 2, 'width': 600, 'height': 400}],
            'categories': [{'id': 7, 'name': 'Truk'}, {'id': 2, 'name': 'Mobil'}, {'id': 11, 'name': 'Bus'}],
            'annotations': [
                {'id': 1, 'image_id': 1, 'category_id': 7, 'bbox': [10, 10, 200, 100], 'area': 20000, 'iscrowd': 0},
                {'id': 2, 'image_id': 2, 'category_id': 2, 'bbox': [20, 20, 200, 100], 'area': 20000, 'iscrowd': 0},
            ],
        }
        self.predictions = [
            {'image_id': 1, 'category_id': 7, 'bbox': [10, 10, 200, 100], 'score': .9},
            {'image_id': 2, 'category_id': 2, 'bbox': [20, 20, 200, 100], 'score': .9},
        ]

    def compute(self, predictions):
        with redirect_stdout(io.StringIO()):
            return compute_coco_metrics(self.groundtruth, predictions)

    def test_perfect_boxes_produce_overall_and_per_class_ap(self):
        original_gt, original_dt = copy.deepcopy(self.groundtruth), copy.deepcopy(self.predictions)
        result = self.compute(self.predictions)
        self.assertAlmostEqual(result['DetectionBoxes_Precision/mAP'], 1)
        self.assertAlmostEqual(result['DetectionBoxes_PerformanceByCategory/mAP/Truk'], 1)
        self.assertAlmostEqual(result['DetectionBoxes_PerformanceByCategory/mAP/Mobil'], 1)
        self.assertEqual(result['DetectionBoxes_PerformanceByCategory/mAP/Bus'], -1)
        self.assertEqual(result['DetectionBoxes_Precision/mAP (small)'], -1)
        self.assertEqual(self.groundtruth, original_gt)
        self.assertEqual(self.predictions, original_dt)

    def test_missing_one_class_keeps_correct_category_mapping(self):
        result = self.compute(self.predictions[1:])
        self.assertAlmostEqual(result['DetectionBoxes_Precision/mAP'], .5)
        self.assertAlmostEqual(result['DetectionBoxes_PerformanceByCategory/mAP/Mobil'], 1)
        self.assertEqual(result['DetectionBoxes_PerformanceByCategory/mAP/Truk'], 0)

    def test_no_detections_produces_zero_ap_without_loadres_crash(self):
        result = self.compute([])
        self.assertEqual(result['DetectionBoxes_Precision/mAP'], 0)
        self.assertEqual(result['DetectionBoxes_Recall/AR@100'], 0)
        self.assertEqual(result['DetectionBoxes_PerformanceByCategory/mAP/Bus'], -1)

    def test_wrong_classes_are_not_counted_as_correct_detections(self):
        wrong = copy.deepcopy(self.predictions)
        wrong[0]['category_id'], wrong[1]['category_id'] = 2, 7
        result = self.compute(wrong)
        self.assertEqual(result['DetectionBoxes_Precision/mAP'], 0)

    def test_evaluate_saves_report_with_standard_per_class_metrics(self):
        import numpy as np
        from PIL import Image
        from ferqueue_cv.training import evaluate
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / 'vehicle.jpg'
            Image.new('RGB', (500, 500), 'red').save(image)
            row = {'image': 'vehicle.jpg', 'width': 500, 'height': 500,
                   'sha256': hashlib.sha256(image.read_bytes()).hexdigest(),
                   'boxes': [{'class_id': 1, 'ymin': .1, 'xmin': .1, 'ymax': .9, 'xmax': .9}]}
            manifest = {'classes': ['Mobil'], 'splits': {'train': [row], 'test': [row]}, 'warnings': []}
            result = {'detection_boxes': np.array([[.1, .1, .9, .9]]),
                      'detection_classes': np.array([1]), 'detection_scores': np.array([.9])}
            with patch('ferqueue_cv.training.load_detector', return_value=(object(), {'manifest': manifest}, {'checkpoint': 'ckpt-12'})), \
                    patch('ferqueue_cv.training.detect', return_value=result), redirect_stdout(io.StringIO()):
                evaluate({'run_dir': 'models/run'}, root, 'test')
            report = json.loads((root / 'models/run/reports/ckpt-12-test.json').read_text())
            self.assertEqual(report['image_count'], 1)
            self.assertEqual(report['checkpoint'], 'ckpt-12')
            self.assertAlmostEqual(report['metrics']['DetectionBoxes_PerformanceByCategory/mAP/Mobil'], 1)

            # Default evaluation must use test and retain low confidence
            # predictions for COCO AP, independently of display filtering.
            result['detection_scores'] = np.array([.1])
            with patch('ferqueue_cv.training.load_detector', return_value=(object(), {'manifest': manifest}, {'checkpoint': 'ckpt-12'})), \
                    patch('ferqueue_cv.training.detect', return_value=result), redirect_stdout(io.StringIO()):
                evaluate({'run_dir': 'models/run', 'confidence_threshold': .99}, root)
            tested = json.loads((root / 'models/run/reports/ckpt-12-test.json').read_text())
            self.assertEqual(tested['split'], 'test')
            self.assertAlmostEqual(tested['metrics']['DetectionBoxes_PerformanceByCategory/mAP/Mobil'], 1)
            with self.assertRaisesRegex(ValueError, 'hanya menggunakan split test'):
                evaluate({'run_dir': 'models/run'}, root, 'val')


if __name__ == '__main__':
    unittest.main()
