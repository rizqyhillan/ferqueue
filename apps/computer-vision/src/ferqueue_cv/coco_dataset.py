"""Read pre-split COCO bbox annotations into the shared training manifest."""

import hashlib
import json
import math
from pathlib import Path

from PIL import Image

from .dataset import IMAGE_EXTENSIONS


def annotation_paths(config, root):
    annotations = config.get('coco_annotations')
    if not isinstance(annotations, dict) or set(annotations) != {'train', 'test'}:
        raise ValueError('coco_annotations harus berisi path JSON train dan test saja.')
    paths = {}
    for split, value in annotations.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f'coco_annotations.{split} harus berupa path JSON di dalam repo.')
        path = Path(value)
        if path.is_absolute() or not (root / path).resolve().is_relative_to(root.resolve()):
            raise ValueError(f'coco_annotations.{split} harus berupa path di dalam repo.')
        paths[split] = root / path
    if paths['train'].resolve() == paths['test'].resolve():
        raise ValueError('JSON COCO train dan test harus berbeda.')
    return paths


def _identifier(row, key, context):
    value = row.get(key)
    if type(value) is not int or value < 0:
        raise ValueError(f'{context}: {key} harus berupa ID integer >= 0.')
    return value


def _categories(document, path):
    rows = document.get('categories')
    if not isinstance(rows, list) or not rows:
        raise ValueError(f'{path}: categories harus berupa daftar kelas yang tidak kosong.')
    categories = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f'{path}: category harus berupa object JSON.')
        category_id = _identifier(row, 'id', str(path))
        name = row.get('name')
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f'{path}: nama kategori tidak boleh kosong.')
        if category_id in categories or name.strip() in categories.values():
            raise ValueError(f'{path}: ID/nama kategori duplikat.')
        categories[category_id] = name.strip()
    return categories


def collect_coco_dataset(config, root):
    root = Path(root).resolve()
    image_dir = root / config['dataset_dir']
    if not image_dir.resolve().is_relative_to(root) or not image_dir.is_dir():
        raise ValueError('dataset_dir COCO harus berupa folder gambar di dalam repo.')
    documents, sources = {}, {}
    for split, path in annotation_paths(config, root).items():
        content = path.read_bytes()
        document = json.loads(content.decode('utf-8-sig'))
        if not isinstance(document, dict):
            raise ValueError(f'{path}: dataset COCO harus berupa object JSON.')
        documents[split] = document
        sources[split] = {'path': path.relative_to(root).as_posix(),
                          'sha256': hashlib.sha256(content).hexdigest()}

    categories = _categories(documents['train'], sources['train']['path'])
    if _categories(documents['test'], sources['test']['path']) != categories:
        raise ValueError('Pemetaan ID/nama kategori COCO train dan test berbeda.')
    category_ids = sorted(categories)
    class_ids = {category_id: index for index, category_id in enumerate(category_ids, 1)}
    classes = [categories[category_id] for category_id in category_ids]

    splits, seen_paths, seen_hashes = {}, set(), {}
    for split in ('train', 'test'):
        document = documents[split]
        images, annotations = document.get('images'), document.get('annotations')
        if not isinstance(images, list) or not images or not isinstance(annotations, list):
            raise ValueError(f'COCO {split}: images harus tidak kosong dan annotations harus berupa daftar.')
        by_id = {}
        for image in images:
            if not isinstance(image, dict):
                raise ValueError(f'COCO {split}: image harus berupa object JSON.')
            image_id = _identifier(image, 'id', f'COCO {split} image')
            if image_id in by_id:
                raise ValueError(f'COCO {split}: ID gambar duplikat: {image_id}.')
            name = image.get('file_name')
            if not isinstance(name, str) or not name.strip():
                raise ValueError(f'COCO {split}: file_name gambar tidak valid.')
            relative = Path(name.replace('\\', '/'))
            path = (image_dir / relative).resolve()
            if relative.is_absolute() or '..' in relative.parts or not path.is_relative_to(image_dir.resolve()):
                raise ValueError(f'COCO {split}: file_name harus berada di dataset_dir: {name}.')
            if path.suffix.lower() not in IMAGE_EXTENSIONS or not path.is_file():
                raise ValueError(f'COCO {split}: gambar JPG/PNG tidak ditemukan: {name}.')
            if path in seen_paths:
                raise ValueError(f'Gambar COCO duplikat/tercantum di beberapa split: {name}.')
            width, height = image.get('width'), image.get('height')
            if any(type(value) is not int or value <= 0 for value in (width, height)):
                raise ValueError(f'COCO {split}: width/height gambar harus integer positif: {name}.')
            with Image.open(path) as decoded:
                decoded.load()
                if decoded.size != (width, height):
                    raise ValueError(f'COCO {split}: ukuran gambar berbeda dari JSON: {name}.')
                if decoded.getexif().get(274, 1) != 1:
                    raise ValueError(f'{name}: normalkan rotasi EXIF sebelum labeling.')
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest in seen_hashes:
                raise ValueError(f'Gambar COCO duplikat: {name} dan {seen_hashes[digest]}.')
            seen_paths.add(path)
            seen_hashes[digest] = name
            by_id[image_id] = {'image': path.relative_to(root).as_posix(), 'sha256': digest,
                               'width': width, 'height': height,
                               'group': relative.parts[0] if len(relative.parts) > 1 else relative.stem,
                               'boxes': []}

        annotation_ids = set()
        for annotation in annotations:
            if not isinstance(annotation, dict):
                raise ValueError(f'COCO {split}: annotation harus berupa object JSON.')
            annotation_id = _identifier(annotation, 'id', f'COCO {split} annotation')
            if annotation_id in annotation_ids:
                raise ValueError(f'COCO {split}: ID anotasi duplikat: {annotation_id}.')
            annotation_ids.add(annotation_id)
            image_id = _identifier(annotation, 'image_id', f'COCO {split} annotation {annotation_id}')
            category_id = _identifier(annotation, 'category_id', f'COCO {split} annotation {annotation_id}')
            if image_id not in by_id or category_id not in class_ids:
                raise ValueError(f'COCO {split}: anotasi {annotation_id} merujuk gambar/kategori tidak dikenal.')
            if annotation.get('iscrowd', 0) != 0 or annotation.get('ignore', 0) != 0:
                raise ValueError(f'COCO {split}: anotasi iscrowd/ignore belum didukung: {annotation_id}.')
            bbox = annotation.get('bbox')
            if not isinstance(bbox, list) or len(bbox) != 4 or any(
                    type(value) not in (int, float) or not math.isfinite(value) for value in bbox):
                raise ValueError(f'COCO {split}: bbox harus berisi empat angka finite: {annotation_id}.')
            x, y, width, height = bbox
            row = by_id[image_id]
            if width <= 0 or height <= 0 or min(x, y) < -1e-6 or (
                    x + width > row['width'] + 1e-6 or y + height > row['height'] + 1e-6):
                raise ValueError(f'COCO {split}: bbox tidak valid/melewati batas gambar: {annotation_id}.')
            row['boxes'].append({'class_id': class_ids[category_id],
                                 'xmin': max(0, x / row['width']),
                                 'ymin': max(0, y / row['height']),
                                 'xmax': min(1, (x + width) / row['width']),
                                 'ymax': min(1, (y + height) / row['height'])})
        splits[split] = list(by_id.values())

    source = {'format': 'coco', 'annotations': sources,
              'category_id_to_class_id': {str(key): value for key, value in class_ids.items()}}
    return classes, splits, source
