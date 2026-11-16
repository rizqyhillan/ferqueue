import importlib.util
from pathlib import Path
import tempfile
import unittest

from ferqueue_cv import compat


class SlimCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'tfexample_decoder.py'

    def test_case_and_cond_use_public_compatibility_api(self):
        source = compat.OLD_IMPORT + '\ncase = control_flow_ops.case\ncond = control_flow_ops.cond\n'
        self.path.write_text(source)
        self.assertTrue(compat.patch_decoder(self.path))
        updated = self.path.read_text()
        self.assertIn(compat.NEW_IMPORT, updated)
        self.assertNotIn(compat.OLD_IMPORT, updated)
        self.assertIn('case = control_flow_ops.case', updated)
        self.assertIn('cond = control_flow_ops.cond', updated)
        compile(updated, str(self.path), 'exec')
        self.assertFalse(compat.patch_decoder(self.path))
        self.assertEqual(self.path.read_text(), updated)

    def test_unknown_legacy_layout_is_preserved(self):
        source = 'import unknown as control_flow_ops\nresult = control_flow_ops.case([])\n'
        self.path.write_text(source)
        with self.assertRaisesRegex(ValueError, 'tidak dikenali'):
            compat.patch_decoder(self.path)
        self.assertEqual(self.path.read_text(), source)

    def test_modern_decoder_is_not_modified(self):
        source = 'from tensorflow.python.ops import control_flow_case\n'
        self.path.write_text(source)
        self.assertFalse(compat.patch_decoder(self.path))
        self.assertEqual(self.path.read_text(), source)

    def test_real_jpeg_png_graph_decoder(self):
        if importlib.util.find_spec('tensorflow') is None or importlib.util.find_spec('tf_slim') is None:
            self.skipTest('Tes graph decoder memerlukan environment TensorFlow di laptop training.')
        compat.check_decoder()


if __name__ == '__main__':
    unittest.main()
