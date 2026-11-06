import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from ferqueue_cv.conversion import adopt_coco, stage_yolo
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

    def coco_config(self):
        return {**self.config, 'dataset_format': 'coco',
                'coco_annotations': {split: f'data/coco/annotations/instances_{split}.json'
                                     for split in ('train', 'test')}}

    def stage_and_fake_upstream(self):
        metadata = stage_yolo(self.config, self.root, 'data/staging')
        output = self.root / 'external/output'
        output.mkdir(parents=True)
        # Contract fixtures for the external converter's integer bbox output.
        # The FERQUEUE adapter must retain these numbers, never recompute boxes.
        for split, rows in metadata['splits'].items():
            document = {'images': [], 'annotations': [], 'categories': [{'id': 1, 'name': 'mobil'}]}
            for index, row in enumerate(rows):
                document['images'].append({'id': index, 'file_name': Path(row['staged_image']).name,
                                           'width': 80, 'height': 60})
                for box in row['boxes']:
                    document['annotations'].append({'id': len(document['annotations']) + 1,
                        'image_id': index, 'category_id': box['class_id'],
                        'bbox': [20, 15, 40, 30], 'area': 1200, 'iscrowd': 0, 'segmentation': []})
            (output / f'instances_{split}.json').write_text(json.dumps(document))
        return metadata

    def adopt(self):
        return adopt_coco(self.config, self.root, 'data/staging', 'external/output', 'data/coco')

    def test_staging_and_adoption_preserve_labels_groups_and_raw_bytes(self):
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in self.raw.rglob('*') if p.is_file()}
        staged = self.stage_and_fake_upstream()
        self.adopt()
        config = self.coco_config()
        manifest, summary = prepare(config, self.root)
        self.assertEqual(set(summary), {'train', 'test'})
        groups = [set(row['group'] for row in manifest['splits'][split]) for split in summary]
        self.assertFalse(groups[0] & groups[1])
        self.assertEqual(sum(s['images'] for s in summary.values()), 10)
        names = [Path(row['staged_image']).name for rows in staged['splits'].values() for row in rows]
        self.assertEqual(len(names), len(set(names)))
        for rows in manifest['splits'].values():
            for row in rows:
                self.assertEqual(row['boxes'], [{'class_id': 1, 'xmin': .25, 'ymin': .25, 'xmax': .75, 'ymax': .75}])
        document = json.loads((self.root / config['coco_annotations']['train']).read_text())
        self.assertEqual(document['annotations'][0]['bbox'], [20, 15, 40, 30])
        self.assertEqual(document['annotations'][0]['segmentation'], [])
        self.assertEqual(document['images'][0]['file_name'].split('/')[0], 'images')
        verify_images(manifest, self.root)
        load_manifest(config, self.root)
        after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in self.raw.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        with self.assertRaisesRegex(ValueError, 'tidak ditimpa'):
            stage_yolo(self.config, self.root, 'data/staging')

    def test_adapter_preserves_upstream_pixel_rounding_and_rejects_wrong_classes(self):
        self.stage_and_fake_upstream()
        source = self.root / 'external/output/instances_train.json'
        document = json.loads(source.read_text())
        document['annotations'][0]['bbox'] = [19, 14, 39, 29]
        document['annotations'][0]['area'] = 39 * 29
        source.write_text(json.dumps(document))
        self.adopt()
        result = json.loads((self.root / 'data/coco/annotations/instances_train.json').read_text())
        self.assertEqual(result['annotations'][0]['bbox'], [19, 14, 39, 29])
        document['categories'][0]['name'] = 'cara'
        source.write_text(json.dumps(document))
        with self.assertRaisesRegex(ValueError, 'Kelas converter berbeda'):
            adopt_coco(self.config, self.root, 'data/staging', 'external/output', 'data/other-coco')

    def test_adapter_rejects_missing_images_labels_and_stale_staging(self):
        metadata = self.stage_and_fake_upstream()
        source = self.root / 'external/output/instances_train.json'
        original = json.loads(source.read_text())
        for key in ('images', 'annotations'):
            document = json.loads(json.dumps(original))
            document[key].pop()
            source.write_text(json.dumps(document))
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.adopt()
        source.write_text(json.dumps(original))
        label = self.root / 'data/staging' / Path(metadata['splits']['train'][0]['staged_image']).with_suffix('.txt')
        label.write_text('')
        with self.assertRaisesRegex(ValueError, 'berubah setelah stage-yolo'):
            self.adopt()

    def test_explicit_groups_cannot_leak_between_coco_splits(self):
        self.stage_and_fake_upstream()
        self.adopt()
        config = self.coco_config()
        train = json.loads((self.root / config['coco_annotations']['train']).read_text())
        path = self.root / config['coco_annotations']['test']
        tested = json.loads(path.read_text())
        tested['images'][0]['group_id'] = train['images'][0]['group_id']
        path.write_text(json.dumps(tested))
        with self.assertRaisesRegex(ValueError, 'bocor'):
            prepare(config, self.root)

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
        path.write_text(json.dumps(self.config))
        self.assertEqual(load_config(path, self.root), self.config)
        plan = training_plan(self.config, {'splits': {'train': [{}] * 7}})
        self.assertEqual(plan['num_steps'], 20)
        for change in ({'num_steps': 100}, {'epochs': True}, {'nms_iou_threshold': 1.1},
                       {'max_detections': 0}, {'freeze_batchnorm': 'false'},
                       {'preprocessing': {'gamma': 0}}, {'preprocessing': {'crop': True}},
                       {'segmentation': {'iterations': 0}}, {'augmentation': {'brightness_delta': 2}},
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
    def test_preprocessing_and_grabcut_preview_preserve_geometry(self):
        import numpy as np
        from ferqueue_cv.processing import grabcut_mask, preprocess_image, preview_dataset
        image = Image.new('RGB', (80, 60), 'white')
        ImageDraw.Draw(image).ellipse((25, 20, 55, 40), fill='red')
        processed = preprocess_image(image, {'denoise_kernel': 3, 'clahe_clip_limit': 2, 'gamma': .9})
        self.assertEqual(processed.size, image.size)
        self.assertEqual(processed.mode, 'RGB')
        self.assertFalse(np.array_equal(np.asarray(processed), np.asarray(image)))
        box = {'xmin': .2, 'ymin': .2, 'xmax': .8, 'ymax': .8}
        mask, status = grabcut_mask(image, box)
        self.assertEqual(status, 'approximate_review_required')
        self.assertEqual(mask.size, image.size)
        pixels = np.asarray(mask)
        self.assertTrue(pixels.any())
        self.assertFalse(pixels[:12].any() or pixels[48:].any() or pixels[:, :16].any() or pixels[:, 64:].any())
        prepare(self.config, self.root)
        report = preview_dataset(self.config, self.root, 'outputs/review', limit=1, segment=True)
        self.assertFalse(report['used_as_training_masks'])
        self.assertEqual(len(report['images']), 1)
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
    def test_records_pipeline_and_resume_use_epoch_plan_and_frozen_processing(self):
        import numpy as np
        import tensorflow as tf
        from google.protobuf import text_format
        from object_detection.protos import pipeline_pb2
        from ferqueue_cv.processing import preprocess_image
        from ferqueue_cv.training import build_records, make_pipeline
        config = {**self.config, 'preprocessing': {'gamma': .8},
                  'augmentation': {'horizontal_flip': False, 'brightness_delta': .12}}
        manifest, _ = prepare(config, self.root)
        _, run, plan = build_records(config, self.root)
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
        # Display-only changes do not invalidate a run; training changes do.
        with patch('ferqueue_cv.training.write_records') as writer:
            build_records({**config, 'confidence_threshold': .2}, self.root)
            writer.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'berbeda dari run'):
            build_records({**config, 'epochs': 20}, self.root)


if __name__ == '__main__':
    unittest.main()
