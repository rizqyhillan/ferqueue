"""Stage input and adopt output of Taeyoung96's external YOLO-to-COCO converter.

This module never computes COCO bounding boxes or invokes the external converter.
The user runs its main.py manually between stage-yolo and adopt-coco.
"""

from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil

from .dataset import collect_dataset, split_groups

CONVERTER_URL = 'https://github.com/Taeyoung96/Yolo-to-COCO-format-converter'


def collect_source(config, root):
    if config.get('dataset_format', 'yolo') == 'coco':
        from .coco_dataset import collect_coco_dataset
        classes, splits, _ = collect_coco_dataset(config, root)
    else:
        classes, rows = collect_dataset(root / config['dataset_dir'], root)
        splits = split_groups(rows, config['train_ratio'], config['test_ratio'], config['seed'])
    return classes, splits


def summarize(classes, splits):
    return {split: {'images': len(rows), 'groups': len({row['group'] for row in rows}),
                    'background_images': sum(not row['boxes'] for row in rows),
                    'objects': dict(Counter(classes[box['class_id'] - 1] for row in rows for box in row['boxes']))}
            for split, rows in splits.items()}


def inspect_dataset(config, root):
    classes, splits = collect_source(config, root)
    return {'classes': classes, 'splits': summarize(classes, splits),
            'note': 'Hanya train/test; split mengikuti kelompok/sesi, bukan jumlah gambar persis.'}


def _output_folder(config, root, value):
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()) or path.is_relative_to((root / config['dataset_dir']).resolve()):
        raise ValueError('Output harus berada di dalam repo dan di luar dataset raw.')
    if path.exists() and any(path.iterdir()):
        raise ValueError(f'{path} sudah berisi data; pilih output versi baru. Hasil lama tidak ditimpa.')
    return path


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stage_yolo(config, root, output_path):
    if config.get('dataset_format', 'yolo') != 'yolo':
        raise ValueError('stage-yolo memerlukan konfigurasi sumber YOLO.')
    root = Path(root).resolve()
    output = _output_folder(config, root, output_path)
    classes, splits = collect_source(config, root)
    train_ids = {box['class_id'] for row in splits['train'] for box in row['boxes']}
    if train_ids != set(range(1, len(classes) + 1)):
        raise ValueError('Ada kelas yang tidak terwakili di train. Periksa data/kelompok/seed sebelum staging.')
    raw = root / config['dataset_dir']
    image_dir = raw / 'images' if (raw / 'images').is_dir() else raw
    label_dir = raw / 'labels' if (raw / 'labels').is_dir() else image_dir
    staged = {}
    for split, rows in splits.items():
        directory = output / 'images' / split
        directory.mkdir(parents=True, exist_ok=True)
        staged[split] = []
        image_paths = []
        for index, row in enumerate(rows, 1):
            source = root / row['image']
            label = label_dir / source.relative_to(image_dir).with_suffix('.txt')
            # Upstream keeps only file_path.name; unique names prevent collisions
            # between sessions such as sesi-01/frame.png and sesi-02/frame.png.
            target = directory / f'{split}-{index:06d}{source.suffix.lower()}'
            shutil.copyfile(source, target)
            text = label.read_text(encoding='utf-8-sig')
            # Upstream does not skip blank lines; preserve numeric tokens exactly.
            content = ''.join(' '.join(line.split()) + '\n' for line in text.splitlines() if line.strip())
            target.with_suffix('.txt').write_text(content, encoding='utf-8')
            image_paths.append(target.as_posix())
            staged[split].append({**row, 'label': label.relative_to(root).as_posix(),
                                  'label_sha256': _digest(label),
                                  'staged_image': target.relative_to(output).as_posix(),
                                  'staged_label_sha256': _digest(target.with_suffix('.txt'))})
        (output / f'{split}.txt').write_text('\n'.join(image_paths) + '\n', encoding='utf-8')
    metadata = {'classes': classes, 'splits': staged,
                'source': {key: config[key] for key in ('dataset_dir', 'seed', 'train_ratio', 'test_ratio')},
                'converter_repository': CONVERTER_URL}
    (output / 'classes_for_converter.txt').write_text(
        'classes = ' + json.dumps(classes, ensure_ascii=False, indent=4) + '\n', encoding='utf-8')
    (output / 'staging.json').write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'Input converter siap: {output}. Jalankan main.py repo Taeyoung96 secara manual untuk train dan test.')
    return metadata


def adopt_coco(config, root, staging_path, input_path, output_path):
    """Rebase upstream file names onto raw paths, retaining upstream bbox numbers."""
    # No annotation conversion takes place here: boxes are read from upstream JSON.
    if config.get('dataset_format', 'yolo') != 'yolo':
        raise ValueError('adopt-coco memerlukan config YOLO yang digunakan saat stage-yolo.')
    root = Path(root).resolve()
    staging, source = (root / staging_path).resolve(), (root / input_path).resolve()
    if not staging.is_relative_to(root) or not source.is_relative_to(root):
        raise ValueError('Folder staging dan hasil converter harus berada di dalam repo.')
    output = _output_folder(config, root, output_path)
    metadata = json.loads((staging / 'staging.json').read_text(encoding='utf-8'))
    classes, current_splits = collect_source(config, root)
    expected_source = {key: config[key] for key in ('dataset_dir', 'seed', 'train_ratio', 'test_ratio')}
    if metadata['source'] != expected_source or metadata['classes'] != classes or set(metadata['splits']) != {'train', 'test'}:
        raise ValueError('Sumber/config staging berbeda. Buat staging baru sebelum menjalankan converter.')
    documents, sources = {}, {}
    for split in ('train', 'test'):
        rows = metadata['splits'][split]
        original = [{key: row[key] for key in current_splits[split][0]} for row in rows]
        if original != current_splits[split]:
            raise ValueError('Gambar/label/kelompok berubah setelah staging. Buat staging baru.')
        by_name = {}
        for row in rows:
            image = (staging / row['staged_image']).resolve()
            label = (root / row['label']).resolve()
            if not image.is_relative_to(staging) or not label.is_relative_to(root):
                raise ValueError('Path dalam metadata staging tidak valid.')
            if (_digest(image) != row['sha256'] or _digest(label) != row['label_sha256']
                    or _digest(image.with_suffix('.txt')) != row['staged_label_sha256']):
                raise ValueError('File raw/staging berubah setelah stage-yolo. Buat staging baru dan konversi ulang.')
            if image.name in by_name:
                raise ValueError('Nama gambar staging duplikat.')
            by_name[image.name] = row
        path = source / f'instances_{split}.json'
        document = json.loads(path.read_text(encoding='utf-8-sig'))
        expected_categories = {index: name for index, name in enumerate(classes, 1)}
        categories = document.get('categories', [])
        if len(categories) != len(classes) or {row['id']: row['name'] for row in categories} != expected_categories:
            raise ValueError('Kelas converter berbeda. Salin classes_for_converter.txt ke variabel classes pada main.py lalu konversi ulang.')
        names = [row['file_name'] for row in document['images']]
        if len(names) != len(by_name) or set(names) != set(by_name):
            raise ValueError(f'Hasil converter {split} tidak cocok dengan seluruh gambar staging split itu.')
        source_to_ids = {}
        for image in document['images']:
            row = by_name[image['file_name']]
            source_to_ids[image['id']] = row
            image['file_name'] = (root / row['image']).relative_to(root / config['dataset_dir']).as_posix()
            image['group_id'] = row['group']
        # Catch missing labels/conversion of prediction results before freezing data.
        counts_by_image = {}
        for annotation in document['annotations']:
            counts_by_image.setdefault(annotation['image_id'], Counter())[annotation['category_id']] += 1
        for image_id, row in source_to_ids.items():
            counts = counts_by_image.get(image_id, Counter())
            if counts != Counter(box['class_id'] for box in row['boxes']):
                raise ValueError(f'Jumlah objek/kelas hasil converter berbeda dari label: {row["image"]}.')
        documents[split] = document
        sources[split] = {'path': path.relative_to(root).as_posix(), 'sha256': _digest(path)}
    output.mkdir(parents=True, exist_ok=True)
    # Validate with the exact importer used by training before publishing results.
    from tempfile import TemporaryDirectory
    from .coco_dataset import collect_coco_dataset
    with TemporaryDirectory(dir=output) as temporary:
        checked_paths = {}
        for split, document in documents.items():
            path = Path(temporary) / f'instances_{split}.json'
            path.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding='utf-8')
            checked_paths[split] = path.relative_to(root).as_posix()
        collect_coco_dataset({**config, 'coco_annotations': checked_paths}, root)
        annotations = output / 'annotations'
        annotations.mkdir()
        for split, path in checked_paths.items():
            (root / path).replace(annotations / f'instances_{split}.json')
    report = {'converter_repository': CONVERTER_URL, 'converter_outputs': sources,
              'staging': staging.relative_to(root).as_posix(), 'image_root': config['dataset_dir'],
              'splits': summarize(classes, current_splits), 'classes': classes,
              'bbox_source': 'Upstream JSON unchanged (including integer pixel rounding)',
              'adaptation': 'file_name and group_id only; training reads original raw images'}
    (output / 'conversion.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'Hasil converter siap untuk training: {output / "annotations"}')
    return report
