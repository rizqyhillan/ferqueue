import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from ferqueue_cv.__main__ import load_config
from ferqueue_cv.cleanup import audit_dataset
from ferqueue_cv.coco_dataset import collect_coco_dataset
from ferqueue_cv.dataset import prepare, verify_images


class CocoDatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.image_dir = self.root / 'data/images'
        self.image_dir.mkdir(parents=True)
        Image.new('RGB', (80, 60), 'red').save(self.image_dir / 'train.png')
        Image.new('RGB', (80, 60), 'blue').save(self.image_dir / 'test.png')
        self.config = {
            'dataset_format': 'coco', 'dataset_dir': 'data/images',
            'coco_annotations': {'train': 'data/train.json', 'test': 'data/test.json'},
            'prepared_dir': 'data/processed/coco', 'run_dir': 'models/coco',
            'seed': 42, 'train_ratio': .9, 'test_ratio': .1,
            'batch_size': 4, 'num_steps': 100, 'learning_rate': .004,
            'confidence_threshold': .5,
        }
        # COCO IDs can have gaps and image/annotation IDs are local to each JSON.
        categories = [{'id': 9, 'name': 'Truk'}, {'id': 2, 'name': 'Mobil'}]
        self.documents = {
            'train': {
                'categories': categories,
                'images': [{'id': 0, 'file_name': 'train.png', 'width': 80, 'height': 60}],
                'annotations': [
                    {'id': 1, 'image_id': 0, 'category_id': 2, 'bbox': [20, 15, 40, 30]},
                    {'id': 2, 'image_id': 0, 'category_id': 9, 'bbox': [8, 6, 16, 12]},
                ],
            },
            'test': {
                'categories': list(reversed(categories)),
                'images': [{'id': 0, 'file_name': 'test.png', 'width': 80, 'height': 60}],
                'annotations': [{'id': 1, 'image_id': 0, 'category_id': 2, 'bbox': [20, 15, 40, 30]}],
            },
        }
        self.write_documents()

    def write_documents(self, documents=None):
        for split, document in (documents or self.documents).items():
            (self.root / self.config['coco_annotations'][split]).write_text(json.dumps(document))

    def test_prepare_uses_coco_labels_remaps_ids_and_preserves_split(self):
        # There are no YOLO .txt files, and ratios must not reshuffle existing COCO splits.
        manifest, summary = prepare(self.config, self.root)
        self.assertEqual(manifest['classes'], ['Mobil', 'Truk'])
        self.assertEqual([row['image'] for row in manifest['splits']['train']], ['data/images/train.png'])
        self.assertEqual([row['image'] for row in manifest['splits']['test']], ['data/images/test.png'])
        boxes = manifest['splits']['train'][0]['boxes']
        self.assertEqual([box['class_id'] for box in boxes], [1, 2])
        self.assertEqual(boxes[0], {'class_id': 1, 'xmin': .25, 'ymin': .25, 'xmax': .75, 'ymax': .75})
        self.assertEqual(summary['train']['objects'], {'Mobil': 1, 'Truk': 1})
        self.assertIn('Truk', manifest['warnings'][0])
        self.assertEqual(manifest['source']['category_id_to_class_id'], {'2': 1, '9': 2})
        verify_images(manifest, self.root)
        with self.assertRaisesRegex(ValueError, 'tidak ditimpa'):
            prepare(self.config, self.root)

    def test_coco_source_changes_invalidate_the_frozen_manifest(self):
        manifest, _ = prepare(self.config, self.root)
        path = self.root / self.config['coco_annotations']['train']
        path.write_text(path.read_text() + '\n')
        with self.assertRaisesRegex(ValueError, 'Anotasi COCO berubah/hilang'):
            verify_images(manifest, self.root)

    def test_images_without_annotations_are_preserved_as_background(self):
        Image.new('RGB', (80, 60), 'green').save(self.image_dir / 'background.png')
        self.documents['train']['images'].append(
            {'id': 3, 'file_name': 'background.png', 'width': 80, 'height': 60})
        self.write_documents()
        _, splits, _ = collect_coco_dataset(self.config, self.root)
        self.assertEqual(splits['train'][1]['boxes'], [])

    def test_training_refuses_a_manifest_from_another_format(self):
        from ferqueue_cv.training import load_manifest
        manifest, _ = prepare(self.config, self.root)
        # A COCO config must not silently train on an existing YOLO manifest.
        del manifest['source']
        path = self.root / self.config['prepared_dir'] / 'manifest.json'
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'Format sumber manifest berbeda'):
            load_manifest(self.config, self.root)

    def test_yolo_config_cannot_reuse_a_coco_manifest(self):
        from ferqueue_cv.training import load_manifest
        prepare(self.config, self.root)
        config = {**self.config, 'dataset_format': 'yolo'}
        with self.assertRaisesRegex(ValueError, 'Format sumber manifest berbeda'):
            load_manifest(config, self.root)

    def test_changed_annotation_paths_require_a_new_manifest(self):
        from ferqueue_cv.training import load_manifest
        prepare(self.config, self.root)
        config = {**self.config, 'coco_annotations': {
            **self.config['coco_annotations'], 'train': 'data/other-train.json'}}
        with self.assertRaisesRegex(ValueError, 'Path anotasi COCO berbeda'):
            load_manifest(config, self.root)

    def test_nested_image_paths_are_kept_relative_to_repo(self):
        folder = self.image_dir / 'session1'
        folder.mkdir()
        (self.image_dir / 'train.png').rename(folder / 'train.png')
        self.documents['train']['images'][0]['file_name'] = 'session1\\train.png'
        self.write_documents()
        _, splits, _ = collect_coco_dataset(self.config, self.root)
        self.assertEqual(splits['train'][0]['image'], 'data/images/session1/train.png')

    def test_rejects_invalid_boxes_instead_of_silently_dropping_them(self):
        for bbox in ([0, 0, 0, 10], [0, 0, 10, -1], [-1, 0, 10, 10],
                     [75, 0, 10, 10], [0, 55, 10, 10], [0, 0, float('nan'), 10],
                     [0, 0, float('inf'), 10], [True, 0, 10, 10], ['0', 0, 10, 10], [0, 0, 10]):
            with self.subTest(bbox=bbox):
                documents = copy.deepcopy(self.documents)
                documents['train']['annotations'][0]['bbox'] = bbox
                self.write_documents(documents)
                with self.assertRaisesRegex(ValueError, 'bbox'):
                    collect_coco_dataset(self.config, self.root)

    def test_rejects_invalid_annotation_references_and_crowds(self):
        for change in ({'image_id': 99}, {'category_id': 99}, {'image_id': True},
                       {'iscrowd': 1}, {'ignore': 1}, {'id': -1}):
            with self.subTest(change=change):
                documents = copy.deepcopy(self.documents)
                documents['train']['annotations'][0].update(change)
                self.write_documents(documents)
                with self.assertRaises(ValueError):
                    collect_coco_dataset(self.config, self.root)

    def test_rejects_duplicate_image_and_annotation_ids(self):
        for key in ('images', 'annotations'):
            with self.subTest(key=key):
                documents = copy.deepcopy(self.documents)
                documents['train'][key].append(copy.deepcopy(documents['train'][key][0]))
                self.write_documents(documents)
                with self.assertRaisesRegex(ValueError, 'duplikat'):
                    collect_coco_dataset(self.config, self.root)

    def test_rejects_invalid_or_inconsistent_categories(self):
        for categories in ([], [{'id': 2, 'name': ''}],
                           [{'id': 2, 'name': 'Mobil'}, {'id': 2, 'name': 'Truk'}],
                           [{'id': 2, 'name': 'Mobil'}, {'id': 9, 'name': 'Mobil'}],
                           [{'id': 2, 'name': 'Bus'}, {'id': 9, 'name': 'Truk'}]):
            with self.subTest(categories=categories):
                documents = copy.deepcopy(self.documents)
                documents['test']['categories'] = categories
                self.write_documents(documents)
                with self.assertRaises(ValueError):
                    collect_coco_dataset(self.config, self.root)

    def test_rejects_missing_images_size_mismatches_and_path_escape(self):
        for change in ({'file_name': 'missing.png'}, {'width': 81}, {'width': 0},
                       {'height': True}, {'file_name': '../outside.png'},
                       {'file_name': str(self.image_dir / 'train.png')}):
            with self.subTest(change=change):
                documents = copy.deepcopy(self.documents)
                documents['train']['images'][0].update(change)
                self.write_documents(documents)
                with self.assertRaises(ValueError):
                    collect_coco_dataset(self.config, self.root)

    def test_rejects_same_image_or_identical_copies_across_splits(self):
        documents = copy.deepcopy(self.documents)
        documents['test']['images'][0]['file_name'] = 'train.png'
        self.write_documents(documents)
        with self.assertRaisesRegex(ValueError, 'duplikat'):
            collect_coco_dataset(self.config, self.root)
        self.write_documents()
        (self.image_dir / 'test.png').write_bytes((self.image_dir / 'train.png').read_bytes())
        with self.assertRaisesRegex(ValueError, 'duplikat'):
            collect_coco_dataset(self.config, self.root)

    def test_rejects_malformed_documents(self):
        for document in ([], {}, {**self.documents['train'], 'images': []},
                         {**self.documents['train'], 'annotations': None}):
            with self.subTest(document=document):
                self.write_documents({'train': document})
                with self.assertRaises(ValueError):
                    collect_coco_dataset(self.config, self.root)

    def test_config_checks_coco_paths_and_rejects_ambiguous_sources(self):
        path = self.root / 'config.json'
        path.write_text(json.dumps(self.config))
        self.assertEqual(load_config('config.json', self.root), self.config)
        for change in (
                {'dataset_format': 'other'}, {'dataset_format': 'yolo'},
                {'coco_annotations': None}, {'coco_annotations': {'train': 'data/train.json'}},
                {'coco_annotations': {'train': '../outside.json', 'test': 'data/test.json'}},
                {'coco_annotations': {'train': '/outside.json', 'test': 'data/test.json'}},
                {'coco_annotations': {'train': 'data/train.json', 'test': 'data/train.json'}}):
            with self.subTest(change=change):
                path.write_text(json.dumps({**self.config, **change}))
                with self.assertRaises(ValueError):
                    load_config('config.json', self.root)

    def test_yolo_cleanup_refuses_coco_sources(self):
        with self.assertRaisesRegex(ValueError, 'hanya mendukung dataset YOLO'):
            audit_dataset(self.config, self.root)
        self.assertTrue((self.image_dir / 'train.png').is_file())

    def test_coco_training_initialization_writes_correct_tfrecords_and_pipeline(self):
        try:
            import tensorflow as tf
            from google.protobuf import text_format
            from object_detection.protos import pipeline_pb2
        except ImportError:
            self.skipTest('Integrasi COCO/TFRecord memerlukan environment training.')
        from ferqueue_cv.training import train
        manifest, _ = prepare(self.config, self.root)
        pretrained = self.root / 'pretrained'
        pretrained.mkdir()
        (pretrained / 'pipeline.config').write_text('model { ssd { num_classes: 90 } } eval_input_reader {}')
        with patch('ferqueue_cv.training.download_pretrained', return_value=pretrained), \
                patch('ferqueue_cv.training.subprocess.run') as launch:
            train(self.config, self.root)
            launch.assert_called_once()
        run = self.root / self.config['run_dir']
        frozen = json.loads((run / 'inputs.json').read_text())
        self.assertEqual(frozen['manifest'], manifest)
        pipeline = pipeline_pb2.TrainEvalPipelineConfig()
        text_format.Parse((run / 'pipeline.config').read_text(), pipeline)
        self.assertEqual(pipeline.model.ssd.num_classes, 2)
        self.assertIn('name: "Mobil"', (run / 'label_map.pbtxt').read_text())
        for split, labels in (('train', [1, 2]), ('test', [1])):
            records = list(tf.compat.v1.io.tf_record_iterator(str(run / 'records' / f'{split}.tfrecord')))
            self.assertEqual(len(records), 1)
            features = tf.train.Example.FromString(records[0]).features.feature
            self.assertEqual(list(features['image/object/class/label'].int64_list.value), labels)
            self.assertEqual(features['image/object/bbox/xmin'].float_list.value[0], .25)
            self.assertEqual(features['image/object/bbox/xmax'].float_list.value[0], .75)


if __name__ == '__main__':
    unittest.main()
