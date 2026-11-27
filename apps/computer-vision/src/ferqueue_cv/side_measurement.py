"""Estimate side-view vehicle dimensions using perpendicular pinhole camera geometry."""

import math


CAMERA_GEOMETRY_HEADER = 'X-Camera-Geometry'


def parse_camera_geometry(value):
    """Read fixed perpendicular side camera geometry: distance_cm,focal_norm."""
    parts = [float(part) for part in value.split(',')]
    if len(parts) != 2:
        raise ValueError('Parameter geometri kamera harus berisi 2 angka (distance_cm,focal_norm).')
    distance_cm, focal_norm = parts
    if not all(math.isfinite(item) for item in parts):
        raise ValueError('Parameter geometri kamera tidak valid.')
    if not (distance_cm > 0 and focal_norm > 0):
        raise ValueError('Jarak kamera dan focal_norm harus > 0.')
    return distance_cm, focal_norm


def estimate_side_from_geometry(image, geometry, detections):
    """Estimate length and height from a straight-on perpendicular side camera."""
    distance_cm, focal_norm = geometry
    width, height = image.size
    focal_px = focal_norm * width
    cm_per_px = distance_cm / focal_px

    result = {
        'status': 'ready',
        'method': 'pinhole_side',
        'geometry': {
            'distance_cm': round(distance_cm, 2),
            'focal_norm': round(focal_norm, 6),
            'focal_px': round(focal_px, 2),
            'mm_per_px': cm_per_px * 10,
        },
        'measurement': {'status': 'no_vehicle'},
    }
    if len(detections) > 1:
        result['measurement']['status'] = 'multiple_vehicles'
    if len(detections) != 1:
        return result

    detection = detections[0]
    y1, x1, y2, x2 = detection['box']
    if not (0 < y1 < y2 < 1 and 0 < x1 < x2 < 1):
        result['measurement']['status'] = 'vehicle_clipped'
        return result

    length_cm = (x2 - x1) * width * cm_per_px
    height_cm = (y2 - y1) * height * cm_per_px
    if not (length_cm > 0 and height_cm > 0):
        result['measurement']['status'] = 'vehicle_too_small'
        return result

    result['measurement'] = {
        'status': 'estimated',
        'length_cm': round(length_cm, 2),
        'height_cm': round(height_cm, 2),
    }
    return result
