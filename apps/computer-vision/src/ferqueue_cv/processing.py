"""Geometry-preserving image processing and bounding-box previews."""

import json
from pathlib import Path

from PIL import Image, ImageDraw


def preprocess_image(image, settings=None):
    """The same transform is used by TFRecord generation and SavedModel callers."""
    settings = settings or {}
    image = image.convert('RGB')
    kernel = settings.get('denoise_kernel', 0)
    clip = settings.get('clahe_clip_limit', 0)
    gamma = settings.get('gamma', 1)
    if not kernel and not clip and gamma == 1:
        return image
    import cv2
    import numpy as np
    pixels = np.asarray(image).copy()
    if kernel:
        pixels = cv2.GaussianBlur(pixels, (kernel, kernel), 0)
    if clip:
        lab = cv2.cvtColor(pixels, cv2.COLOR_RGB2LAB)
        grid = settings.get('clahe_grid_size', 8)
        lab[:, :, 0] = cv2.createCLAHE(clipLimit=clip, tileGridSize=(grid, grid)).apply(lab[:, :, 0])
        pixels = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
    if gamma != 1:
        # Explicit convention: output = 255 * (input / 255) ** gamma.
        table = np.round(255 * (np.arange(256) / 255) ** gamma).astype('uint8')
        pixels = cv2.LUT(pixels, table)
    return Image.fromarray(pixels)


def preview_dataset(config, root, output_path, split='train', limit=12):
    from .training import load_manifest
    manifest = load_manifest(config, root)
    if split not in manifest['splits']:
        raise ValueError(f'Split {split} tidak tersedia.')
    if limit < 0:
        raise ValueError('limit harus >= 0.')
    output = (root / output_path).resolve()
    if not output.is_relative_to(root.resolve()):
        raise ValueError('Output preview harus berada di dalam repo.')
    if output.is_relative_to((root / config['dataset_dir']).resolve()):
        raise ValueError('Output preview harus berada di luar dataset sumber.')
    if output.exists() and any(output.iterdir()):
        raise ValueError('Output preview sudah berisi data; pilih --output baru.')
    rows = manifest['splits'][split]
    rows = rows[:limit] if limit else rows
    reports = []
    output.mkdir(parents=True, exist_ok=True)
    for row in rows:
        relative = Path(row['image'])
        target = output / relative.parent / relative.name
        target.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(root / row['image']) as source:
            raw = source.convert('RGB')
        processed = preprocess_image(raw, config.get('preprocessing'))
        processed.save(str(target) + '.processed.png')
        # Side-by-side allows inspection without labels hiding image details.
        comparison = Image.new('RGB', (raw.width * 2, raw.height))
        comparison.paste(raw, (0, 0))
        comparison.paste(processed, (raw.width, 0))
        comparison.save(str(target) + '.comparison.jpg')
        overlay = processed.copy()
        draw = ImageDraw.Draw(overlay)
        for box in row['boxes']:
            coordinates = [box['xmin'] * raw.width, box['ymin'] * raw.height,
                           box['xmax'] * raw.width, box['ymax'] * raw.height]
            draw.rectangle(coordinates, outline='lime', width=2)
            draw.text(coordinates[:2], str(box['class_id']), fill='lime')
        overlay.save(str(target) + '.boxes.jpg')
        reports.append({'image': row['image']})
    report = {'split': split, 'preprocessing': config.get('preprocessing', {}),
              'images': reports}
    (output / 'report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'{len(rows)} gambar siap diperiksa: {output / "report.json"}')
    return report
