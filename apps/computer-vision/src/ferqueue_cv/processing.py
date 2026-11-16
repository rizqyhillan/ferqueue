"""Geometry-preserving image processing and review-only bbox-guided GrabCut masks."""

import json
import math
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


def grabcut_mask(image, box, settings=None):
    """Return an approximate mask, never silently substitute the bounding box."""
    import cv2
    import numpy as np
    settings = settings or {}
    pixels = np.asarray(image.convert('RGB')).copy()
    height, width = pixels.shape[:2]
    x1 = max(0, math.floor(box['xmin'] * width))
    y1 = max(0, math.floor(box['ymin'] * height))
    x2 = min(width, math.ceil(box['xmax'] * width))
    y2 = min(height, math.ceil(box['ymax'] * height))
    if x2 - x1 < 2 or y2 - y1 < 2:
        return None, 'box_too_small'
    # A one-pixel border supplies definite background even for full-frame boxes.
    padded = cv2.copyMakeBorder(pixels, 1, 1, 1, 1, cv2.BORDER_REPLICATE)
    mask = np.zeros(padded.shape[:2], dtype=np.uint8)
    cv2.setRNGSeed(42)
    try:
        cv2.grabCut(padded, mask, (x1 + 1, y1 + 1, x2 - x1, y2 - y1),
                    np.zeros((1, 65)), np.zeros((1, 65)), settings.get('iterations', 5), cv2.GC_INIT_WITH_RECT)
    except cv2.error:
        return None, 'grabcut_failed'
    foreground = np.isin(mask[1:-1, 1:-1], (cv2.GC_FGD, cv2.GC_PR_FGD)).astype('uint8') * 255
    kernel = settings.get('morphology_kernel', 3)
    if kernel:
        element = np.ones((kernel, kernel), dtype=np.uint8)
        foreground = cv2.morphologyEx(foreground, cv2.MORPH_OPEN, element)
        foreground = cv2.morphologyEx(foreground, cv2.MORPH_CLOSE, element)
    # Morphology must not introduce pixels outside the annotated box.
    bounded = np.zeros_like(foreground)
    bounded[y1:y2, x1:x2] = foreground[y1:y2, x1:x2]
    if not bounded.any():
        return None, 'empty_mask_review_required'
    return Image.fromarray(bounded), 'approximate_review_required'


def preview_dataset(config, root, output_path, split='train', limit=12, segment=False):
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
        objects = []
        for index, box in enumerate(row['boxes'], 1):
            coordinates = [box['xmin'] * raw.width, box['ymin'] * raw.height,
                           box['xmax'] * raw.width, box['ymax'] * raw.height]
            draw.rectangle(coordinates, outline='lime', width=2)
            draw.text(coordinates[:2], str(box['class_id']), fill='lime')
            if segment:
                mask, status = grabcut_mask(processed, box, config.get('segmentation'))
                item = {'object': index, 'class_id': box['class_id'], 'status': status}
                if mask is not None:
                    mask_path = Path(str(target) + f'.object-{index}.mask.png')
                    mask.save(mask_path)
                    cutout = processed.convert('RGBA')
                    cutout.putalpha(mask)
                    cutout.save(str(target) + f'.object-{index}.cutout.png')
                    tint = Image.new('RGB', processed.size, (255, 70, 20))
                    preview = Image.blend(processed, tint, .45)
                    preview = Image.composite(preview, processed, mask)
                    preview.save(str(target) + f'.object-{index}.overlay.jpg')
                    item['mask'] = mask_path.relative_to(root).as_posix()
                objects.append(item)
        overlay.save(str(target) + '.boxes.jpg')
        reports.append({'image': row['image'], 'objects': objects})
    report = {'split': split, 'preprocessing': config.get('preprocessing', {}),
              'segmentation': config.get('segmentation', {}) if segment else None,
              'used_as_training_masks': False, 'images': reports}
    (output / 'report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'{len(rows)} gambar siap diperiksa: {output / "report.json"}')
    return report
