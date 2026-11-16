import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from .runtime import configure_sources
from .settings import DEFAULT_CONFIG, load_config


def main():
    parser = argparse.ArgumentParser(description='Training deteksi kendaraan dari anotasi YOLO atau COCO JSON.')
    parser.add_argument('action', choices=['check', 'check-inference', 'fix-tf-slim', 'diagnose', 'serve', 'stage-yolo', 'adopt-coco', 'inspect', 'prepare', 'plan', 'preview', 'segment', 'build-records', 'clean-dataset', 'train', 'evaluate', 'export', 'predict', 'test', 'package-model', 'import-model'])
    parser.add_argument('--config', default=os.environ.get('CV_CONFIG_PATH', DEFAULT_CONFIG))
    parser.add_argument('--input', default='data/inference')
    parser.add_argument('--output', help='Folder hasil; default berbeda untuk setiap tahapan.')
    parser.add_argument('--split', choices=['train', 'test'], help='evaluate: test; preview/segment: default train.')
    parser.add_argument('--staging', default='data/processed/pcv-converter-v2', help='adopt-coco: folder input converter hasil stage-yolo.')
    parser.add_argument('--limit', type=int, default=12, help='Jumlah gambar preview/segment, default 12; 0 untuk semua gambar pada split.')
    parser.add_argument('--require-gpu', action='store_true')
    parser.add_argument('--archive', default='outputs/ssd-model.zip')
    parser.add_argument('--host', default='127.0.0.1', help='serve: alamat listener PCV.')
    parser.add_argument('--port', type=int, default=8000, help='serve: port API PCV.')
    parser.add_argument('--calibration-only', action='store_true', help='serve: kalibrasi koin tanpa memuat model deteksi.')
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
        elif args.action == 'fix-tf-slim':
            from .compat import fix_decoder
            fix_decoder()
        elif args.action == 'diagnose':
            from .diagnostics import diagnose
            diagnose(config, root, args.output or 'outputs/model-diagnosis.json')
        elif args.action == 'serve':
            from .live_api import serve
            serve(config, root, args.host, args.port, calibration_only=args.calibration_only)
        elif args.action == 'clean-dataset':
            from .cleanup import clean_dataset
            clean_dataset(config, root, dry_run=args.dry_run)
        elif args.action in ('stage-yolo', 'adopt-coco', 'inspect'):
            from .conversion import stage_yolo, adopt_coco, inspect_dataset
            if args.action == 'stage-yolo':
                stage_yolo(config, root, args.output or 'data/processed/pcv-converter-v2')
            elif args.action == 'adopt-coco':
                adopt_coco(config, root, args.staging, args.input, args.output or 'data/processed/pcv-coco-v2')
            else:
                print(json.dumps(inspect_dataset(config, root), indent=2, ensure_ascii=False))
        elif args.action == 'prepare':
            from .dataset import prepare
            manifest, summary = prepare(config, root)
            print(json.dumps({'splits': summary, 'warnings': manifest['warnings']}, indent=2))
            print(f'Dataset siap: {config["prepared_dir"]}/manifest.json')
        elif args.action in ('preview', 'segment'):
            from .processing import preview_dataset
            preview_dataset(config, root, args.output or f'outputs/pcv-{args.action}',
                            args.split or 'train', args.limit, segment=args.action == 'segment')
        elif args.action == 'plan':
            from .training import load_manifest
            from .settings import training_plan
            print(json.dumps(training_plan(config, load_manifest(config, root)), indent=2))
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
            from .compat import check_decoder
            check_decoder()
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
                output = args.output or 'outputs/predictions'
                for value in (args.input, output):
                    if not (root / value).resolve().is_relative_to(root):
                        raise ValueError('Input/output harus berada di dalam repo.')
                training.predict(config, root, args.input, output)
            elif args.action == 'evaluate':
                training.evaluate(config, root, args.split)
            elif args.action == 'build-records':
                training.build_records(config, root)
            else:
                getattr(training, args.action)(config, root)
    except (ValueError, OSError, KeyError, ImportError, subprocess.CalledProcessError) as error:
        print(f'GAGAL: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
