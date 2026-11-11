import os
import sys
import unittest
from unittest.mock import Mock, patch

from ferqueue_cv.__main__ import main
from ferqueue_cv.runtime import use_cpu
from ferqueue_cv.settings import DEFAULT_CONFIG


class TrainingRuntimeTests(unittest.TestCase):
    def test_serve_uses_current_default_config_and_forwards_port(self):
        config = {'run_dir': 'models/example'}
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(sys, 'argv', ['pcv.py', 'serve', '--port', '8001']), \
                patch('ferqueue_cv.__main__.configure_sources'), \
                patch('ferqueue_cv.__main__.load_config', return_value=config) as load, \
                patch('ferqueue_cv.live_api.serve') as serve:
            self.assertEqual(main(), 0)
            self.assertEqual(load.call_args.args[0], DEFAULT_CONFIG)
        serve.assert_called_once_with(config, load.call_args.args[1], '127.0.0.1', 8001, calibration_only=False)

    def test_explicit_config_overrides_environment_for_support_tools(self):
        for action, target in [('fix-tf-slim', 'ferqueue_cv.compat.fix_decoder'),
                               ('diagnose', 'ferqueue_cv.diagnostics.diagnose')]:
            with self.subTest(action=action), \
                    patch.dict(os.environ, {'CV_CONFIG_PATH': 'other.json'}), \
                    patch.object(sys, 'argv', ['pcv.py', action, '--config', 'chosen.json']), \
                    patch('ferqueue_cv.__main__.configure_sources'), \
                    patch('ferqueue_cv.__main__.load_config', return_value={}) as load, \
                    patch(target) as operation:
                self.assertEqual(main(), 0)
                self.assertEqual(load.call_args.args[0], 'chosen.json')
                operation.assert_called_once()

    def test_cpu_selection_is_inherited_by_training_subprocess(self):
        tensorflow = Mock()
        with patch.dict(sys.modules, {'tensorflow': tensorflow}), patch.dict(os.environ, {}, clear=True):
            use_cpu()
            self.assertEqual(os.environ['CUDA_VISIBLE_DEVICES'], '-1')
            tensorflow.config.set_visible_devices.assert_called_once_with([], 'GPU')

    def test_cli_trains_on_cpu_by_default_and_keeps_gpu_opt_in(self):
        for gpu in (False, True):
            arguments = ['ferqueue_cv', 'train'] + (['--require-gpu'] if gpu else [])
            with self.subTest(gpu=gpu), patch.object(sys, 'argv', arguments), \
                    patch('ferqueue_cv.__main__.configure_sources'), \
                    patch('ferqueue_cv.__main__.load_config', return_value={}), \
                    patch('ferqueue_cv.runtime.use_cpu') as cpu, \
                    patch('ferqueue_cv.runtime.require_gpu') as require_gpu, \
                    patch('ferqueue_cv.training.train') as train:
                self.assertEqual(main(), 0)
                train.assert_called_once()
                self.assertEqual(cpu.call_count, int(not gpu))
                self.assertEqual(require_gpu.call_count, int(gpu))


if __name__ == '__main__':
    unittest.main()
