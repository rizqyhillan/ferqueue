"""Validate YOLO or pre-split COCO data and freeze the training manifest."""

import csv
import hashlib
import json
import math
import random
from collections import Counter
from pathlib import Path

from PIL import Image

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png'}


def read_classes(path):
    names = Path(path).read_text(encoding='utf-8-sig').splitlines()
    names = [name.strip() for name in names]
    if not names or any(not name for name in names) or len(set(names)) != len(names):
        raise ValueError(f'{path}: classes.txt harus berisi nama kelas unik, satu per baris, tanpa baris kosong.')
    return names


def read_boxes(path, num_classes):
    if not path.is_file():
        raise ValueError(f'Label tidak ditemukan: {path}. Untuk background, buat file .txt kosong secara eksplisit.')
    boxes = []
    for line_number, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split()
        try:
            if len(parts) != 5:
                raise ValueError('harus 5 kolom')
            class_id = int(parts[0])
            cx, cy, width, height = map(float, parts[1:])
            if not 0 <= class_id < num_classes:
                raise ValueError('class ID di luar classes.txt')
            if not all(math.isfinite(v) for v in (cx, cy, width, height)):
                raise ValueError('koordinat tidak finite')
            if not (0 < width <= 1 and 0 < height <= 1):
                raise ValueError('lebar/tinggi harus > 0 dan <= 1')
            xmin, ymin = cx - width / 2, cy - height / 2
            xmax, ymax = cx + width / 2, cy + height / 2
            if min(xmin, ymin) < -1e-6 or max(xmax, ymax) > 1 + 1e-6:
                raise ValueError('bounding box melewati batas gambar')
            boxes.append({'class_id': class_id + 1, 'xmin': max(0, xmin),
                          'ymin': max(0, ymin), 'xmax': min(1, xmax), 'ymax': min(1, ymax)})
        except ValueError as error:
            raise ValueError(f'{path}:{line_number}: {error}') from error
    return boxes


def validate_ratios(train_ratio, test_ratio):
    if any(type(value) not in (int, float) or not math.isfinite(value) or not 0 < value < 1
           for value in (train_ratio, test_ratio)) or not math.isclose(train_ratio + test_ratio, 1, rel_tol=0, abs_tol=1e-9):
        raise ValueError('Rasio train dan test harus positif, masing-masing < 1, dan jumlahnya 1.')


def split_groups(items, train_ratio, test_ratio, seed):
    validate_ratios(train_ratio, test_ratio)
    groups = sorted({item['group'] for item in items})
    if len(groups) < 2:
        raise ValueError('Perlu minimal 2 kelompok independen untuk train/test. Jangan pecah satu rekaman video.')
    random.Random(seed).shuffle(groups)
    test_count = max(1, min(len(groups) - 1, round(len(groups) * test_ratio)))
    split_by_group = {group: ('test' if index < test_count else 'train')
                      for index, group in enumerate(groups)}
    return {name: [item for item in items if split_by_group[item['group']] == name]
            for name in ('train', 'test')}


def collect_dataset(dataset_dir, root):
    dataset_dir, root = Path(dataset_dir), Path(root)
    classes = read_classes(dataset_dir / 'classes.txt')
    for class_file in dataset_dir.rglob('classes.txt'):
        if read_classes(class_file) != classes:
            raise ValueError(f'Urutan kelas berbeda di {class_file}. Samakan pemetaan ID label sebelum training.')
    image_dir = dataset_dir / 'images' if (dataset_dir / 'images').is_dir() else dataset_dir
    label_dir = dataset_dir / 'labels' if (dataset_dir / 'labels').is_dir() else image_dir
    group_overrides = {}
    if (dataset_dir / 'groups.csv').is_file():
        with (dataset_dir / 'groups.csv').open(encoding='utf-8-sig', newline='') as handle:
            for row in csv.DictReader(handle):
                key, group = row['image'].replace('\\', '/').strip(), row['group'].strip()
                if not group or key in group_overrides:
                    raise ValueError('groups.csv: nama kelompok kosong atau gambar tercantum lebih dari sekali.')
                group_overrides[key] = group
    images = sorted(p for p in image_dir.rglob('*') if p.suffix.lower() in IMAGE_EXTENSIONS)
    if not images:
        raise ValueError(f'Tidak ada gambar JPG/PNG di {image_dir}')
    items, hashes, used_labels = [], {}, set()
    known_images = {p.relative_to(image_dir).as_posix() for p in images}
    unknown_groups = set(group_overrides) - known_images
    if unknown_groups:
        raise ValueError(f'groups.csv merujuk gambar yang tidak ada: {sorted(unknown_groups)}')
    for path in images:
        relative = path.relative_to(image_dir)
        label = label_dir / relative.with_suffix('.txt')
        if label in used_labels:
            raise ValueError(f'Dua gambar memakai label yang sama: {label}. Gunakan nama gambar unik.')
        used_labels.add(label)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest in hashes:
            raise ValueError(f'Gambar duplikat: {path} dan {hashes[digest]}. Hapus duplikat dari salinan dataset.')
        hashes[digest] = path
        with Image.open(path) as image:
            image.load()
            width, height = image.size
            if image.getexif().get(274, 1) != 1:
                raise ValueError(f'{path}: normalkan rotasi EXIF sebelum labeling; koordinat tidak diubah otomatis.')
        group = group_overrides.get(relative.as_posix(), relative.parts[0] if len(relative.parts) > 1 else relative.stem)
        items.append({'image': path.resolve().relative_to(root.resolve()).as_posix(),
                      'sha256': digest, 'width': width, 'height': height, 'group': group,
                      'boxes': read_boxes(label, len(classes))})
    orphan_labels = {p for p in label_dir.rglob('*.txt') if p.name != 'classes.txt'} - used_labels
    if orphan_labels:
        raise ValueError(f'Label tanpa pasangan gambar: {sorted(map(str, orphan_labels))[:5]}')
    return classes, items


def prepare(config, root):
    output = root / config['prepared_dir']
    if output.exists() and any(output.iterdir()):
        raise ValueError(f'{output} sudah berisi dataset. Ganti prepared_dir untuk versi baru; split lama tidak ditimpa.')
    source = None
    dataset_format = config.get('dataset_format', 'yolo')
    if dataset_format == 'coco':
        from .coco_dataset import collect_coco_dataset
        classes, splits, source = collect_coco_dataset(config, root)
    elif dataset_format == 'yolo':
        classes, items = collect_dataset(root / config['dataset_dir'], root)
        splits = split_groups(items, config['train_ratio'], config['test_ratio'], config['seed'])
    else:
        raise ValueError('dataset_format harus yolo atau coco.')
    train_ids = {box['class_id'] for item in splits['train'] for box in item['boxes']}
    missing = [name for index, name in enumerate(classes, 1) if index not in train_ids]
    if missing:
        raise ValueError(f'Kelas tidak terdapat pada split training: {missing}. Tambah kelompok data atau sesuaikan seed.')
    warnings = []
    for split in ('test',):
        ids = {box['class_id'] for item in splits[split] for box in item['boxes']}
        absent = [name for index, name in enumerate(classes, 1) if index not in ids]
        if absent:
            warnings.append(f'{split}: kelas tidak terwakili: {absent}; evaluasi per kelas belum lengkap.')
    manifest = {'schema_version': 2, 'classes': classes, 'seed': config['seed'],
                'train_ratio': config['train_ratio'], 'test_ratio': config['test_ratio'],
                'splits': splits, 'warnings': warnings}
    if source is not None:
        manifest['source'] = source
    output.mkdir(parents=True, exist_ok=True)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
    summary = {}
    for split, rows in splits.items():
        counts = Counter(classes[box['class_id'] - 1] for row in rows for box in row['boxes'])
        summary[split] = {'images': len(rows), 'groups': len({row['group'] for row in rows}), 'objects': dict(counts)}
    (output / 'summary.json').write_text(json.dumps({'splits': summary, 'warnings': warnings}, indent=2), encoding='utf-8')
    return manifest, summary


def verify_images(manifest, root):
    if set(manifest['splits']) != {'train', 'test'} or any(not rows for rows in manifest['splits'].values()):
        raise ValueError('Manifest harus berisi train dan test saja, keduanya tidak kosong. Jalankan prepare dengan prepared_dir baru dan gunakan run_dir baru.')
    if manifest.get('source', {}).get('format') == 'coco':
        for source in manifest['source']['annotations'].values():
            path = root / source['path']
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != source['sha256']:
                raise ValueError(f'Anotasi COCO berubah/hilang setelah prepare: {path}. Buat prepared_dir dan run_dir baru.')
    for rows in manifest['splits'].values():
        for row in rows:
            path = root / row['image']
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
                raise ValueError(f'Gambar berubah/hilang setelah prepare: {path}. Buat prepared_dir dan run_dir baru.')
