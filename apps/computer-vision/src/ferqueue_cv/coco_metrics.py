"""COCO bbox metrics using the standard pycocotools API, including per-class AP."""

import copy


SUMMARY_NAMES = (
    'Precision/mAP', 'Precision/mAP@.50IOU', 'Precision/mAP@.75IOU',
    'Precision/mAP (small)', 'Precision/mAP (medium)', 'Precision/mAP (large)',
    'Recall/AR@1', 'Recall/AR@10', 'Recall/AR@100',
    'Recall/AR@100 (small)', 'Recall/AR@100 (medium)', 'Recall/AR@100 (large)',
)


def compute_coco_metrics(groundtruth, detections):
    import numpy as np
    from pycocotools.coco import COCO
    from pycocotools.cocoeval import COCOeval

    reference = COCO()
    reference.dataset = copy.deepcopy(groundtruth)
    reference.dataset.setdefault('info', {})
    reference.createIndex()
    if detections:
        predicted = reference.loadRes(copy.deepcopy(detections))
    else:
        # COCO.loadRes accesses the first annotation, so handle an empty list explicitly.
        predicted = COCO()
        predicted.dataset = {'images': copy.deepcopy(reference.dataset['images']),
                             'categories': copy.deepcopy(reference.dataset['categories']), 'annotations': []}
        predicted.createIndex()
    evaluator = COCOeval(reference, predicted, iouType='bbox')
    evaluator.evaluate()
    evaluator.accumulate()
    evaluator.summarize()
    metrics = {'DetectionBoxes_' + name: float(value)
               for name, value in zip(SUMMARY_NAMES, evaluator.stats)}

    # Standard COCO precision has shape [IoU, recall, category, area, maxDets].
    # Values of -1 denote settings with no ground-truth objects; exclude them.
    precision = evaluator.eval['precision']
    area = evaluator.params.areaRngLbl.index('all')
    maximum = list(evaluator.params.maxDets).index(100)
    names = {category['id']: category['name'] for category in reference.dataset['categories']}
    for index, category_id in enumerate(evaluator.params.catIds):
        values = precision[:, :, index, area, maximum]
        valid = values[values > -1]
        score = float(np.mean(valid)) if valid.size else -1.0
        metrics['DetectionBoxes_PerformanceByCategory/mAP/' + names[category_id]] = score
    return metrics
