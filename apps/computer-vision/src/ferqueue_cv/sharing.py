"""Share inference-only SavedModels without training data or CUDA environments."""

import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import zipfile


def package_model(config, root, archive):
    metadata = json.loads((root / config['run_dir'] / 'export.json').read_text(encoding='utf-8'))
    model = (root / metadata['saved_model']).resolve()
    if not model.is_relative_to(root.resolve()) or not (model / 'saved_model.pb').is_file():
        raise ValueError('SavedModel tidak tersedia. Jalankan export di laptop training terlebih dahulu.')
    if archive.exists():
        raise ValueError('Arsip output sudah ada. Pilih nama --archive baru.')
    archive.parent.mkdir(parents=True, exist_ok=True)
    public = {key: metadata[key] for key in ('classes', 'model', 'checkpoint')}
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as handle:
        handle.writestr('model.json', json.dumps(public, ensure_ascii=False, indent=2))
        for path in sorted(model.rglob('*')):
            if path.is_file():
                handle.write(path, 'saved_model/' + path.relative_to(model).as_posix())
    print(f'Paket model untuk anggota tim: {archive}')


def import_model(config, root, archive):
    run = root / config['run_dir']
    # An imported model must not replace training artifacts or an existing export.
    if (run / 'inputs.json').exists() or (run / 'export.json').exists():
        raise ValueError('run_dir sudah memiliki model/training. Pilih run_dir baru di konfigurasi untuk impor.')
    with zipfile.ZipFile(archive) as handle:
        names = handle.namelist()
        if len(names) != len(set(names)):
            raise ValueError('Arsip memiliki nama file duplikat.')
        for name in names:
            path = PurePosixPath(name)
            if '\\' in name or path.is_absolute() or '..' in path.parts or ':' in name:
                raise ValueError('Arsip memiliki path tidak valid.')
            if name != 'model.json' and (not path.parts or path.parts[0] != 'saved_model'):
                raise ValueError('Arsip hanya boleh berisi model.json dan saved_model/.')
        if 'saved_model/saved_model.pb' not in names or not any(name.startswith('saved_model/variables/') for name in names):
            raise ValueError('Arsip SavedModel tidak lengkap.')
        metadata = json.loads(handle.read('model.json').decode('utf-8'))
        if not isinstance(metadata['classes'], list) or not metadata['classes'] or any(not isinstance(name, str) or not name for name in metadata['classes']):
            raise ValueError('Daftar kelas model tidak valid.')
        if not re.fullmatch(r'ckpt-\d+', metadata['checkpoint']):
            raise ValueError('Identitas checkpoint tidak valid.')
        if metadata['model'] != 'ssd_mobilenet_v2_fpnlite_320x320_coco17_tpu-8':
            raise ValueError('Arsitektur model tidak sesuai workflow ini.')
        destination = run / 'exports' / ('imported-' + metadata['checkpoint'])
        if destination.exists():
            raise ValueError('Folder impor sudah ada; gunakan run_dir baru.')
        run.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=run.parent) as temporary:
            staging = Path(temporary)
            handle.extractall(staging)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(staging / 'saved_model'), str(destination))
        metadata['saved_model'] = destination.relative_to(root).as_posix()
        (run / 'export.json').write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'Model siap untuk predict: {destination}')
