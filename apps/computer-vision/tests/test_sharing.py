import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from ferqueue_cv.sharing import import_model, package_model


class SharingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = {'run_dir': 'models/mobilenet/runs/trainer'}
        run = self.root / self.config['run_dir']
        saved = run / 'exports/ckpt-1/saved_model'
        (saved / 'variables').mkdir(parents=True)
        (saved / 'saved_model.pb').write_bytes(b'model-placeholder')
        (saved / 'variables/variables.index').write_bytes(b'index-placeholder')
        metadata = {'saved_model': saved.relative_to(self.root).as_posix(), 'classes': ['mobil'],
                    'model': 'ssd_mobilenet_v2_fpnlite_320x320_coco17_tpu-8', 'checkpoint': 'ckpt-1'}
        (run / 'export.json').write_text(json.dumps(metadata))
        (run / 'inputs.json').write_text('{"private_training_data": true}')
        self.archive = self.root / 'outputs/model.zip'

    def test_portable_package_excludes_training_metadata_and_rebases_path(self):
        package_model(self.config, self.root, self.archive)
        with zipfile.ZipFile(self.archive) as handle:
            self.assertNotIn('inputs.json', handle.namelist())
            self.assertEqual(json.loads(handle.read('model.json'))['classes'], ['mobil'])
        receiver = {'run_dir': 'models/mobilenet/runs/receiver'}
        import_model(receiver, self.root, self.archive)
        metadata = json.loads((self.root / receiver['run_dir'] / 'export.json').read_text())
        self.assertTrue((self.root / metadata['saved_model'] / 'saved_model.pb').is_file())
        self.assertEqual(metadata['classes'], ['mobil'])
        with self.assertRaisesRegex(ValueError, 'sudah memiliki'):
            import_model(receiver, self.root, self.archive)

    def test_rejects_path_traversal_and_unrelated_files(self):
        for name in ('../outside.txt', 'C:/outside.txt', 'saved_model/../../outside.txt', 'scripts/evil.py'):
            with self.subTest(name=name):
                archive = self.root / 'malformed.zip'
                with zipfile.ZipFile(archive, 'w') as handle:
                    handle.writestr(name, 'unsafe')
                with self.assertRaises(ValueError):
                    import_model({'run_dir': 'models/receiver'}, self.root, archive)
        self.assertFalse((self.root / 'outside.txt').exists())

    def test_package_does_not_overwrite_existing_archive(self):
        package_model(self.config, self.root, self.archive)
        with self.assertRaisesRegex(ValueError, 'sudah ada'):
            package_model(self.config, self.root, self.archive)


if __name__ == '__main__':
    unittest.main()
