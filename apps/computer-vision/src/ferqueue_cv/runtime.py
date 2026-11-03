"""Locate local training sources and preserve import paths for subprocesses."""

import os
from pathlib import Path
import sys


def configure_sources(root):
    source = root / 'apps/computer-vision/src'
    research = root / '.cache/tensorflow-models/research'
    paths = [str(source)]
    if (research / 'object_detection').is_dir():
        paths.extend([str(research), str(research / 'slim')])
    for path in reversed(paths):
        if path not in sys.path:
            sys.path.insert(0, path)
    inherited = os.environ.get('PYTHONPATH', '')
    os.environ['PYTHONPATH'] = os.pathsep.join(paths + ([inherited] if inherited else []))


def require_gpu():
    import tensorflow as tf
    devices = tf.config.list_physical_devices('GPU')
    if not devices:
        raise ValueError('GPU NVIDIA tidak terdeteksi oleh TensorFlow. Training dihentikan; jalankan check --require-gpu di WSL2.')
    for device in devices:
        tf.config.experimental.set_memory_growth(device, True)
    with tf.device('/GPU:0'):
        result = tf.matmul(tf.ones([32, 32]), tf.ones([32, 32]))
    if 'GPU' not in result.device.upper():
        raise ValueError('Operasi tes tidak memakai GPU. Periksa kecocokan GPU, driver, CUDA, dan TensorFlow.')
    result.numpy()
    print(f'GPU aktif: {devices[0].name}', flush=True)


def use_cpu():
    # Environment is inherited by the separate official training process, too.
    os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
    import tensorflow as tf
    tf.config.set_visible_devices([], 'GPU')
    print('Device training: CPU (Radeon iGPU tidak dipakai oleh backend TensorFlow ini).', flush=True)


def model_template(root):
    template = root / '.cache/tensorflow-models/research/object_detection/configs/tf2/ssd_mobilenet_v2_fpnlite_320x320_coco17_tpu-8.config'
    if not template.is_file():
        raise ValueError('Sumber Object Detection API belum siap. Jalankan bash scripts/cv.sh setup di Linux.')
    return template
