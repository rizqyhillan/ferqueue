"""Read-only checks of training/exported weights and a few SavedModel predictions."""

import hashlib
import json
import os
from pathlib import Path


def compare_weights(training, exported):
    import numpy as np
    training_keys = {name for name in training.get_variable_to_shape_map() if name.startswith('model/')}
    exported_keys = {name for name in exported.get_variable_to_shape_map() if name.startswith('model/')}
    shared = sorted(training_keys & exported_keys)
    differences, invalid_training, invalid_export = [], [], []
    identical = 0
    for name in shared:
        left, right = np.asarray(training.get_tensor(name)), np.asarray(exported.get_tensor(name))
        left_finite = bool(np.isfinite(left).all())
        right_finite = bool(np.isfinite(right).all())
        if not left_finite:
            invalid_training.append(name)
        if not right_finite:
            invalid_export.append(name)
        if left.shape == right.shape and np.array_equal(left, right):
            identical += 1
            continue
        maximum = None
        if left.shape == right.shape and left_finite and right_finite and left.size:
            maximum = float(np.max(np.abs(left.astype(np.float64) - right.astype(np.float64))))
        differences.append({'name': name, 'training_shape': list(left.shape),
                            'exported_shape': list(right.shape), 'max_abs_difference': maximum})
    complete = bool(shared) and training_keys == exported_keys
    return {'training_variable_count': len(training_keys), 'exported_variable_count': len(exported_keys),
            'compared_variable_count': len(shared), 'identical_variable_count': identical,
            'all_model_weights_identical': complete and identical == len(shared) and not invalid_training and not invalid_export,
            'missing_from_export': sorted(training_keys - exported_keys),
            'extra_in_export': sorted(exported_keys - training_keys),
            'non_finite_training': invalid_training, 'non_finite_export': invalid_export,
            'different_variables': differences[:30], 'different_variable_count': len(differences)}


def global_step(reader):
    for name in ('step/.ATTRIBUTES/VARIABLE_VALUE', 'global_step/.ATTRIBUTES/VARIABLE_VALUE'):
        if name in reader.get_variable_to_shape_map():
            return int(reader.get_tensor(name))
    return None


def summarize_predictions(result, classes):
    import numpy as np
    count = int(np.asarray(result['num_detections'])[0])
    scores = np.asarray(result['detection_scores'])[0, :count]
    ids = np.asarray(result['detection_classes'])[0, :count].astype(int)
    boxes = np.asarray(result['detection_boxes'])[0, :count]
    if not (np.isfinite(scores).all() and np.isfinite(boxes).all()):
        raise ValueError('Prediksi model mengandung NaN atau infinity.')
    by_class = {}
    for index, name in enumerate(classes, 1):
        values = scores[ids == index]
        by_class[name] = float(values.max()) if values.size else None
    top = []
    for score, class_id, box in zip(scores[:5], ids[:5], boxes[:5]):
        top.append({'class_id': int(class_id),
                    'class_name': classes[class_id - 1] if 1 <= class_id <= len(classes) else 'unknown',
                    'confidence': float(score), 'bbox_yxyx_normalized': [float(value) for value in box]})
    return {'returned_detections': count, 'maximum_score_per_returned_class': by_class,
            'counts_at_threshold': {str(threshold): int((scores >= threshold).sum()) for threshold in (.25, .5)},
            'top_5': top}


def diagnose(config, root, output_path='outputs/model-diagnosis.json'):
    from .processing import preprocess_image
    from .settings import training_plan
    output = (root / output_path).resolve()
    if not output.is_relative_to(root.resolve()):
        raise ValueError('Laporan diagnosis harus berada di dalam repo.')
    run = root / config['run_dir']
    frozen = json.loads((run / 'inputs.json').read_text(encoding='utf-8'))
    metadata = json.loads((run / 'export.json').read_text(encoding='utf-8'))
    manifest = frozen['manifest']
    # This small diagnostic runs on CPU, so it does not depend on the shell's CUDA library paths.
    os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
    os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL', '2')
    import numpy as np
    import tensorflow as tf
    from PIL import Image

    print('Membaca checkpoint training dan ekspor...', flush=True)
    latest = tf.train.latest_checkpoint(str(run / 'training'))
    if not latest:
        raise ValueError('Checkpoint training tidak ditemukan pada run_dir ini.')
    reader = tf.train.load_checkpoint(latest)
    saved = root / metadata['saved_model']
    exported = tf.train.latest_checkpoint(str(saved.parent / 'checkpoint'))
    report = {'tensorflow_version': tf.__version__, 'classes': manifest['classes'],
              'configured_steps': training_plan(frozen['config'], manifest)['num_steps'],
              'checkpoint_global_step': global_step(reader),
              'latest_training_checkpoint': Path(latest).name, 'export_metadata_checkpoint': metadata['checkpoint'],
              'export_metadata_is_latest': metadata['checkpoint'] == Path(latest).name,
              'export_metadata_classes': metadata.get('classes'),
              'export_classes_match_manifest': metadata['classes'] == manifest['classes'] if 'classes' in metadata else None,
              'weight_comparison': None, 'samples': [],
              'notes': ['Skor per kelas berasal dari deteksi yang dikembalikan SavedModel setelah NMS.',
                        'Pemeriksaan ini tidak melatih ulang, mengekspor ulang, atau mengubah bobot.']}
    if exported:
        report['weight_comparison'] = compare_weights(reader, tf.train.load_checkpoint(exported))
    else:
        report['notes'].append('Checkpoint pendamping ekspor tidak ditemukan; perbandingan bobot dilewati.')

    print('Menguji satu gambar train per kelas dan gambar abu-abu...', flush=True)
    with tf.device('/CPU:0'):
        model = tf.saved_model.load(str(saved))
        detector = model.signatures['serving_default']
        for index, name in enumerate(manifest['classes'], 1):
            row = next((row for row in manifest['splits']['train'] if any(box['class_id'] == index for box in row['boxes'])), None)
            if row is None:
                report['samples'].append({'expected_class': name, 'error': 'Kelas tidak terdapat pada train.'})
                continue
            source = root / row['image']
            if not source.is_file():
                report['samples'].append({'image': row['image'], 'error': 'Gambar tidak ditemukan.'})
                continue
            with Image.open(source) as original:
                image = np.asarray(preprocess_image(original, metadata.get('preprocessing')), dtype=np.uint8)
            result = detector(tf.convert_to_tensor(image[None, ...]))
            report['samples'].append({'kind': 'train_image', 'image': row['image'], 'expected_class': name,
                                      'image_matches_training_manifest': hashlib.sha256(source.read_bytes()).hexdigest() == row['sha256'],
                                      'expected_class_ids': [box['class_id'] for box in row['boxes']],
                                      **summarize_predictions(result, manifest['classes'])})
        blank = np.asarray(preprocess_image(Image.new('RGB', (640, 640), (127, 127, 127)), metadata.get('preprocessing')))
        result = detector(tf.convert_to_tensor(blank[None, ...]))
        report['samples'].append({'kind': 'blank_gray_image', **summarize_predictions(result, manifest['classes'])})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    print(f'Langkah pada checkpoint: {report["checkpoint_global_step"]}', flush=True)
    if report['weight_comparison'] is not None:
        print(f'Bobot training dan ekspor identik: {report["weight_comparison"]["all_model_weights_identical"]}', flush=True)
    print(f'Laporan pemeriksaan: {output}', flush=True)
    return report
