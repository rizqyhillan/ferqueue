import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from ferqueue_cv.runtime import use_cpu
from ferqueue_cv.timing import run_measured, speed_summary


class TrainingTimingTests(unittest.TestCase):
    def test_warmup_and_duplicate_logs_do_not_bias_estimate(self):
        summary = speed_summary({100: 50, 200: 2, 300: 4}, 4, 3000)
        self.assertEqual(summary['seconds_per_step'], 3)
        self.assertEqual(summary['measured_steps'], 200)
        self.assertEqual(summary['estimated_training_seconds'], {'3000': 9000, '6000': 18000})
        self.assertAlmostEqual(summary['images_per_second'], 4 / 3)

    def test_resumed_session_excludes_its_own_first_block(self):
        self.assertEqual(speed_summary({800: 30, 900: 2}, 4, 3000)['seconds_per_step'], 2)
        self.assertIsNone(speed_summary({800: 30}, 4, 3000)['seconds_per_step'])
        self.assertEqual(speed_summary({}, 4, 3000)['estimated_training_seconds'], {})

    def test_real_subprocess_logs_are_saved_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            program = 'print("Step 100 per-step time 40.000s"); print("Step 200 per-step time 2.000s"); print("Step 200 per-step time 2.000s")'
            report = run_measured([sys.executable, '-c', program], run,
                                  {'num_steps': 200, 'batch_size': 4}, 1.5, {'device': 'CPU'}, 3000)
            saved = json.loads(next((run / 'reports').glob('*.json')).read_text())
            self.assertEqual(saved, report)
            self.assertEqual(report['status'], 'completed')
            self.assertEqual(report['seconds_per_step'], 2)
            self.assertEqual(report['measured_steps'], 100)
            self.assertGreaterEqual(report['total_seconds'], 1.5)
            self.assertEqual(Path(report['log']).read_text().count('Step 200'), 2)

    def test_failed_process_keeps_failure_report_and_log(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            with self.assertRaises(subprocess.CalledProcessError):
                run_measured([sys.executable, '-c', 'print("training error"); raise SystemExit(3)'],
                             run, {'num_steps': 200, 'batch_size': 4}, 0, {}, 3000)
            report = json.loads(next((run / 'reports').glob('*.json')).read_text())
            self.assertEqual(report['status'], 'failed')
            self.assertEqual(report['returncode'], 3)
            self.assertIn('training error', Path(report['log']).read_text())

class TrainingRuntimeTests(unittest.TestCase):
    def test_benchmark_is_isolated_and_preserves_source_config(self):
        from ferqueue_cv.training import benchmark
        config = {'run_dir': 'models/original', 'num_steps': 3000, 'batch_size': 4}
        with patch('ferqueue_cv.training.train') as train:
            benchmark(config, Path('/tmp'), 200)
            first = train.call_args.args[0]
            benchmark(config, Path('/tmp'), 200)
            second = train.call_args.args[0]
        self.assertEqual(config['run_dir'], 'models/original')
        self.assertEqual(config['num_steps'], 3000)
        self.assertEqual(first['num_steps'], 200)
        self.assertTrue(first['run_dir'].startswith('outputs/benchmarks/'))
        self.assertNotEqual(first['run_dir'], second['run_dir'])
        self.assertEqual(train.call_args.kwargs['target_steps'], 3000)
        for steps in (0, 100, 250, True):
            with self.subTest(steps=steps), self.assertRaises(ValueError):
                benchmark(config, Path('/tmp'), steps)

    def test_cpu_selection_is_inherited_by_training_subprocess(self):
        tensorflow = Mock()
        with patch.dict(sys.modules, {'tensorflow': tensorflow}), patch.dict(os.environ, {}, clear=True):
            use_cpu()
            self.assertEqual(os.environ['CUDA_VISIBLE_DEVICES'], '-1')
            tensorflow.config.set_visible_devices.assert_called_once_with([], 'GPU')

    def test_cli_trains_on_cpu_by_default_and_keeps_gpu_opt_in(self):
        from ferqueue_cv.__main__ import main
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
