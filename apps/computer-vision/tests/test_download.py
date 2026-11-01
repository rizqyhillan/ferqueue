import io
from pathlib import Path
import tarfile
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

from ferqueue_cv.training import MODEL_NAME, MODEL_URL, download_pretrained


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def archive(self):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w:gz') as handle:
            for name, data in {'pipeline.config': b'model {}', 'checkpoint/ckpt-0.index': b'index',
                               'checkpoint/ckpt-0.data-00000-of-00001': b'weights'}.items():
                member = tarfile.TarInfo(f'{MODEL_NAME}/{name}')
                member.size = len(data)
                handle.addfile(member, io.BytesIO(data))
        buffer.seek(0)
        return buffer

    def test_download_uses_canonical_https_endpoint_and_extracts_model(self):
        with patch('ferqueue_cv.training.urllib.request.urlopen', return_value=self.archive()) as request:
            target = download_pretrained(self.root)
        expected = f'https://storage.googleapis.com/download.tensorflow.org/models/object_detection/tf2/20200711/{MODEL_NAME}.tar.gz'
        self.assertEqual(MODEL_URL, expected)
        request.assert_called_once_with(expected, timeout=120)
        self.assertTrue((target / 'pipeline.config').is_file())
        self.assertTrue((target / 'checkpoint/ckpt-0.data-00000-of-00001').is_file())
        self.assertFalse(list(target.parent.glob('*.download')))
        with patch('ferqueue_cv.training.urllib.request.urlopen') as request:
            self.assertEqual(download_pretrained(self.root), target)
            request.assert_not_called()

    def test_failed_download_does_not_leave_partial_file(self):
        with patch('ferqueue_cv.training.urllib.request.urlopen', side_effect=urllib.error.URLError('TLS failure')):
            with self.assertRaises(urllib.error.URLError):
                download_pretrained(self.root)
        self.assertFalse(list((self.root / 'models/mobilenet/pretrained').glob('*.download')))


if __name__ == '__main__':
    unittest.main()
