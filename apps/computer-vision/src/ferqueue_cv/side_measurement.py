"""Estimate side-view dimensions from a 50-yen coin in the same image."""

import math


COIN_DIAMETER_MM = 21.0
COIN_REGION_HEADER = 'X-Coin-Region'


def parse_coin_region(value):
    """Read a normalized [ymin, xmin, ymax, xmax] region."""
    y1, x1, y2, x2 = (float(part) for part in value.split(','))
    if not (0 <= y1 < y2 <= 1 and 0 <= x1 < x2 <= 1):
        raise ValueError('Area koin di luar gambar atau kosong.')
    return y1, x1, y2, x2


def find_coin(image, region):
    import cv2
    import numpy as np

    width, height = image.size
    y1, x1, y2, x2 = region
    left, top = int(x1 * width), int(y1 * height)
    right, bottom = math.ceil(x2 * width), math.ceil(y2 * height)
    crop = image.crop((left, top, right, bottom)).convert('L')
    if min(crop.size) < 28:
        return 'coin_region_small', None

    blurred = cv2.GaussianBlur(np.asarray(crop), (5, 5), 0)
    _, mask = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    candidates = []
    for binary in (mask, cv2.bitwise_not(mask)):
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            _, _, w, h = cv2.boundingRect(contour)
            if len(contour) < 5 or min(w, h) < 24:
                continue
            (cx, cy), axes, _ = cv2.fitEllipse(contour)
            minor, major = sorted(axes)
            if not (24 <= minor <= major and minor / major >= .88):
                continue
            margin = major / 2 + 2
            if not (margin <= cx <= crop.width - margin and margin <= cy <= crop.height - margin):
                continue
            if major < .4 * min(crop.size):
                continue
            fill = cv2.contourArea(contour) / (math.pi * minor * major / 4)
            if not .82 <= fill <= 1.12:
                continue
            diameter = (minor + major) / 2
            candidates.append({
                'center': [(top + cy) / height, (left + cx) / width],
                'diameter_px': diameter,
                'mm_per_px': COIN_DIAMETER_MM / diameter,
            })

    if len(candidates) > 1:
        return 'coin_ambiguous', None
    return ('ready', candidates[0]) if candidates else ('coin_not_found', None)


def estimate_side(image, region, detections):
    status, coin = find_coin(image, region)
    if coin is None:
        return {'status': status}

    result = {'status': 'ready', 'coin': coin, 'measurement': {'status': 'no_vehicle'}}
    if len(detections) > 1:
        result['measurement']['status'] = 'multiple_vehicles'
    if len(detections) != 1:
        return result

    width, height = image.size
    y1, x1, y2, x2 = detections[0]['box']
    if not (0 < y1 < y2 < 1 and 0 < x1 < x2 < 1):
        result['measurement']['status'] = 'vehicle_clipped'
        return result

    cy, cx = coin['center']
    radius = coin['diameter_px'] / 2
    if (y1 < cy + radius / height and y2 > cy - radius / height
            and x1 < cx + radius / width and x2 > cx - radius / width):
        result['measurement']['status'] = 'coin_overlaps_vehicle'
        return result

    cm_per_px = coin['mm_per_px'] / 10
    result['measurement'] = {
        'status': 'estimated',
        'length_cm': round((x2 - x1) * width * cm_per_px, 2),
        'height_cm': round((y2 - y1) * height * cm_per_px, 2),
    }
    return result
