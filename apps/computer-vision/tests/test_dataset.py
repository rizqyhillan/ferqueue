import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from ferqueue_cv.dataset import collect_dataset, prepare, read_boxes, split_groups, verify_images
from ferqueue_cv.__main__ import load_config


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.dataset = self.root / 'data/raw/vehicles'
        self.dataset.mkdir(parents=True)
        (self.dataset / 'classes.txt').write_text('mobil\ntruk\n', encoding='utf-8')
        self.config = {'dataset_dir': 'data/raw/vehicles', 'prepared_dir': 'data/processed/v1',
                       'run_dir': 'models/run1', 'train_ratio': .8, 'test_ratio': .2,
                       'seed': 42, 'batch_size': 4, 'num_steps': 100, 'learning_rate': .004,
                       'confidence_threshold': .5}

    def make_image(self, relative, color):
        path = self.dataset / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new('RGB', (80, 60), color=color).save(path)
        path.with_suffix('.txt').write_text('0 0.5 0.5 0.5 0.5\n1 0.5 0.5 0.2 0.2\n')
        return path

    def populate(self):
        for index in range(12):
            self.make_image(f'session-{index // 2}/vehicle-{index}.png', (index * 20, 50, 100))

    def test_yolo_to_tensorflow_class_ids_and_coordinates(self):
        path = self.make_image('one.png', 'red')
        boxes = read_boxes(path.with_suffix('.txt'), 2)
        self.assertEqual([box['class_id'] for box in boxes], [1, 2])
        self.assertEqual([boxes[0][key] for key in ('xmin', 'ymin', 'xmax', 'ymax')], [.25, .25, .75, .75])

    def test_rejects_missing_labels_instead_of_silent_background(self):
        path = self.make_image('one.png', 'red')
        path.with_suffix('.txt').unlink()
        with self.assertRaisesRegex(ValueError, 'Label tidak ditemukan'):
            collect_dataset(self.dataset, self.root)

    def test_empty_label_is_valid_background(self):
        path = self.make_image('one.png', 'red')
        path.with_suffix('.txt').write_text('')
        _, rows = collect_dataset(self.dataset, self.root)
        self.assertEqual(rows[0]['boxes'], [])

    def test_rejects_invalid_yolo_rows(self):
        path = self.make_image('one.png', 'red').with_suffix('.txt')
        for line in ['2 .5 .5 .2 .2', '0 nan .5 .2 .2', '0 .1 .5 .8 .2', '0 .5 .5 0 .2', '0 .5 .5 .2']:
            with self.subTest(line=line):
                path.write_text(line)
                with self.assertRaises(ValueError):
                    read_boxes(path, 2)

    def test_group_split_is_repeatable_and_no_video_leaks(self):
        self.populate()
        _, rows = collect_dataset(self.dataset, self.root)
        first = split_groups(rows, .8, .2, 42)
        self.assertEqual(first, split_groups(rows, .8, .2, 42))
        self.assertEqual(set(first), {'train', 'test'})
        groups = [{row['group'] for row in first[name]} for name in ('train', 'test')]
        self.assertTrue(all(groups))
        self.assertFalse(groups[0] & groups[1])
        self.assertEqual(sum(map(len, first.values())), 12)

    def test_groups_csv_overrides_flat_files(self):
        self.make_image('a.png', 'red')
        self.make_image('b.png', 'blue')
        (self.dataset / 'groups.csv').write_text('image,group\na.png,video1\nb.png,video1\n')
        _, rows = collect_dataset(self.dataset, self.root)
        self.assertEqual({row['group'] for row in rows}, {'video1'})
        with self.assertRaisesRegex(ValueError, 'minimal 2 kelompok'):
            split_groups(rows, .8, .2, 42)

    def test_train_test_ratios_and_small_group_sets(self):
        rows = [{'group': str(index)} for index in range(100)]
        splits = split_groups(rows, .8, .2, 42)
        self.assertEqual((len(splits['train']), len(splits['test'])), (80, 20))
        small = split_groups(rows[:2], .8, .2, 42)
        self.assertEqual((len(small['train']), len(small['test'])), (1, 1))
        for train_ratio, test_ratio in ((.8, .3), (1, 0), (float('nan'), .2), (True, .2)):
            with self.subTest(train_ratio=train_ratio, test_ratio=test_ratio):
                with self.assertRaises(ValueError):
                    split_groups(rows, train_ratio, test_ratio, 42)

    def test_old_three_way_manifest_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'train dan test saja'):
            verify_images({'splits': {'train': [{}], 'val': [{}], 'test': [{}]}}, self.root)

    def test_duplicate_content_is_rejected(self):
        self.make_image('a.png', 'red')
        self.make_image('b.png', 'red')
        with self.assertRaisesRegex(ValueError, 'duplikat'):
            collect_dataset(self.dataset, self.root)

    def test_nested_class_order_mismatch_is_rejected(self):
        self.make_image('session1/a.png', 'red')
        (self.dataset / 'session1/classes.txt').write_text('truk\nmobil\n')
        with self.assertRaisesRegex(ValueError, 'Urutan kelas berbeda'):
            collect_dataset(self.dataset, self.root)

    def test_separate_images_and_labels_layout(self):
        path = self.make_image('images/s1/a.png', 'red')
        label = self.dataset / 'labels/s1/a.txt'
        label.parent.mkdir(parents=True)
        path.with_suffix('.txt').replace(label)
        _, rows = collect_dataset(self.dataset, self.root)
        self.assertEqual(rows[0]['group'], 's1')
        self.assertEqual(rows[0]['image'], 'data/raw/vehicles/images/s1/a.png')

    def test_prepare_freezes_split_and_checks_changed_images(self):
        self.populate()
        manifest, summary = prepare(self.config, self.root)
        self.assertEqual(set(manifest['splits']), {'train', 'test'})
        self.assertEqual(set(summary), {'train', 'test'})
        self.assertEqual((manifest['train_ratio'], manifest['test_ratio']), (.8, .2))
        self.assertEqual(sum(part['images'] for part in summary.values()), 12)
        verify_images(manifest, self.root)
        with self.assertRaisesRegex(ValueError, 'tidak ditimpa'):
            prepare(self.config, self.root)
        (self.root / manifest['splits']['train'][0]['image']).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'berubah/hilang'):
            verify_images(manifest, self.root)

    def test_rejects_orphan_label_and_shared_basename(self):
        self.make_image('a.png', 'red')
        (self.dataset / 'orphan.txt').write_text('')
        with self.assertRaisesRegex(ValueError, 'tanpa pasangan'):
            collect_dataset(self.dataset, self.root)
        (self.dataset / 'orphan.txt').unlink()
        Image.new('RGB', (80, 60), color='blue').save(self.dataset / 'a.jpg')
        with self.assertRaisesRegex(ValueError, 'label yang sama'):
            collect_dataset(self.dataset, self.root)

    def test_config_rejects_path_escape_and_invalid_steps(self):
        path = self.root / 'config.json'
        for change in ({'run_dir': '../outside'}, {'num_steps': 0}, {'batch_size': True}, {'learning_rate': -1},
                       {'train_ratio': .7}, {'val_ratio': .15}):
            with self.subTest(change=change):
                path.write_text(json.dumps({**self.config, **change}))
                with self.assertRaises(ValueError):
                    load_config('config.json', self.root)


    def test_tensorflow_records_preserve_boxes_and_class_ids(self):
        try:
            import tensorflow as tf
        except ImportError:
            self.skipTest('Tes TFRecord/pipeline memerlukan environment training di laptop NVIDIA.')
        from ferqueue_cv.training import make_pipeline, write_records
        self.populate()
        manifest, _ = prepare(self.config, self.root)
        output = self.root / 'records'
        write_records(manifest, output, self.root)
        self.assertEqual(set(manifest['splits']), {'train', 'test'})
        for split in ('train', 'test'):
            records = list(tf.data.TFRecordDataset(str(output / f'{split}.tfrecord')))
            self.assertEqual(len(records), len(manifest['splits'][split]))
            example = tf.train.Example.FromString(bytes(records[0].numpy()))
            features = example.features.feature
            self.assertEqual(list(features['image/object/class/label'].int64_list.value), [1, 2])
            self.assertEqual(list(features['image/object/bbox/xmin'].float_list.value)[0], .25)
        from google.protobuf import text_format
        from object_detection.protos import pipeline_pb2
        pretrained = self.root / 'pretrained'
        pretrained.mkdir()
        (pretrained / 'pipeline.config').write_text('model { ssd { num_classes: 90 } } eval_input_reader {}')
        make_pipeline(self.config, manifest, pretrained, self.root)
        pipeline = pipeline_pb2.TrainEvalPipelineConfig()
        text_format.Parse((self.root / 'pipeline.config').read_text(), pipeline)
        self.assertEqual(pipeline.model.ssd.num_classes, 2)
        self.assertEqual(pipeline.train_config.fine_tune_checkpoint_type, 'detection')
        self.assertEqual(pipeline.train_config.batch_size, 4)
        self.assertEqual(pipeline.train_config.optimizer.momentum_optimizer.learning_rate.cosine_decay_learning_rate.total_steps, 100)
        self.assertTrue(pipeline.eval_input_reader[0].tf_record_input_reader.input_path[0].endswith('test.tfrecord'))


if __name__ == '__main__':
    unittest.main()
