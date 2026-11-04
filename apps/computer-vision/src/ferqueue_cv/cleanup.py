"""Review all dataset cleanup candidates before moving approved files to quarantine."""

from collections import defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import stat
import uuid

from .dataset import IMAGE_EXTENSIONS, read_boxes, read_classes


def _inside(path, boundary):
    """Reject links/junctions and paths outside the intended directory before moves."""
    path, boundary = Path(path).absolute(), Path(boundary).resolve()
    if not path.resolve().is_relative_to(boundary):
        raise ValueError(f'Path di luar folder yang diizinkan: {path}')
    for part in (path, *path.parents):
        if part.is_symlink() or (part.exists() and
                getattr(part.stat(), 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise ValueError(f'Symlink/junction tidak didukung untuk cleanup: {part}')
        if part == boundary:
            break
    return path


def _digest(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def audit_dataset(config, root):
    if config.get('dataset_format', 'yolo') != 'yolo':
        raise ValueError('clean-dataset hanya mendukung dataset YOLO; dataset COCO tidak diubah.')
    root = Path(root).resolve()
    dataset = _inside(root / config['dataset_dir'], root)
    if not dataset.is_dir() or dataset == root:
        raise ValueError('dataset_dir harus berupa folder dataset di dalam repo, bukan root repo.')
    image_dir = dataset / 'images' if (dataset / 'images').is_dir() else dataset
    label_dir = dataset / 'labels' if (dataset / 'labels').is_dir() else image_dir
    # Inspect directories too: do not silently miss datasets behind linked directories.
    for path in dataset.rglob('*'):
        _inside(path, dataset)
    images = sorted(p for p in image_dir.rglob('*')
                    if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS)
    labels = sorted(p for p in label_dir.rglob('*.txt')
                    if p.is_file() and p.name != 'classes.txt')
    relative = lambda path: path.relative_to(root).as_posix()
    issues, candidates, duplicates, fingerprints = [], {}, [], {}

    def fingerprint(path):
        key = relative(path)
        if key not in fingerprints:
            fingerprints[key] = _digest(path)
        return fingerprints[key]

    def propose(path, reason):
        key = relative(path)
        candidates[key] = {'path': key, 'reason': reason, 'sha256': fingerprint(path)}

    classes = None
    try:
        classes = read_classes(dataset / 'classes.txt')
        for class_file in dataset.rglob('classes.txt'):
            fingerprint(class_file)
            if read_classes(class_file) != classes:
                raise ValueError(f'Urutan kelas berbeda: {relative(class_file)}')
    except (ValueError, OSError) as error:
        classes = None
        issues.append(f'Kelas perlu diperbaiki; deduplikasi pasangan dinonaktifkan: {error}')

    by_label, by_hash = defaultdict(list), defaultdict(list)
    annotations = {}
    for image in images:
        label = label_dir / image.relative_to(image_dir).with_suffix('.txt')
        by_label[label].append(image)
        by_hash[fingerprint(image)].append(image)
        if not label.is_file():
            propose(image, 'gambar tanpa label .txt')
        else:
            fingerprint(label)
            if classes is not None:
                try:
                    boxes = read_boxes(label, len(classes))
                    annotations[image] = sorted(tuple(box[key] for key in
                        ('class_id', 'xmin', 'ymin', 'xmax', 'ymax')) for box in boxes)
                except ValueError as error:
                    issues.append(str(error))

    shared = {image for members in by_label.values() if len(members) > 1 for image in members}
    for label, members in by_label.items():
        if len(members) > 1:
            issues.append(f'Label dipakai beberapa gambar; tinjau manual: {relative(label)} -> '
                          + ', '.join(map(relative, members)))
            for image in members:
                candidates.pop(relative(image), None)

    for label in labels:
        fingerprint(label)
        if label not in by_label:
            propose(label, 'label tanpa pasangan gambar')

    for digest, members in by_hash.items():
        if len(members) < 2:
            continue
        group = {'sha256': digest, 'images': list(map(relative, members)),
                 'keep': [], 'status': ''}
        annotated = [p for p in members if (label_dir / p.relative_to(image_dir).with_suffix('.txt')).is_file()]
        if any(p in shared for p in members):
            group['status'] = 'manual: beberapa gambar memakai satu label'
        elif not annotated:
            group['status'] = 'semua gambar tanpa label masuk karantina'
        elif any(p not in annotations for p in annotated):
            group['status'] = 'manual: kelas/label tidak valid'
        elif any(annotations[p] != annotations[annotated[0]] for p in annotated[1:]):
            group['status'] = 'manual: gambar sama tetapi anotasi berbeda'
        else:
            keep = annotated[0]
            group['keep'] = [relative(keep)]
            group['status'] = 'sisakan pasangan valid pertama menurut urutan path'
            for image in annotated[1:]:
                propose(image, f'duplikat gambar; simpan {relative(keep)}')
                propose(label_dir / image.relative_to(image_dir).with_suffix('.txt'),
                        f'label pasangan gambar duplikat; simpan {relative(keep)}')
        if group['status'].startswith('manual:'):
            group['keep'] = [relative(p) for p in annotated]
            issues.append(group['status'] + ': ' + ', '.join(group['images']))
        duplicates.append(group)

    removed_images = {image.relative_to(image_dir).as_posix() for image in images
                      if relative(image) in candidates}
    groups_update = None
    groups_path = dataset / 'groups.csv'
    if groups_path.is_file():
        fingerprint(groups_path)
        with groups_path.open(encoding='utf-8-sig', newline='') as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or not {'image', 'group'} <= set(reader.fieldnames):
                issues.append('groups.csv tidak memiliki kolom image,group; perbaiki sebelum cleanup.')
            else:
                rows = list(reader)
                if any(None in row or any(value is None for value in row.values()) for row in rows):
                    issues.append('groups.csv memiliki baris tidak lengkap; perbaiki sebelum cleanup.')
                else:
                    remaining = [row for row in rows
                                 if row['image'].replace('\\', '/').strip() not in removed_images]
                    if len(remaining) != len(rows):
                        output = io.StringIO(newline='')
                        writer = csv.DictWriter(output, fieldnames=reader.fieldnames)
                        writer.writeheader()
                        writer.writerows(remaining)
                        groups_update = {'path': relative(groups_path), 'sha256': fingerprint(groups_path),
                                         'removed_rows': len(rows) - len(remaining), 'content': output.getvalue()}

    blocked = []
    if any('groups.csv' in issue and 'sebelum cleanup' in issue for issue in issues):
        blocked.append('Perbaiki format groups.csv sebelum memindahkan file.')
    prepared = _inside(root / config['prepared_dir'], root)
    if prepared.exists() and any(prepared.iterdir()):
        blocked.append('prepared_dir sudah berisi hasil prepare. Gunakan prepared_dir dan run_dir baru sebelum cleanup.')
    return {'dataset_dir': relative(dataset), 'images': len(images), 'labels': len(labels),
            'candidates': sorted(candidates.values(), key=lambda item: item['path']),
            'duplicates': duplicates, 'issues': issues, 'blocked': blocked,
            'groups_update': groups_update, 'fingerprints': fingerprints}


def write_report(plan, root):
    folder = _inside(Path(root) / 'outputs/dataset-cleanup', root)
    folder.mkdir(parents=True, exist_ok=True)
    run = folder / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8])
    run.mkdir()
    (run / 'report.json').write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding='utf-8')
    lines = ['REVIEW PEMBERSIHAN DATASET', f'Dataset: {plan["dataset_dir"]}',
             f'Gambar: {plan["images"]}; label: {plan["labels"]}',
             f'File yang akan dipindahkan ke karantina: {len(plan["candidates"])}',
             'Tidak ada file dataset diubah selama audit.', '', 'RENCANA KARANTINA']
    for item in plan['candidates']:
        lines.append(f'{item["path"]}\n  Alasan: {item["reason"]}')
    lines.extend(['', 'KELOMPOK GAMBAR DENGAN SHA256 SAMA'])
    for group in plan['duplicates']:
        lines.extend([group['status'], '  Simpan: ' + ', '.join(group['keep'])])
        lines.extend('  ' + path for path in group['images'])
    if plan['groups_update']:
        lines.extend(['', f'groups.csv: hapus {plan["groups_update"]["removed_rows"]} baris gambar yang dikarantina.',
                      'Salinan groups.csv asli disimpan di backup sebelum diperbarui.'])
    lines.extend(['', 'PERLU REVIEW MANUAL', *plan['issues'], '', 'PENGHALANG CLEANUP', *plan['blocked']])
    lines.extend(['', 'Label kosong sah untuk background. Label dengan isi sama pada gambar berbeda tetap disimpan.',
                  'Duplikat gambar berdasarkan byte identik (SHA256), bukan sekadar mirip atau nama file sama.',
                  'Ketik y di terminal setelah selesai review untuk menjalankan seluruh rencana karantina.'])
    (run / 'report.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return run


def apply_cleanup(plan, config, root, run):
    """Apply only an unchanged, freshly checked plan; journal each completed move."""
    root = Path(root).resolve()
    run = _inside(run, root / 'outputs/dataset-cleanup')
    if plan['blocked']:
        raise ValueError(' '.join(plan['blocked']))
    # Includes retained copies and label/class/group files, not only deletion targets.
    if audit_dataset(config, root) != plan:
        raise ValueError('Dataset/rencana berubah sejak audit. Jalankan clean-dataset dan review ulang.')
    if (run / 'applied.json').exists():
        raise ValueError('Rencana ini sudah pernah dijalankan.')
    dataset = _inside(root / plan['dataset_dir'], root)
    moves = []
    for item in plan['candidates']:
        source = _inside(root / item['path'], dataset)
        target = _inside(run / 'files' / item['path'], run)
        if target.exists():
            raise ValueError(f'Backup sudah ada: {target}')
        moves.append((source, target))
    groups = plan['groups_update']
    journal = {'status': 'in_progress', 'moved': [], 'groups_backup': None}

    def save_journal():
        (run / 'applied.json').write_text(json.dumps(journal, indent=2), encoding='utf-8')

    save_journal()
    try:
        if groups:
            source = _inside(root / groups['path'], dataset)
            backup = _inside(run / 'original' / groups['path'], run)
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_bytes(source.read_bytes())
            journal['groups_backup'] = backup.relative_to(root).as_posix()
            save_journal()
        # Append progress instead of rewriting a growing JSON list for every file.
        with (run / 'moves.jsonl').open('x', encoding='utf-8') as move_log:
            for source, target in moves:
                target.parent.mkdir(parents=True, exist_ok=True)
                source.rename(target)
                entry = {'source': source.relative_to(root).as_posix(),
                         'backup': target.relative_to(root).as_posix()}
                journal['moved'].append(entry)
                move_log.write(json.dumps(entry) + '\n')
                move_log.flush()
        if groups:
            source = root / groups['path']
            temporary = source.with_name(f'.groups-cleanup-{uuid.uuid4().hex}.tmp')
            temporary.write_bytes(groups['content'].encode('utf-8'))
            temporary.replace(source)
        journal['status'] = 'complete'
    except (OSError, KeyboardInterrupt):
        journal['status'] = 'incomplete; lihat moved untuk file yang sudah dipindahkan'
        raise
    finally:
        save_journal()
    return len(moves)


def clean_dataset(config, root, dry_run=False, confirm=None):
    print(f'Memindai seluruh dataset: {config["dataset_dir"]} ...', flush=True)
    plan = audit_dataset(config, root)
    run = write_report(plan, root)
    print(f'Gambar: {plan["images"]}; label: {plan["labels"]}; kelompok duplikat: {len(plan["duplicates"])}')
    print(f'Rencana karantina: {len(plan["candidates"])} file; catatan manual: {len(plan["issues"])}')
    print(f'Buka laporan lengkap: {run / "report.txt"}')
    print(f'Laporan terstruktur: {run / "report.json"}')
    if plan['blocked']:
        print('Cleanup diblokir: ' + ' '.join(plan['blocked']))
        return run
    if dry_run or not plan['candidates']:
        print('Audit selesai. Tidak ada file dataset diubah.')
        return run
    try:
        answer = (confirm or input)('Review laporan di atas. Pindahkan SEMUA kandidat ke karantina? Ketik y: ')
    except (EOFError, KeyboardInterrupt):
        answer = ''
    if answer.strip() != 'y':
        print('Dibatalkan. Tidak ada file dataset diubah.')
        return run
    count = apply_cleanup(plan, config, root, run)
    print(f'Selesai: {count} file dipindahkan ke {run / "files"}')
    print('Path asal dan backup tercatat di applied.json. Jalankan prepare setelah catatan manual dibereskan.')
    return run
