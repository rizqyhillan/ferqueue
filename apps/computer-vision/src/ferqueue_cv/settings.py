"""Validate experiment settings without importing TensorFlow or OpenCV."""

import json
import math
from pathlib import Path

from .dataset import validate_ratios

DEFAULT_CONFIG = 'apps/computer-vision/configs/coco.json'
DISPLAY_KEYS = {'confidence_threshold', 'nms_iou_threshold', 'max_detections', 'class_agnostic_nms'}


def positive_int(config, key, default=None):
    value = config.get(key, default)
    if type(value) is not int or value < 1:
        raise ValueError(f'{key} harus berupa bilangan bulat positif.')
    return value


def number(value, key, minimum, maximum=None):
    if type(value) not in (int, float) or not math.isfinite(value) or value < minimum or (
            maximum is not None and value > maximum):
        raise ValueError(f'{key} harus berupa angka finite dalam rentang {minimum}–{maximum or "tak terbatas"}.')


def validate_processing(config):
    processing = config.get('preprocessing', {})
    allowed = {'denoise_kernel', 'clahe_clip_limit', 'clahe_grid_size', 'gamma'}
    if not isinstance(processing, dict) or set(processing) - allowed:
        raise ValueError(f'preprocessing hanya menerima {sorted(allowed)}.')
    kernel = processing.get('denoise_kernel', 0)
    if type(kernel) is not int or kernel not in (0, 3, 5, 7):
        raise ValueError('denoise_kernel harus 0 (mati), 3, 5, atau 7.')
    number(processing.get('clahe_clip_limit', 0), 'clahe_clip_limit', 0, 10)
    grid = positive_int(processing, 'clahe_grid_size', 8)
    if grid > 64:
        raise ValueError('clahe_grid_size maksimal 64.')
    number(processing.get('gamma', 1), 'gamma', .1, 5)
    segmentation = config.get('segmentation', {})
    if not isinstance(segmentation, dict) or set(segmentation) - {'iterations', 'morphology_kernel'}:
        raise ValueError('segmentation hanya menerima iterations dan morphology_kernel.')
    if positive_int(segmentation, 'iterations', 5) > 50:
        raise ValueError('iterations GrabCut maksimal 50.')
    if type(segmentation.get('morphology_kernel', 3)) is not int or segmentation.get('morphology_kernel', 3) not in (0, 3, 5, 7):
        raise ValueError('morphology_kernel harus 0, 3, 5, atau 7.')


def load_config(path, root):
    root = Path(root).resolve()
    config = json.loads((root / path).read_text(encoding='utf-8-sig'))
    for key in ('dataset_dir', 'prepared_dir', 'run_dir'):
        value = Path(config[key])
        if value.is_absolute() or not (root / value).resolve().is_relative_to(root):
            raise ValueError(f'{key} harus berupa path di dalam repo.')
    dataset_format = config.get('dataset_format', 'yolo')
    if dataset_format not in ('yolo', 'coco'):
        raise ValueError('dataset_format harus yolo atau coco.')
    if dataset_format == 'coco':
        from .coco_dataset import annotation_paths
        annotation_paths(config, root)
    elif 'coco_annotations' in config:
        raise ValueError('Gunakan dataset_format coco jika konfigurasi berisi coco_annotations.')
    positive_int(config, 'batch_size')
    if ('epochs' in config) == ('num_steps' in config):
        raise ValueError('Isi salah satu saja: epochs atau num_steps.')
    key = 'epochs' if 'epochs' in config else 'num_steps'
    positive_int(config, key)
    if key == 'num_steps' and config[key] < 10:
        raise ValueError('num_steps minimal 10.')
    number(config['learning_rate'], 'learning_rate', 1e-12)
    number(config['confidence_threshold'], 'confidence_threshold', 0, 1)
    number(config.get('nms_iou_threshold', .45), 'nms_iou_threshold', 0, 1)
    positive_int(config, 'max_detections', 10)
    positive_int(config, 'checkpoint_every_n', 100)
    for key in ('class_agnostic_nms', 'freeze_batchnorm'):
        if key in config and type(config[key]) is not bool:
            raise ValueError(f'{key} harus true atau false.')
    if 'val_ratio' in config:
        raise ValueError('Gunakan train dan test saja. Hapus val_ratio dan pastikan kedua rasio berjumlah 1.')
    validate_ratios(config['train_ratio'], config['test_ratio'])
    if type(config['seed']) is not int:
        raise ValueError('seed harus bilangan bulat.')
    augmentation = config.get('augmentation')
    if 'augmentation' in config:
        if not isinstance(augmentation, dict) or set(augmentation) - {'horizontal_flip', 'brightness_delta'}:
            raise ValueError('augmentation hanya menerima horizontal_flip dan brightness_delta.')
        if type(augmentation.get('horizontal_flip', False)) is not bool:
            raise ValueError('horizontal_flip harus true atau false.')
        number(augmentation.get('brightness_delta', 0), 'brightness_delta', 0, 1)
    validate_processing(config)
    return config


def training_plan(config, manifest):
    count = len(manifest['splits']['train'])
    if not count:
        raise ValueError('Split training kosong.')
    steps_per_epoch = math.ceil(count / config['batch_size'])
    steps = config['epochs'] * steps_per_epoch if 'epochs' in config else config['num_steps']
    if steps < 10:
        raise ValueError('Total training minimal 10 langkah. Tambah epochs atau num_steps.')
    return {'train_images': count, 'batch_size': config['batch_size'],
            'steps_per_epoch': steps_per_epoch, 'num_steps': steps,
            'requested_epochs': config.get('epochs'),
            'approximate_passes': steps * config['batch_size'] / count}


def training_identity(config):
    """Display filtering and review-only masks do not affect training inputs."""
    return {key: value for key, value in config.items() if key not in DISPLAY_KEYS | {'segmentation'}}
