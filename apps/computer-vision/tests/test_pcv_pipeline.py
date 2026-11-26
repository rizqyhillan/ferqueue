import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from ferqueue_cv.conversion import inspect_dataset
from ferqueue_cv.dataset import prepare, split_groups, verify_images
from ferqueue_cv.settings import load_config, training_plan
from ferqueue_cv.training import load_manifest


class ManualPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.raw = self.root / 'data/raw/vehicles'
        self.raw.mkdir(parents=True)
        (self.raw / 'classes.txt').write_text('mobil\n')
        for index in range(10):
            image = self.raw / f'images/session-{index}/frame.png'
            image.parent.mkdir(parents=True)
            Image.new('RGB', (80, 60), (index * 20, 10, 40)).save(image)
            label = self.raw / f'labels/session-{index}/frame.txt'
            label.parent.mkdir(parents=True)
            label.write_text('0 .5 .5 .5 .5\n')
        self.config = {'dataset_format': 'yolo', 'dataset_dir': 'data/raw/vehicles',
                       'prepared_dir': 'data/processed/manifest', 'run_dir': 'models/run1',
                       'seed': 42, 'train_ratio': .7, 'test_ratio': .3,
                       'epochs': 10, 'batch_size': 4, 'learning_rate': .004,
                       'confidence_threshold': .5}

    def test_inspect_and_prepare_directly_from_yolo_without_external_converter(self):
        summary = inspect_dataset(self.config, self.root)
        self.assertEqual(summary['classes'], ['mobil'])
        self.assertEqual(set(summary['splits']), {'train', 'test'})
        manifest, prep_summary = prepare(self.config, self.root)
        self.assertEqual(set(prep_summary), {'train', 'test'})
        groups = [set(row['group'] for row in manifest['splits'][split]) for split in prep_summary]
        self.assertFalse(groups[0] & groups[1])
        self.assertEqual(sum(s['images'] for s in prep_summary.values()), 10)
        verify_images(manifest, self.root)
        load_manifest(self.config, self.root)

    def test_two_way_split_keeps_even_small_sets_disjoint(self):
        for count in (2, 3, 100):
            rows = [{'group': str(i // 2)} for i in range(count * 2)]
            splits = split_groups(rows, .7, .3, 42)
            self.assertEqual(set(splits), {'train', 'test'})
            self.assertTrue(all(splits.values()))
            self.assertEqual(sum(map(len, splits.values())), len(rows))
            self.assertEqual(splits, split_groups(rows, .7, .3, 42))
        with self.assertRaisesRegex(ValueError, 'minimal 2'):
            split_groups([{'group': 'a'}, {'group': 'a'}], .7, .3, 42)

    def test_epoch_budget_and_invalid_or_ambiguous_settings(self):
        path = self.root / 'config.json'
        valid_clahe = {
            **self.config,
            'preprocessing': {
                'denoise_kernel': 0,
                'clahe_clip_limit': 1.5,
                'clahe_grid_size': 8,
                'gamma': 1.0,
            },
        }
        path.write_text(json.dumps(valid_clahe))
        self.assertEqual(load_config(path, self.root), valid_clahe)
        plan = training_plan(self.config, {'splits': {'train': [{}] * 7}})
        self.assertEqual(plan['num_steps'], 20)
        for change in ({'num_steps': 100}, {'epochs': True}, {'nms_iou_threshold': 1.1},
                       {'max_detections': 0}, {'freeze_batchnorm': 'false'},
                       {'preprocessing': {'gamma': 0}}, {'preprocessing': {'crop': True}},
                       {'preprocessing': {'clahe_clip_limit': 12}},
                       {'preprocessing': {'clahe_grid_size': 0}},
                       {'augmentation': {'brightness_delta': 2}},
                       {'augmentation': None}, {'val_ratio': None}):
            with self.subTest(change=change):
                path.write_text(json.dumps({**self.config, **change}))
                with self.assertRaises(ValueError):
                    load_config(path, self.root)

    def test_dataset_settings_cannot_silently_reuse_a_manifest(self):
        prepare(self.config, self.root)
        with self.assertRaisesRegex(ValueError, 'berbeda dari manifest'):
            load_manifest({**self.config, 'seed': 7}, self.root)

    @unittest.skipUnless(importlib.util.find_spec('cv2'), 'OpenCV diperlukan untuk pemrosesan citra.')
    def test_preprocessing_clahe_and_preview_preserve_geometry(self):
        import numpy as np
        from ferqueue_cv.processing import describe_preprocessing, preprocess_image, preview_dataset

        self.assertEqual(describe_preprocessing({}), 'netral (RGB asli)')
        self.assertEqual(
            describe_preprocessing({'denoise_kernel': 0, 'clahe_clip_limit': 1.5, 'clahe_grid_size': 8, 'gamma': 1.0}),
            'LAB-CLAHE(clip=1.5, grid=8)',
        )

        image = Image.new('RGB', (80, 60), (40, 40, 40))
        ImageDraw.Draw(image).ellipse((25, 20, 55, 40), fill=(180, 60, 60))
        processed = preprocess_image(image, {'denoise_kernel': 0, 'clahe_clip_limit': 1.5, 'clahe_grid_size': 8, 'gamma': 1.0})
        self.assertEqual(processed.size, image.size)
        self.assertEqual(processed.mode, 'RGB')
        self.assertFalse(np.array_equal(np.asarray(processed), np.asarray(image)))

        prepare(self.config, self.root)
        clahe_config = {
            **self.config,
            'preprocessing': {'denoise_kernel': 0, 'clahe_clip_limit': 1.5, 'clahe_grid_size': 8, 'gamma': 1.0},
        }
        report = preview_dataset(clahe_config, self.root, 'outputs/review', limit=2)
        self.assertEqual(len(report['images']), 2)
        self.assertTrue((self.root / 'outputs/review/report.json').is_file())

    @unittest.skipUnless(importlib.util.find_spec('numpy'), 'NumPy diperlukan untuk NMS.')
    def test_display_filters_share_confidence_nms_and_class_policy(self):
        import numpy as np
        from ferqueue_cv.postprocessing import select_detections
        result = {'detection_boxes': np.array([[0, 0, .5, .5], [0, 0, .5, .5], [.6, .6, .9, .9]]),
                  'detection_scores': np.array([.9, .8, .4]), 'detection_classes': np.array([1, 2, 1])}
        self.assertEqual(select_detections(result, self.config), [0])
        self.assertEqual(select_detections(result, {**self.config, 'class_agnostic_nms': False}), [0, 1])
        self.assertEqual(select_detections(result, {**self.config, 'confidence_threshold': .3}), [0, 2])

    @unittest.skipUnless(importlib.util.find_spec('tensorflow'), 'TensorFlow diperlukan untuk TFRecord/pipeline.')
    def test_records_pipeline_auto_prepares_and_freezes_clahe_processing(self):
        import numpy as np
        import tensorflow as tf
        from google.protobuf import text_format
        from object_detection.protos import pipeline_pb2
        from ferqueue_cv.processing import preprocess_image
        from ferqueue_cv.training import build_records, make_pipeline

        config = {
            **self.config,
            'preprocessing': {
                'denoise_kernel': 0,
                'clahe_clip_limit': 1.5,
                'clahe_grid_size': 8,
                'gamma': 1.0,
            },
            'augmentation': {'horizontal_flip': False, 'brightness_delta': .12},
        }
        # build_records otomatis menjalankan prepare jika manifest belum ada.
        manifest, run, plan = build_records(config, self.root)
        self.assertTrue((self.root / config['prepared_dir'] / 'manifest.json').is_file())

        template = self.root / 'pretrained'
        template.mkdir()
        (template / 'pipeline.config').write_text('model { ssd {} } eval_input_reader {}')
        make_pipeline(config, manifest, template, run)
        pipeline = pipeline_pb2.TrainEvalPipelineConfig()
        text_format.Parse((run / 'pipeline.config').read_text(), pipeline)
        self.assertEqual(pipeline.train_config.num_steps, plan['num_steps'])
        self.assertEqual(len(pipeline.train_config.data_augmentation_options), 1)
        self.assertAlmostEqual(pipeline.train_config.data_augmentation_options[0].random_adjust_brightness.max_delta, .12)
        self.assertTrue(pipeline.eval_input_reader[0].tf_record_input_reader.input_path[0].endswith('test.tfrecord'))

        for split in ('train', 'test'):
            records = list(tf.compat.v1.io.tf_record_iterator(str(run / f'records/{split}.tfrecord')))
            self.assertEqual(len(records), len(manifest['splits'][split]))
            features = tf.train.Example.FromString(records[0]).features.feature
            self.assertEqual(features['image/format'].bytes_list.value[0], b'png')
            decoded = tf.io.decode_png(features['image/encoded'].bytes_list.value[0]).numpy()
            with Image.open(self.root / manifest['splits'][split][0]['image']) as source:
                expected = np.asarray(preprocess_image(source, config['preprocessing']))
            np.testing.assert_array_equal(decoded, expected)

        # Display-only changes do not invalidate a run; training/preprocessing changes do.
        with patch('ferqueue_cv.training.write_records') as writer:
            build_records({**config, 'confidence_threshold': .2}, self.root)
            writer.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'berbeda dari run'):
            build_records({**config, 'epochs': 20}, self.root)
        with self.assertRaisesRegex(ValueError, 'berbeda dari run'):
            build_records({**config, 'preprocessing': {**config['preprocessing'], 'clahe_clip_limit': 0}}, self.root)


if __name__ == '__main__':
    unittest.main()
