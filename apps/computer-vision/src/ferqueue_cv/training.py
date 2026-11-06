"""TensorFlow-specific operations; imported only inside the training environment."""

import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import urllib.request

from PIL import Image, ImageDraw, ImageOps

from .dataset import IMAGE_EXTENSIONS, verify_images
from .processing import preprocess_image
from .settings import training_identity, training_plan

MODEL_NAME = 'ssd_mobilenet_v2_fpnlite_320x320_coco17_tpu-8'
# Use the bucket's canonical HTTPS endpoint; the custom hostname can fail TLS hostname validation.
MODEL_URL = f'https://storage.googleapis.com/download.tensorflow.org/models/object_detection/tf2/20200711/{MODEL_NAME}.tar.gz'


def load_manifest(config, root):
    path = root / config['prepared_dir'] / 'manifest.json'
    if not path.is_file():
        raise ValueError('Dataset belum disiapkan. Jalankan prepare terlebih dahulu.')
    manifest = json.loads(path.read_text(encoding='utf-8'))
    source = manifest.get('source', {})
    if config.get('dataset_format', 'yolo') != source.get('format', 'yolo'):
        raise ValueError('Format sumber manifest berbeda dari konfigurasi. Gunakan prepared_dir baru dan jalankan prepare.')
    if source.get('format') == 'coco':
        expected = {split: Path(value).as_posix() for split, value in config['coco_annotations'].items()}
        actual = {split: item['path'] for split, item in source['annotations'].items()}
        if expected != actual:
            raise ValueError('Path anotasi COCO berbeda dari manifest. Gunakan prepared_dir baru dan jalankan prepare.')
    if set(manifest['splits']) != {'train', 'test'}:
        raise ValueError('Split konfigurasi berbeda dari manifest. Gunakan prepared_dir dan run_dir baru.')
    for key in ('seed', 'train_ratio', 'test_ratio'):
        if config.get(key) != manifest.get(key):
            raise ValueError(f'{key} berbeda dari manifest. Gunakan prepared_dir dan run_dir baru.')
    verify_images(manifest, root)
    return manifest


def _bytes(values):
    import tensorflow as tf
    return tf.train.Feature(bytes_list=tf.train.BytesList(value=values))


def _ints(values):
    import tensorflow as tf
    return tf.train.Feature(int64_list=tf.train.Int64List(value=values))


def _floats(values):
    import tensorflow as tf
    return tf.train.Feature(float_list=tf.train.FloatList(value=values))


def write_records(manifest, directory, root, preprocessing=None):
    import tensorflow as tf
    directory.mkdir(parents=True, exist_ok=True)
    for split, rows in manifest['splits'].items():
        temporary = directory / f'{split}.tfrecord.partial'
        with tf.io.TFRecordWriter(str(temporary)) as writer:
            for row in rows:
                # Lossless RGB keeps training/evaluation transforms consistent.
                buffer = io.BytesIO()
                with Image.open(root / row['image']) as image:
                    preprocess_image(image, preprocessing).save(buffer, format='PNG')
                boxes = row['boxes']
                example = tf.train.Example(features=tf.train.Features(feature={
                    'image/height': _ints([row['height']]),
                    'image/width': _ints([row['width']]),
                    'image/filename': _bytes([row['image'].encode()]),
                    'image/source_id': _bytes([row['sha256'].encode()]),
                    'image/encoded': _bytes([buffer.getvalue()]),
                    'image/format': _bytes([b'png']),
                    'image/object/bbox/xmin': _floats([b['xmin'] for b in boxes]),
                    'image/object/bbox/xmax': _floats([b['xmax'] for b in boxes]),
                    'image/object/bbox/ymin': _floats([b['ymin'] for b in boxes]),
                    'image/object/bbox/ymax': _floats([b['ymax'] for b in boxes]),
                    'image/object/class/text': _bytes([manifest['classes'][b['class_id'] - 1].encode() for b in boxes]),
                    'image/object/class/label': _ints([b['class_id'] for b in boxes]),
                    'image/object/is_crowd': _ints([0] * len(boxes)),
                }))
                writer.write(example.SerializeToString())
        temporary.replace(directory / f'{split}.tfrecord')


def download_pretrained(root):
    parent = root / 'models/mobilenet/pretrained'
    target = parent / MODEL_NAME
    if (target / 'pipeline.config').is_file() and (target / 'checkpoint/ckpt-0.index').is_file():
        return target
    parent.mkdir(parents=True, exist_ok=True)
    archive = parent / f'{MODEL_NAME}.tar.gz'
    partial = archive.with_suffix('.download')
    print(f'Mengunduh checkpoint resmi: {MODEL_URL}', flush=True)
    try:
        with urllib.request.urlopen(MODEL_URL, timeout=120) as response, partial.open('wb') as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        partial.replace(archive)
        with tarfile.open(archive, 'r:gz') as handle:
            # Extract only regular files/directories under the expected model directory.
            members = handle.getmembers()
            for member in members:
                destination = (parent / member.name).resolve()
                if not destination.is_relative_to(target.resolve()) or not (member.isfile() or member.isdir()):
                    raise ValueError(f'Isi arsip model tidak valid: {member.name}')
            handle.extractall(parent, members=members)
    finally:
        partial.unlink(missing_ok=True)
    if not (target / 'checkpoint/ckpt-0.index').is_file():
        raise ValueError('Checkpoint pretrained tidak lengkap. Periksa unduhan.')
    return target


def make_pipeline(config, manifest, pretrained, run):
    from google.protobuf import text_format
    from object_detection.protos import pipeline_pb2, train_pb2
    pipeline = pipeline_pb2.TrainEvalPipelineConfig()
    text_format.Parse((pretrained / 'pipeline.config').read_text(), pipeline)
    pipeline.model.ssd.num_classes = len(manifest['classes'])
    pipeline.model.ssd.freeze_batchnorm = config.get('freeze_batchnorm', True)
    train = pipeline.train_config
    train.batch_size = config['batch_size']
    steps = training_plan(config, manifest)['num_steps']
    train.num_steps = steps
    train.fine_tune_checkpoint = str(pretrained / 'checkpoint/ckpt-0')
    train.fine_tune_checkpoint_type = 'detection'
    train.fine_tune_checkpoint_version = train_pb2.CheckpointVersion.V2
    train.sync_replicas = False
    train.replicas_to_aggregate = 1
    # Replace the pretrained large-batch schedule with a small-dataset schedule.
    train.optimizer.Clear()
    momentum = train.optimizer.momentum_optimizer
    momentum.momentum_optimizer_value = 0.9
    schedule = momentum.learning_rate.cosine_decay_learning_rate
    schedule.learning_rate_base = config['learning_rate']
    schedule.total_steps = steps
    schedule.warmup_steps = min(100, steps // 10)
    schedule.warmup_learning_rate = config['learning_rate'] / 10
    train.optimizer.use_moving_average = False
    if 'augmentation' in config:
        # Replace inherited COCO augmentation explicitly for reproducible experiments.
        del train.data_augmentation_options[:]
        augmentation = config['augmentation']
        if augmentation.get('horizontal_flip', False):
            train.data_augmentation_options.add().random_horizontal_flip.SetInParent()
        if augmentation.get('brightness_delta', 0):
            train.data_augmentation_options.add().random_adjust_brightness.max_delta = augmentation['brightness_delta']
    train.max_number_of_boxes = max(100, max(len(row['boxes']) for row in manifest['splits']['train']))
    label_map = str(run / 'label_map.pbtxt')
    pipeline.train_input_reader.label_map_path = label_map
    del pipeline.train_input_reader.tf_record_input_reader.input_path[:]
    pipeline.train_input_reader.tf_record_input_reader.input_path.append(str(run / 'records/train.tfrecord'))
    pipeline.train_input_reader.num_readers = 1
    for reader in pipeline.eval_input_reader:
        reader.label_map_path = label_map
        reader.shuffle = False
        reader.num_epochs = 1
        reader.num_readers = 1
        del reader.tf_record_input_reader.input_path[:]
        reader.tf_record_input_reader.input_path.append(str(run / 'records/test.tfrecord'))
    pipeline.eval_config.use_moving_averages = False
    pipeline.eval_config.batch_size = 1
    (run / 'pipeline.config').write_text(text_format.MessageToString(pipeline), encoding='utf-8')


def build_records(config, root):
    manifest = load_manifest(config, root)
    run = root / config['run_dir']
    # Store exact inputs so accidentally changed labels/settings cannot resume an old run.
    frozen = {'config': config, 'manifest': manifest, 'model': MODEL_NAME}
    serialized = json.dumps(frozen, sort_keys=True, ensure_ascii=False, indent=2)
    signature = run / 'inputs.json'
    if signature.is_file():
        previous = json.loads(signature.read_text(encoding='utf-8'))
        previous['config'] = training_identity(previous['config'])
        identity = {**frozen, 'config': training_identity(config)}
        if previous != identity:
            raise ValueError('Config/dataset berbeda dari run ini. Ganti run_dir untuk eksperimen baru.')
    if run.exists() and any(run.iterdir()) and not signature.is_file():
        raise ValueError('run_dir sudah berisi file tanpa metadata. Pilih run_dir baru.')
    plan = training_plan(config, manifest)
    run.mkdir(parents=True, exist_ok=True)
    if not signature.exists():
        signature.write_text(serialized, encoding='utf-8')
    (run / 'training-plan.json').write_text(json.dumps(plan, indent=2), encoding='utf-8')
    label_map = ''.join(f'item {{ id: {index} name: {json.dumps(name, ensure_ascii=False)} }}\n'
                        for index, name in enumerate(manifest['classes'], 1))
    (run / 'label_map.pbtxt').write_text(label_map, encoding='utf-8')
    if not all((run / 'records' / f'{split}.tfrecord').is_file() for split in manifest['splits']):
        write_records(manifest, run / 'records', root, config.get('preprocessing'))
    print(f'TFRecord dan label map siap: {run}; {plan["num_steps"]} langkah training.', flush=True)
    return manifest, run, plan


def train(config, root):
    manifest, run, plan = build_records(config, root)
    pretrained = download_pretrained(root)
    make_pipeline(config, manifest, pretrained, run)
    (run / 'training').mkdir(exist_ok=True)
    # Official training entry point resumes from the latest checkpoint in model_dir.
    subprocess.run([sys.executable, '-m', 'object_detection.model_main_tf2',
                    f'--pipeline_config_path={run / "pipeline.config"}',
                    f'--model_dir={run / "training"}', f'--num_train_steps={plan["num_steps"]}',
                    f'--checkpoint_every_n={config.get("checkpoint_every_n", 100)}', '--alsologtostderr'], check=True)


def export(config, root):
    import tensorflow as tf
    run = root / config['run_dir']
    if not (run / 'inputs.json').is_file():
        raise ValueError('Belum ada training untuk run_dir ini.')
    checkpoint = tf.train.latest_checkpoint(str(run / 'training'))
    if not checkpoint:
        raise ValueError('Checkpoint training belum tersedia.')
    output = run / 'exports' / Path(checkpoint).name
    saved = output / 'saved_model/saved_model.pb'
    if not saved.is_file():
        subprocess.run([sys.executable, '-m', 'object_detection.exporter_main_v2',
                        '--input_type=image_tensor', f'--pipeline_config_path={run / "pipeline.config"}',
                        f'--trained_checkpoint_dir={run / "training"}',
                        f'--output_directory={output}'], check=True)
    frozen = json.loads((run / 'inputs.json').read_text(encoding='utf-8'))
    metadata = {'checkpoint': Path(checkpoint).name, 'saved_model': saved.parent.relative_to(root).as_posix(),
                'classes': frozen['manifest']['classes'], 'model': MODEL_NAME,
                'preprocessing': frozen['config'].get('preprocessing', {})}
    (run / 'export.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    print(f'Model diekspor: {saved.parent}', flush=True)


def load_detector(config, root):
    import tensorflow as tf
    run = root / config['run_dir']
    if not (run / 'export.json').is_file():
        raise ValueError('Model belum diekspor. Jalankan export setelah training.')
    metadata = json.loads((run / 'export.json').read_text(encoding='utf-8'))
    frozen = json.loads((run / 'inputs.json').read_text(encoding='utf-8')) if (run / 'inputs.json').is_file() else {'manifest': {'classes': metadata['classes']}}
    model = tf.saved_model.load(str(root / metadata['saved_model']))
    return model.signatures['serving_default'], frozen, metadata


def detect(detector, image, preprocessing=None):
    import numpy as np
    import tensorflow as tf
    image = preprocess_image(image, preprocessing)
    result = detector(tf.convert_to_tensor(np.asarray(image, dtype=np.uint8)[None, ...]))
    count = int(result['num_detections'][0])
    return {key: value[0, :count].numpy() for key, value in result.items() if key != 'num_detections'}


def evaluate(config, root, split='test'):
    split = split or 'test'
    if split != 'test':
        raise ValueError('Evaluasi hanya menggunakan split test.')
    import numpy as np
    from .coco_metrics import compute_coco_metrics
    detector, frozen, metadata = load_detector(config, root)
    manifest = frozen['manifest']
    if 'splits' not in manifest:
        raise ValueError('Evaluasi berlabel dilakukan di laptop training yang memiliki manifest dan dataset asli.')
    if split not in manifest['splits']:
        raise ValueError(f'Split {split} tidak tersedia pada model ini.')
    verify_images(manifest, root)
    categories = [{'id': index, 'name': name} for index, name in enumerate(manifest['classes'], 1)]
    groundtruth = {'info': {}, 'images': [], 'annotations': [], 'categories': categories}
    predictions = []
    for image_id, row in enumerate(manifest['splits'][split], 1):
        with Image.open(root / row['image']) as source:
            result = detect(detector, source.convert('RGB'), metadata.get('preprocessing'))
        scale = np.array([row['height'], row['width'], row['height'], row['width']])
        boxes = np.array([[b['ymin'], b['xmin'], b['ymax'], b['xmax']] for b in row['boxes']], dtype=np.float32).reshape(-1, 4)
        groundtruth['images'].append({'id': image_id, 'file_name': row['image'],
                                     'width': row['width'], 'height': row['height']})
        for coordinates, box in zip(boxes * scale, row['boxes']):
            ymin, xmin, ymax, xmax = map(float, coordinates)
            width, height = xmax - xmin, ymax - ymin
            groundtruth['annotations'].append({
                'id': len(groundtruth['annotations']) + 1, 'image_id': image_id,
                'category_id': box['class_id'], 'bbox': [xmin, ymin, width, height],
                'area': width * height, 'iscrowd': 0,
            })
        for coordinates, class_id, score in zip(result['detection_boxes'] * scale,
                                                 result['detection_classes'], result['detection_scores']):
            ymin, xmin, ymax, xmax = map(float, coordinates)
            predictions.append({'image_id': image_id, 'category_id': int(class_id),
                                'bbox': [xmin, ymin, xmax - xmin, ymax - ymin], 'score': float(score)})
    metrics = compute_coco_metrics(groundtruth, predictions)
    report = {'split': split, 'checkpoint': metadata['checkpoint'],
              'image_count': len(manifest['splits'][split]), 'metrics': metrics,
              'warnings': manifest['warnings']}
    path = root / config['run_dir'] / 'reports' / f'{metadata["checkpoint"]}-{split}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2), flush=True)
    print(f'Laporan: {path}', flush=True)


def predict(config, root, input_path, output_path):
    from .postprocessing import select_detections
    detector, frozen, metadata = load_detector(config, root)
    source = root / input_path
    destination = root / output_path
    paths = [source] if source.is_file() else sorted(p for p in source.rglob('*') if p.suffix.lower() in IMAGE_EXTENSIONS)
    if not paths:
        raise ValueError(f'Tidak ada gambar JPG/PNG di {source}')
    if source.is_dir() and destination.resolve().is_relative_to(source.resolve()):
        raise ValueError('Folder output harus berada di luar folder gambar input.')
    destination.mkdir(parents=True, exist_ok=True)
    classes = frozen['manifest']['classes']
    for path in paths:
        relative = Path(path.name) if source.is_file() else path.relative_to(source)
        # Keep original extension in output name, so a.jpg and a.png never collide.
        target = destination / relative.parent / f'{relative.name}.predicted.jpg'
        target.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(path) as raw:
            image = ImageOps.exif_transpose(raw).convert('RGB')
        result = detect(detector, image, metadata.get('preprocessing'))
        width, height = image.size
        draw = ImageDraw.Draw(image)
        observations = []
        for selected in select_detections(result, config):
            box, score, class_id = (result[key][selected] for key in ('detection_boxes', 'detection_scores', 'detection_classes'))
            index = int(class_id)
            if not 1 <= index <= len(classes):
                continue
            ymin, xmin, ymax, xmax = map(float, box)
            pixels = [max(0, min(width, xmin * width)), max(0, min(height, ymin * height)),
                      max(0, min(width, xmax * width)), max(0, min(height, ymax * height))]
            draw.rectangle(pixels, outline=(40, 200, 80), width=3)
            caption = f'{classes[index - 1]} {score:.2f}'.encode('ascii', 'replace').decode('ascii')
            draw.text((pixels[0] + 3, pixels[1] + 3), caption, fill=(255, 255, 255), stroke_width=1, stroke_fill=(0, 0, 0))
            observations.append({'class_id': index, 'class_name': classes[index - 1], 'confidence': float(score),
                                 'bbox_xyxy_px': pixels,
                                 'dimensions': {'length_m': None, 'width_m': None, 'height_m': None,
                                                'status': 'not_calibrated'}})
        image.save(target, quality=95)
        payload = {'source_image': str(relative), 'image_width': width, 'image_height': height,
                   'model': MODEL_NAME, 'checkpoint': metadata['checkpoint'], 'detections': observations}
        target.with_suffix('.json').write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')
        print(f'{relative}: {len(observations)} deteksi -> {target}', flush=True)
