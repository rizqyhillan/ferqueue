"""Shared display confidence/NMS filtering for offline prediction and web frames."""


def select_detections(result, config):
    import numpy as np
    boxes = np.asarray(result['detection_boxes'])
    scores = np.asarray(result['detection_scores'])
    classes = np.asarray(result['detection_classes'])
    candidates = [int(index) for index in np.argsort(-scores, kind='stable')
                  if scores[index] >= config['confidence_threshold'] and np.isfinite(scores[index])
                  and np.isfinite(boxes[index]).all() and np.isfinite(classes[index])
                  and boxes[index][2] > boxes[index][0] and boxes[index][3] > boxes[index][1]]
    keep = []
    while candidates and len(keep) < config.get('max_detections', 10):
        current = candidates.pop(0)
        keep.append(current)
        remaining = []
        a = boxes[current]
        for index in candidates:
            if not config.get('class_agnostic_nms', True) and classes[index] != classes[current]:
                remaining.append(index)
                continue
            b = boxes[index]
            intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
            union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
            if union <= 0 or intersection / union <= config.get('nms_iou_threshold', .45):
                remaining.append(index)
        candidates = remaining
    return keep
