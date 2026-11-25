"""Estimate side-view vehicle dimensions using fixed camera trigonometry geometry."""

import math


CAMERA_GEOMETRY_HEADER = 'X-Camera-Geometry'
DEFAULT_CLASS_WIDTH_CM = {
    'mobil': 2.25,
    'bus': 3.0,
    'truk': 3.0,
}
DEFAULT_FALLBACK_WIDTH_CM = 2.5


def parse_camera_geometry(value):
    """Read fixed camera triangle geometry: d_perp_cm,d_parallel_cm,focal_norm."""
    parts = [float(part) for part in value.split(',')]
    if len(parts) != 3:
        raise ValueError('Parameter geometri kamera harus berisi 3 angka.')
    d_perp_cm, d_parallel_cm, focal_norm = parts
    if not all(math.isfinite(item) for item in parts):
        raise ValueError('Parameter geometri kamera tidak valid.')
    if not (d_perp_cm > 0 and d_parallel_cm >= 0 and focal_norm > 0):
        raise ValueError('Jarak tegak lurus dan focal_norm harus > 0, geser samping >= 0.')
    return d_perp_cm, d_parallel_cm, focal_norm


def estimate_side_from_geometry(image, geometry, detections):
    """Estimate length and height from a level, oblique fixed camera triangle."""
    d_perp_cm, d_parallel_cm, focal_norm = geometry
    width, height = image.size
    distance_cm = math.hypot(d_perp_cm, d_parallel_cm)
    yaw_deg = math.degrees(math.atan2(d_parallel_cm, d_perp_cm))
    cos_yaw = d_perp_cm / distance_cm
    sin_yaw = d_parallel_cm / distance_cm
    focal_px = focal_norm * width
    cm_per_px = distance_cm / focal_px

    result = {
        'status': 'ready',
        'method': 'trigonometry',
        'geometry': {
            'd_perp_cm': round(d_perp_cm, 2),
            'd_parallel_cm': round(d_parallel_cm, 2),
            'distance_cm': round(distance_cm, 2),
            'yaw_deg': round(yaw_deg, 2),
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

    projected_length_cm = (x2 - x1) * width * cm_per_px
    height_cm = (y2 - y1) * height * cm_per_px
    class_key = str(detection.get('class_name', '')).strip().lower()
    assumed_width_cm = DEFAULT_CLASS_WIDTH_CM.get(class_key, DEFAULT_FALLBACK_WIDTH_CM)
    length_cm = (projected_length_cm - assumed_width_cm * sin_yaw) / cos_yaw
    if length_cm <= 0:
        result['measurement']['status'] = 'vehicle_too_small'
        return result

    result['measurement'] = {
        'status': 'estimated',
        'length_cm': round(length_cm, 2),
        'height_cm': round(height_cm, 2),
        'projected_length_cm': round(projected_length_cm, 2),
        'assumed_width_cm': assumed_width_cm,
    }
    return result
