"""Measure the official trainer without changing its optimization loop."""

from datetime import datetime, timezone
import json
import os
import platform
import re
import statistics
import subprocess
import time
from uuid import uuid4

STEP_TIME = re.compile(r'Step (\d+) per-step time ([0-9.]+)s')


def attempt_id():
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8]


def speed_summary(samples, batch_size, target_steps):
    # Each log covers 100 steps. Exclude the first block (graph tracing/warmup).
    # TF/absl can emit the same log twice; samples are keyed by global step.
    steady = [value for _, value in sorted(samples.items())[1:] if value > 0]
    seconds = statistics.mean(steady) if steady else None
    return {
        'warmup_blocks_excluded': 1 if samples else 0,
        'measured_steps': len(steady) * 100,
        'seconds_per_step': seconds,
        'images_per_second': batch_size / seconds if seconds else None,
        'estimated_training_seconds': {
            str(steps): seconds * steps for steps in sorted({target_steps, 3000, 6000})
        } if seconds else {},
        'estimate_scope': 'Steady training only; excludes initial setup/warmup, export and evaluation. Thermal/power changes can affect longer runs.',
    }


def run_measured(command, run, config, preparation_seconds, runtime, target_steps):
    reports = run / 'reports'
    reports.mkdir(exist_ok=True)
    identifier = attempt_id()
    log_path = reports / f'training-{identifier}.log'
    report_path = reports / f'training-{identifier}.json'
    report = {
        'started_at': datetime.now(timezone.utc).isoformat(),
        'status': 'failed',
        'requested_steps': config['num_steps'],
        'batch_size': config['batch_size'],
        'preparation_seconds': preparation_seconds,
        'runtime': {
            'platform': platform.platform(),
            'python': platform.python_version(),
            'logical_cpus': os.cpu_count(),
            'intraop_threads': os.environ.get('TF_NUM_INTRAOP_THREADS'),
            'interop_threads': os.environ.get('TF_NUM_INTEROP_THREADS'),
            **runtime,
        },
        'log': str(log_path),
    }
    samples = {}
    started = time.perf_counter()
    try:
        with log_path.open('w', encoding='utf-8') as log:
            with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, encoding='utf-8', errors='replace', bufsize=1) as process:
                try:
                    for line in process.stdout:
                        print(line, end='', flush=True)
                        log.write(line)
                        log.flush()
                        match = STEP_TIME.search(line)
                        if match:
                            samples[int(match[1])] = float(match[2])
                    code = process.wait()
                except BaseException:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    raise
        report['returncode'] = code
        if code:
            raise subprocess.CalledProcessError(code, command)
        report['status'] = 'completed'
    except KeyboardInterrupt:
        report['status'] = 'interrupted'
        raise
    finally:
        elapsed = time.perf_counter() - started
        report.update(training_process_seconds=elapsed, total_seconds=preparation_seconds + elapsed)
        report['step_samples'] = [{'step': step, 'seconds_per_step': value}
                                  for step, value in sorted(samples.items())]
        report.update(speed_summary(samples, config['batch_size'], target_steps))
        report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(f'\nDurasi proses training: {elapsed / 60:.2f} menit; termasuk persiapan: {report["total_seconds"] / 60:.2f} menit.', flush=True)
        if report['status'] == 'completed':
            if report['seconds_per_step']:
                print(f'Kecepatan setelah warmup: {report["seconds_per_step"]:.3f} detik/langkah; '
                      f'{report["images_per_second"]:.2f} gambar/detik.', flush=True)
                for steps, seconds in report['estimated_training_seconds'].items():
                    print(f'Estimasi {steps} langkah: {seconds / 60:.1f} menit ({seconds / 3600:.2f} jam), di luar persiapan/export/evaluasi.', flush=True)
            else:
                print('Belum cukup sampel setelah warmup untuk estimasi. Gunakan benchmark minimal 200 langkah.', flush=True)
        print(f'Laporan durasi: {report_path}\nLog: {log_path}', flush=True)
    return report
