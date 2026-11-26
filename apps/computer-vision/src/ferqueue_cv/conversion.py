"""Inspect YOLO or COCO dataset sources and summarize train/test splits."""

from collections import Counter

from .dataset import collect_dataset, split_groups


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
