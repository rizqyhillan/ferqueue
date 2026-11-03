import argparse
import json
import math
from pathlib import Path
import subprocess
import sys

from .runtime import configure_sources
from .dataset import validate_ratios


def load_config(path, root):
    config = json.loads((root / path).read_text(encoding='utf-8-sig'))
    for key in ('dataset_dir', 'prepared_dir', 'run_dir'):
        value = Path(config[key])
        if value.is_absolute() or not (root / value).resolve().is_relative_to(root):
            raise ValueError(f'{key} harus berupa path di dalam repo.')
    for key in ('batch_size', 'num_steps'):
        if type(config[key]) is not int or config[key] < 1:
            raise ValueError(f'{key} harus berupa bilangan bulat positif.')
    if config['num_steps'] < 10:
        raise ValueError('num_steps minimal 10.')
    for key in ('learning_rate', 'confidence_threshold'):
        if not isinstance(config[key], (int, float)) or not math.isfinite(config[key]):
            raise ValueError(f'{key} harus berupa angka finite.')
    if config['learning_rate'] <= 0 or not 0 <= config['confidence_threshold'] <= 1:
        raise ValueError('learning_rate harus positif dan confidence_threshold harus antara 0 dan 1.')
    if 'val_ratio' in config:
        raise ValueError('Konfigurasi lama masih berisi val_ratio. Gunakan train_ratio dan test_ratio dengan jumlah 1.')
    validate_ratios(config['train_ratio'], config['test_ratio'])
    if type(config['seed']) is not int:
        raise ValueError('seed harus bilangan bulat.')
    return config


def main():
    parser = argparse.ArgumentParser(description='Training deteksi kendaraan dari gambar LabelImg YOLO.')
    parser.add_argument('action', choices=['check', 'check-inference', 'prepare', 'clean-dataset', 'train', 'evaluate', 'export', 'predict', 'test', 'package-model', 'import-model'])
    parser.add_argument('--config', default='configs/training.json')
    parser.add_argument('--input', default='data/inference')
    parser.add_argument('--output', default='outputs/predictions')
    parser.add_argument('--split', choices=['test'], default='test')
    parser.add_argument('--require-gpu', action='store_true')
    parser.add_argument('--archive', default='outputs/ssd-model.zip')
    parser.add_argument('--dry-run', action='store_true', help='clean-dataset: buat laporan saja, tanpa pertanyaan atau perubahan dataset.')
    args = parser.parse_args()
    root = Path.cwd().resolve()
    configure_sources(root)
    try:
        config = load_config(args.config, root)
        if args.require_gpu:
            from .runtime import require_gpu
            require_gpu()
        elif args.action in ('check', 'train'):
            from .runtime import use_cpu
            use_cpu()
        if args.action == 'test':
            subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s',
                            'apps/computer-vision/tests', '-v'], check=True)
        elif args.action == 'clean-dataset':
            from .cleanup import clean_dataset
            clean_dataset(config, root, dry_run=args.dry_run)
        elif args.action == 'prepare':
            from .dataset import prepare
            manifest, summary = prepare(config, root)
            print(json.dumps({'splits': summary, 'warnings': manifest['warnings']}, indent=2))
            print(f'Dataset siap: {config["prepared_dir"]}/manifest.json')
        elif args.action == 'check-inference':
            import tensorflow as tf
            print(f'TensorFlow {tf.__version__}; environment prediksi gambar siap.')
        elif args.action in ('package-model', 'import-model'):
            from .sharing import package_model, import_model
            archive = (root / args.archive).resolve()
            if not archive.is_relative_to(root):
                raise ValueError('Arsip model harus berada di dalam repo.')
            (package_model if args.action == 'package-model' else import_model)(config, root, archive)
        elif args.action == 'check':
            subprocess.run([sys.executable, str(root / 'scripts/fix_tf_slim.py'), '--check-only'], check=True)
            import tensorflow as tf
            from object_detection.builders import model_builder
            from object_detection.utils import config_util
            print(f'TensorFlow: {tf.__version__}; GPU: {tf.config.list_physical_devices("GPU")}')
            from .runtime import model_template
            template = model_template(root)
            model_config = config_util.get_configs_from_pipeline_file(str(template))['model']
            model_config.ssd.num_classes = 2
            detector = model_builder.build(model_config=model_config, is_training=False)
            images, shapes = detector.preprocess(tf.zeros([1, 320, 320, 3], dtype=tf.float32))
            detector.postprocess(detector.predict(images, shapes), shapes)
            print('Object Detection API dan forward pass SSD MobileNet V2 FPNLite siap (bobot acak untuk tes environment).')
        else:
            from . import training
            if args.action == 'predict':
                for value in (args.input, args.output):
                    if not (root / value).resolve().is_relative_to(root):
                        raise ValueError('Input/output harus berada di dalam repo.')
                training.predict(config, root, args.input, args.output)
            elif args.action == 'evaluate':
                training.evaluate(config, root, args.split)
            else:
                getattr(training, args.action)(config, root)
    except (ValueError, OSError, KeyError, ImportError, subprocess.CalledProcessError) as error:
        print(f'GAGAL: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
