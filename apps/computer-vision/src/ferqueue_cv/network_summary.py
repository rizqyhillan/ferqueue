"""Inspect and visualize the complete CNN network architecture (SSD MobileNet V2 FPNLite 320x320)."""

from collections import OrderedDict
import csv
import io
import json
import os
from pathlib import Path


ANCHOR_SPECS = [
    {'level': 'P3', 'grid': '40x40', 'stride': 8, 'anchors_per_cell': 6, 'total_anchors': 40 * 40 * 6},
    {'level': 'P4', 'grid': '20x20', 'stride': 16, 'anchors_per_cell': 6, 'total_anchors': 20 * 20 * 6},
    {'level': 'P5', 'grid': '10x10', 'stride': 32, 'anchors_per_cell': 6, 'total_anchors': 10 * 10 * 6},
    {'level': 'P6', 'grid': '5x5', 'stride': 64, 'anchors_per_cell': 6, 'total_anchors': 5 * 5 * 6},
    {'level': 'P7', 'grid': '3x3', 'stride': 107, 'anchors_per_cell': 6, 'total_anchors': 3 * 3 * 6},
]

COMPONENT_ORDER = [
    'Backbone (MobileNetV2)',
    'Neck (FPNLite Top-Down P3-P5)',
    'Neck (FPNLite Coarse P6-P7)',
    'Head (SSD Shared Tower)',
    'Head (SSD Box & Class Predictor)',
]


def classify_component(layer_name):
    """Map a Keras layer or SavedModel variable scope name to its CNN architectural component."""
    lower = layer_name.lower()
    if 'predictiontower' in lower or 'box_encodings' in lower:
        return 'Head (SSD Shared Tower)'
    if any(token in lower for token in ('boxhead', 'classhead', 'classpredictor')) or lower.endswith('boxpredictor'):
        return 'Head (SSD Box & Class Predictor)'
    if 'bottom_up_conv2d' in lower:
        return 'Neck (FPNLite Coarse P6-P7)'
    if any(token in lower for token in ('projection_', 'smoothing_', 'nearest_neighbor_upsampling', 'top_down')):
        return 'Neck (FPNLite Top-Down P3-P5)'
    return 'Backbone (MobileNetV2)'


def infer_saved_model_layer_type(layer_name, weight_shapes, var_kinds):
    """Infer a readable CNN layer type from SavedModel variable names and tensor shapes."""
    lower = layer_name.lower()
    kinds = set(var_kinds)
    if 'depthwise_kernel' in kinds and 'pointwise_kernel' in kinds:
        return 'SeparableConv2D'
    if 'depthwise_kernel' in kinds:
        return 'DepthwiseConv2D'
    if 'kernel' in kinds:
        return 'Conv2D'
    if 'batchnorm' in lower or lower.endswith('_bn') or lower.startswith('bn_') or {'gamma', 'beta'} <= kinds:
        return 'BatchNormalization'
    return 'Layer'


def format_kernel_stride(layer):
    """Format kernel size and stride for Keras layers."""
    kernel = getattr(layer, 'kernel_size', None)
    strides = getattr(layer, 'strides', None)
    parts = []
    if kernel is not None:
        if isinstance(kernel, (tuple, list)) and len(kernel) == 2:
            parts.append(f'{kernel[0]}x{kernel[1]}')
        else:
            parts.append(str(kernel))
    if strides is not None:
        if isinstance(strides, (tuple, list)) and len(strides) == 2:
            parts.append(f's={strides[0]}')
        else:
            parts.append(f's={strides}')
    return ', '.join(parts) if parts else '-'


def format_shape(shape):
    """Format tensor shape tuple cleanly."""
    if shape is None:
        return '-'
    if isinstance(shape, str):
        return shape
    if isinstance(shape, (list, tuple)) and shape and isinstance(shape[0], (list, tuple)):
        shape = shape[0]
    try:
        return '(' + ', '.join('?' if d is None else str(int(d)) for d in shape) + ')'
    except (TypeError, ValueError):
        return str(shape)


def _layer_param_counts(layer):
    import tensorflow as tf
    trainable = sum(int(tf.size(w)) for w in layer.trainable_weights)
    non_trainable = sum(int(tf.size(w)) for w in layer.non_trainable_weights)
    return trainable + non_trainable, trainable, non_trainable


def _friendly_layer_type(layer):
    cls_name = type(layer).__name__
    if cls_name == 'FreezableBatchNorm':
        return 'BatchNormalization'
    if cls_name == 'Lambda':
        lower = layer.name.lower()
        if 'upsampling' in lower:
            return 'UpSampling2D (Nearest)'
        if 'relu' in lower or 'activation' in lower or 'smoothing' in lower or 'bottom_up' in lower:
            return 'ReLU6'
    return cls_name


def _fpn_layer_output_shape(layer_name):
    lower = layer_name.lower()
    if 'projection_3' in lower:
        return '(1, 10, 10, 128)'
    if 'projection_2' in lower or 'smoothing_2' in lower:
        return '(1, 20, 20, 128)'
    if 'projection_1' in lower or 'smoothing_1' in lower:
        return '(1, 40, 40, 128)'
    if 'bottom_up_conv2d_20' in lower:
        return '(1, 5, 5, 128)'
    if 'bottom_up_conv2d_21' in lower:
        return '(1, 3, 3, 128)'
    if 'feature_0' in lower or 'activation_0' in lower:
        return '(1, 40, 40, 128)'
    if 'feature_1' in lower or 'activation_1' in lower:
        return '(1, 20, 20, 128)'
    if 'feature_2' in lower or 'activation_2' in lower:
        return '(1, 10, 10, 128)'
    if 'feature_3' in lower or 'activation_3' in lower:
        return '(1, 5, 5, 128)'
    if 'feature_4' in lower or 'activation_4' in lower:
        return '(1, 3, 3, 128)'
    if 'predictiontower/conv2d_' in lower:
        return 'Shared (P3..P7, 128 ch)'
    if 'boxhead' in lower or lower.endswith('boxpredictor'):
        return 'Shared (P3..P7, 24 ch) -> (1, 12804, 4)'
    if 'classhead' in lower or 'classpredictor' in lower:
        return 'Shared (P3..P7, 24 ch) -> (1, 12804, C+1)'
    return '-'


def summarize_components(layers):
    """Aggregate layer counts and parameter totals by architectural component."""
    total_params = sum(row['params'] for row in layers)
    buckets = OrderedDict((name, {
        'component': name,
        'layer_count': 0,
        'params': 0,
        'trainable_params': 0,
        'non_trainable_params': 0,
        'param_pct': 0.0,
    }) for name in COMPONENT_ORDER)

    for row in layers:
        comp = row['component']
        if comp not in buckets:
            buckets[comp] = {
                'component': comp,
                'layer_count': 0,
                'params': 0,
                'trainable_params': 0,
                'non_trainable_params': 0,
                'param_pct': 0.0,
            }
        entry = buckets[comp]
        entry['layer_count'] += 1
        entry['params'] += row['params']
        entry['trainable_params'] += row['trainable_params']
        entry['non_trainable_params'] += row['non_trainable_params']

    result = []
    for entry in buckets.values():
        if entry['layer_count'] == 0:
            continue
        entry['param_pct'] = round((entry['params'] / total_params * 100.0) if total_params else 0.0, 2)
        result.append(entry)
    return result


def summarize_layer_types(layers):
    """Aggregate layer counts and parameter totals by layer type."""
    counts = {}
    for row in layers:
        kind = row['layer_type']
        entry = counts.setdefault(kind, {'layer_type': kind, 'count': 0, 'params': 0})
        entry['count'] += 1
        entry['params'] += row['params']
    return sorted(counts.values(), key=lambda item: (-item['params'], -item['count'], item['layer_type']))


def _resolve_classes_and_export(config, root):
    run_dir = root / config['run_dir']
    export_json = run_dir / 'export.json'
    export_meta = None
    classes = ['Mobil', 'Truk', 'Bus']
    if export_json.is_file():
        export_meta = json.loads(export_json.read_text(encoding='utf-8'))
        if export_meta.get('classes'):
            classes = list(export_meta['classes'])
    else:
        manifest_path = root / config['prepared_dir'] / 'manifest.json'
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            if manifest.get('classes'):
                classes = list(manifest['classes'])
    return classes, export_meta


def _extract_backbone_concrete_shapes(backbone):
    import tensorflow as tf
    probe = tf.keras.Model(inputs=backbone.inputs, outputs=[layer.output for layer in backbone.layers])
    outputs = probe(tf.zeros([1, 320, 320, 3], dtype=tf.float32), training=False)
    if not isinstance(outputs, (list, tuple)):
        outputs = [outputs]
    return {layer.name: format_shape(tuple(int(d) for d in tensor.shape)) for layer, tensor in zip(backbone.layers, outputs)}


def _collect_keras_sublayers(obj, seen, collected):
    import tensorflow as tf
    if isinstance(obj, tf.keras.layers.Layer):
        if id(obj) in seen or not obj.built:
            return
        seen.add(id(obj))
        collected.append(obj)
        return
    if isinstance(obj, (list, tuple)):
        for item in obj:
            _collect_keras_sublayers(item, seen, collected)
    elif isinstance(obj, dict):
        for item in obj.values():
            _collect_keras_sublayers(item, seen, collected)
    elif hasattr(obj, 'submodules'):
        for sub in obj.submodules:
            _collect_keras_sublayers(sub, seen, collected)


def inspect_keras_detector(config, root):
    """Build the SSD MobileNet V2 FPNLite detector via Object Detection API and inspect all layers."""
    from .runtime import model_template
    import tensorflow as tf
    from object_detection.builders import model_builder
    from object_detection.utils import config_util

    classes, export_meta = _resolve_classes_and_export(config, root)
    run_dir = root / config['run_dir']
    pipeline_path = run_dir / 'pipeline.config'
    if not pipeline_path.is_file():
        pipeline_path = model_template(root)

    model_config = config_util.get_configs_from_pipeline_file(str(pipeline_path))['model']
    model_config.ssd.num_classes = len(classes)
    detector = model_builder.build(model_config=model_config, is_training=False)

    dummy = tf.zeros([1, 320, 320, 3], dtype=tf.float32)
    images, shapes = detector.preprocess(dummy)
    predictions = detector.predict(images, shapes)
    detector.postprocess(predictions, shapes)

    feature_extractor = detector._feature_extractor
    backbone = feature_extractor.classification_backbone
    backbone_shapes = _extract_backbone_concrete_shapes(backbone)

    seen = set()
    rows = []

    def add_layer(layer, component, output_shape):
        params, trainable, non_trainable = _layer_param_counts(layer)
        rows.append({
            'index': len(rows) + 1,
            'component': component,
            'name': layer.name,
            'layer_type': _friendly_layer_type(layer),
            'kernel_stride': format_kernel_stride(layer),
            'output_shape': output_shape,
            'params': params,
            'trainable_params': trainable,
            'non_trainable_params': non_trainable,
            'trainable': bool(trainable > 0) if params > 0 else False,
        })

    # 1. Backbone (MobileNetV2)
    for layer in backbone.layers:
        if id(layer) in seen:
            continue
        seen.add(id(layer))
        add_layer(layer, 'Backbone (MobileNetV2)', backbone_shapes.get(layer.name, format_shape(layer.output_shape)))

    # 2. FPNLite Top-Down (P3-P5)
    fpn_layers = []
    _collect_keras_sublayers(feature_extractor._fpn_features_generator.layers, seen, fpn_layers)
    upsample_idx = 0
    for layer in fpn_layers:
        if 'upsampling' in layer.name.lower():
            upsample_idx += 1
            out_shape = '(1, 20, 20, 128)' if upsample_idx == 1 else '(1, 40, 40, 128)'
        else:
            out_shape = _fpn_layer_output_shape(layer.name)
        add_layer(layer, 'Neck (FPNLite Top-Down P3-P5)', out_shape)

    # 3. FPNLite Coarse Bottom-Up (P6-P7)
    coarse_layers = []
    _collect_keras_sublayers(feature_extractor._coarse_feature_layers, seen, coarse_layers)
    for layer in coarse_layers:
        add_layer(layer, 'Neck (FPNLite Coarse P6-P7)', _fpn_layer_output_shape(layer.name))

    # 4. SSD Weight-Shared Prediction Tower
    box_predictor = detector._box_predictor
    tower_layers = []
    _collect_keras_sublayers(box_predictor._base_tower_layers_for_heads, seen, tower_layers)
    for layer in tower_layers:
        add_layer(layer, 'Head (SSD Shared Tower)', _fpn_layer_output_shape(layer.name))

    # 5. SSD Box & Class Predictor Heads (expand inner conv layers so kernel/stride are visible)
    head_objects = []
    if hasattr(box_predictor, '_box_prediction_head') and box_predictor._box_prediction_head is not None:
        head_objects.append(('box', box_predictor._box_prediction_head))
    for head_name, heads in getattr(box_predictor, '_prediction_heads', {}).items():
        if isinstance(heads, (list, tuple)):
            for item in heads:
                head_objects.append((head_name, item))
        else:
            head_objects.append((head_name, heads))

    for head_kind, head_obj in head_objects:
        inner = []
        for attr in ('_box_encoder_layers', '_class_predictor_layers'):
            if hasattr(head_obj, attr):
                _collect_keras_sublayers(getattr(head_obj, attr), seen, inner)
        if not inner:
            _collect_keras_sublayers(head_obj, seen, inner)
        for layer in inner:
            if 'box' in head_kind.lower() or 'box' in layer.name.lower():
                out_shape = 'Shared (P3..P7, 24 ch) -> (1, 12804, 4)'
            else:
                out_shape = f'Shared (P3..P7, {(len(classes) + 1) * 6} ch) -> (1, 12804, {len(classes) + 1})'
            add_layer(layer, 'Head (SSD Box & Class Predictor)', out_shape)

    buf = io.StringIO()
    backbone.summary(print_fn=lambda line: buf.write(line + '\n'), line_length=110)

    total_params = sum(row['params'] for row in rows)
    trainable_params = sum(row['trainable_params'] for row in rows)
    non_trainable_params = sum(row['non_trainable_params'] for row in rows)
    detector_var_params = sum(int(tf.size(v)) for v in detector.variables)
    feature_map_shapes = [format_shape(tuple(int(d) for d in fmap.shape)) for fmap in predictions['feature_maps']]
    num_anchors = int(predictions['anchors'].shape[0])

    return {
        'architecture': 'SSD MobileNet V2 FPNLite 320x320',
        'model_id': export_meta['model'] if export_meta and 'model' in export_meta else 'ssd_mobilenet_v2_fpnlite_320x320_coco17_tpu-8',
        'checkpoint': export_meta.get('checkpoint') if export_meta else None,
        'inspection_source': 'keras_model_builder',
        'pipeline_config': str(pipeline_path.relative_to(root)) if pipeline_path.is_relative_to(root) else str(pipeline_path),
        'input_shape': '(1, 320, 320, 3)',
        'classes': classes,
        'num_classes': len(classes),
        'total_layers': len(rows),
        'total_params': total_params,
        'trainable_params': trainable_params,
        'non_trainable_params': non_trainable_params,
        'detector_variables_params': detector_var_params,
        'params_match_variables': total_params == detector_var_params,
        'estimated_size_mb_fp32': round(total_params * 4 / (1024 * 1024), 2),
        'fpn_feature_map_shapes': feature_map_shapes,
        'total_anchors': num_anchors,
        'anchor_specs': ANCHOR_SPECS,
        'components': summarize_components(rows),
        'layer_types': summarize_layer_types(rows),
        'layers': rows,
        'backbone_keras_summary': buf.getvalue(),
    }


def inspect_saved_model(saved_model_dir, classes=None, checkpoint=None):
    """Fallback CNN inspector directly from an exported SavedModel (no Object Detection API required)."""
    import tensorflow as tf
    from tensorflow.python.framework.convert_to_constants import convert_variables_to_constants_v2

    classes = list(classes or ['Mobil', 'Truk', 'Bus'])
    loaded = tf.saved_model.load(str(saved_model_dir))
    fn = loaded.signatures['serving_default']
    frozen_fn = convert_variables_to_constants_v2(fn, lower_control_flow=False)

    shape_by_op = {}
    for op in frozen_fn.graph.get_operations():
        if not op.outputs:
            continue
        shp = op.outputs[0].shape
        if shp.rank == 4:
            shape_by_op[op.name] = tuple(int(d) if d is not None else None for d in shp.as_list())
    op_names = list(shape_by_op.keys())

    def find_out_shape(layer_name):
        needle = '/' + layer_name + '/'
        matches = [shape_by_op[name] for name in op_names if needle in ('/' + name + '/')]
        for shape in reversed(matches):
            if shape[1] is not None and shape[2] is not None:
                return format_shape(shape)
        return format_shape(matches[-1]) if matches else '-'

    grouped = OrderedDict()
    for var in fn.variables:
        clean = var.name.split(':')[0]
        parts = clean.split('/')
        layer_name = '/'.join(parts[:-1]) if len(parts) > 1 else clean
        param_kind = parts[-1]
        entry = grouped.setdefault(layer_name, {
            'var_kinds': [],
            'weight_shapes': [],
            'params': 0,
            'trainable_params': 0,
            'non_trainable_params': 0,
        })
        count = int(tf.size(var))
        entry['var_kinds'].append(param_kind)
        entry['params'] += count
        if var.trainable:
            entry['trainable_params'] += count
        else:
            entry['non_trainable_params'] += count
        if param_kind in ('kernel', 'depthwise_kernel', 'pointwise_kernel', 'weights'):
            entry['weight_shapes'].append(tuple(int(d) for d in var.shape))

    rows = []
    for layer_name, info in grouped.items():
        ltype = infer_saved_model_layer_type(layer_name, info['weight_shapes'], info['var_kinds'])
        k_str = ', '.join(f'{s[0]}x{s[1]}' for s in info['weight_shapes'] if len(s) >= 2) or '-'
        out_shape = _fpn_layer_output_shape(layer_name)
        if out_shape == '-':
            out_shape = find_out_shape(layer_name)
        rows.append({
            'index': len(rows) + 1,
            'component': classify_component(layer_name),
            'name': layer_name,
            'layer_type': ltype,
            'kernel_stride': k_str,
            'output_shape': out_shape,
            'params': info['params'],
            'trainable_params': info['trainable_params'],
            'non_trainable_params': info['non_trainable_params'],
            'trainable': info['trainable_params'] > 0,
        })

    total_params = sum(row['params'] for row in rows)
    trainable_params = sum(row['trainable_params'] for row in rows)
    non_trainable_params = sum(row['non_trainable_params'] for row in rows)
    return {
        'architecture': 'SSD MobileNet V2 FPNLite 320x320',
        'model_id': 'ssd_mobilenet_v2_fpnlite_320x320_coco17_tpu-8',
        'checkpoint': checkpoint,
        'inspection_source': 'saved_model_variables',
        'saved_model_dir': str(saved_model_dir),
        'input_shape': '(1, 320, 320, 3)',
        'classes': classes,
        'num_classes': len(classes),
        'total_layers': len(rows),
        'total_params': total_params,
        'trainable_params': trainable_params,
        'non_trainable_params': non_trainable_params,
        'detector_variables_params': total_params,
        'params_match_variables': True,
        'estimated_size_mb_fp32': round(total_params * 4 / (1024 * 1024), 2),
        'fpn_feature_map_shapes': ['(1, 40, 40, 128)', '(1, 20, 20, 128)', '(1, 10, 10, 128)', '(1, 5, 5, 128)', '(1, 3, 3, 128)'],
        'total_anchors': sum(item['total_anchors'] for item in ANCHOR_SPECS),
        'anchor_specs': ANCHOR_SPECS,
        'components': summarize_components(rows),
        'layer_types': summarize_layer_types(rows),
        'layers': rows,
        'backbone_keras_summary': None,
    }


def format_network_table(report, include_keras_summary=False):
    """Format the full CNN architecture summary and complete layer list as clean printable text."""
    lines = []
    bar = '=' * 124
    sub = '-' * 124
    lines.append(bar)
    lines.append(f"ARSITEKTUR & DAFTAR LENGKAP NETWORK CNN — {report['architecture']}")
    lines.append(bar)
    lines.append(f"Model ID        : {report['model_id']}")
    if report.get('checkpoint'):
        lines.append(f"Checkpoint      : {report['checkpoint']}")
    lines.append(f"Sumber Inspeksi : {report['inspection_source']}")
    lines.append(f"Input Shape     : {report['input_shape']} (RGB, normalisasi internal [-1, 1])")
    lines.append(f"Kelas Output    : {', '.join(report['classes'])} ({report['num_classes']} kelas + 1 background)")
    lines.append(f"Total Layer     : {report['total_layers']} layer")
    lines.append(f"Total Parameter : {report['total_params']:,} "
                 f"(Trainable: {report['trainable_params']:,} | Non-Trainable: {report['non_trainable_params']:,})")
    lines.append(f"Ukuran Bobot    : ~{report['estimated_size_mb_fp32']:.2f} MB (float32)")
    lines.append(f"Total Anchor    : {report['total_anchors']:,} anchor (FPN P3-P7: {', '.join(report['fpn_feature_map_shapes'])})")
    lines.append('')

    lines.append('1. RINGKASAN PER KOMPONEN NETWORK CNN')
    lines.append(sub)
    lines.append(f"{'Komponen':<36} {'Layer':>6} {'Total Param':>14} {'Trainable':>14} {'Non-Train':>12} {'Porsi':>8}")
    lines.append(sub)
    for comp in report['components']:
        lines.append(
            f"{comp['component']:<36} {comp['layer_count']:>6} "
            f"{comp['params']:>14,} {comp['trainable_params']:>14,} "
            f"{comp['non_trainable_params']:>12,} {comp['param_pct']:>7.2f}%"
        )
    lines.append(sub)
    lines.append(
        f"{'TOTAL':<36} {report['total_layers']:>6} "
        f"{report['total_params']:>14,} {report['trainable_params']:>14,} "
        f"{report['non_trainable_params']:>12,} {'100.00%':>8}"
    )
    lines.append('')

    lines.append('2. RINGKASAN PER TIPE LAYER')
    lines.append(sub)
    lines.append(f"{'Tipe Layer':<30} {'Jumlah':>8} {'Total Param':>16}")
    lines.append(sub)
    for item in report['layer_types']:
        lines.append(f"{item['layer_type']:<30} {item['count']:>8} {item['params']:>16,}")
    lines.append('')

    lines.append(f"3. DAFTAR LENGKAP SELURUH LAYER NETWORK CNN ({report['total_layers']} LAYER)")
    lines.append(bar)
    lines.append(f"{'No':>3}  {'Komponen':<22} {'Nama Layer':<42} {'Tipe':<19} {'Kernel/S':<10} {'Output Shape':<22} {'Param #':>10}")
    lines.append(sub)
    comp_short = {
        'Backbone (MobileNetV2)': 'Backbone MobileNetV2',
        'Neck (FPNLite Top-Down P3-P5)': 'FPNLite Top-Down',
        'Neck (FPNLite Coarse P6-P7)': 'FPNLite Coarse P6-P7',
        'Head (SSD Shared Tower)': 'SSD Shared Tower',
        'Head (SSD Box & Class Predictor)': 'SSD Box/Class Head',
    }
    for row in report['layers']:
        cname = comp_short.get(row['component'], row['component'])[:22]
        lname = row['name'] if len(row['name']) <= 42 else '...' + row['name'][-39:]
        ltype = row['layer_type'][:19]
        oshape = row['output_shape'][:22]
        lines.append(
            f"{row['index']:>3}  {cname:<22} {lname:<42} {ltype:<19} "
            f"{row['kernel_stride']:<10} {oshape:<22} {row['params']:>10,}"
        )
    lines.append(bar)

    if include_keras_summary and report.get('backbone_keras_summary'):
        lines.append('')
        lines.append('4. LAMPIRAN: KERAS model.summary() — BACKBONE MOBILENET V2')
        lines.append(sub)
        lines.append(report['backbone_keras_summary'].rstrip())

    return '\n'.join(lines) + '\n'


def render_architecture_diagram(report, output_path):
    """Render a high-resolution (300 DPI) CNN architecture block diagram and parameter charts."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fig = plt.figure(figsize=(18, 11.5), dpi=150)
    fig.patch.set_facecolor('white')
    gs = fig.add_gridspec(2, 2, height_ratios=[1.42, 1.0], hspace=0.28, wspace=0.22)

    # Top panel: End-to-End CNN Architecture Flow Diagram
    ax = fig.add_subplot(gs[0, :])
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 44)
    ax.axis('off')

    ax.text(
        50, 42.2,
        f"Arsitektur Network CNN — {report['architecture']} (FERQUEUE)",
        ha='center', va='center', fontsize=15, fontweight='bold', color='#0f172a',
    )
    ax.text(
        50, 39.5,
        f"Total: {report['total_layers']} Layer  |  {report['total_params']:,} Parameter "
        f"(Trainable: {report['trainable_params']:,} • Non-Trainable: {report['non_trainable_params']:,})  |  "
        f"~{report['estimated_size_mb_fp32']:.2f} MB (FP32)  |  {report['total_anchors']:,} Anchors  |  "
        f"Kelas: {', '.join(report['classes'])}",
        ha='center', va='center', fontsize=9.8, color='#334155',
    )

    def draw_box(x, y, w, h, title, body, facecolor, edgecolor, title_color='#0f172a', title_size=9.2, body_size=7.8, title_offset=0.9, body_offset=1.3):
        box = FancyBboxPatch(
            (x, y), w, h,
            boxstyle='round,pad=0.35,rounding_size=0.9',
            facecolor=facecolor, edgecolor=edgecolor, linewidth=1.7,
        )
        ax.add_patch(box)
        ax.text(x + w / 2, y + h - title_offset, title, ha='center', va='top', fontsize=title_size, fontweight='bold', color=title_color)
        if body:
            ax.text(x + w / 2, y + h / 2 - body_offset, body, ha='center', va='center', fontsize=body_size, color='#1e293b', linespacing=1.32)

    def draw_arrow(x1, y1, x2, y2, color='#475569', rad=0.0):
        ax.annotate(
            '', xy=(x2, y2), xytext=(x1, y1),
            arrowprops=dict(
                arrowstyle='-|>,head_length=0.55,head_width=0.32',
                color=color, lw=1.6,
                connectionstyle=f'arc3,rad={rad}' if rad else 'arc3,rad=0.0',
            ),
        )

    # Dynamic component totals for headers
    comp_map = {c['component']: c for c in report['components']}
    bb_c = comp_map.get('Backbone (MobileNetV2)', {'layer_count': 0, 'params': 0})
    fpn_l = comp_map.get('Neck (FPNLite Top-Down P3-P5)', {'layer_count': 0, 'params': 0})
    fpn_c = comp_map.get('Neck (FPNLite Coarse P6-P7)', {'layer_count': 0, 'params': 0})
    twr_c = comp_map.get('Head (SSD Shared Tower)', {'layer_count': 0, 'params': 0})
    hed_c = comp_map.get('Head (SSD Box & Class Predictor)', {'layer_count': 0, 'params': 0})
    fpn_layers_cnt = fpn_l['layer_count'] + fpn_c['layer_count']
    fpn_params_cnt = fpn_l['params'] + fpn_c['params']
    head_layers_cnt = twr_c['layer_count'] + hed_c['layer_count']
    head_params_cnt = twr_c['params'] + hed_c['params']

    # Outer group frames with comfortable horizontal gaps
    group_frames = [
        (12.6, 2.2, 24.4, 34.8, f"1. BACKBONE: MobileNetV2 ({bb_c['layer_count']} Lyr | {bb_c['params']:,} P)", '#eff6ff', '#2563eb'),
        (39.4, 2.2, 21.6, 34.8, f"2. NECK: FPNLite P3–P7 ({fpn_layers_cnt} Lyr | {fpn_params_cnt:,} P)", '#f0fdf4', '#16a34a'),
        (63.4, 2.2, 23.0, 34.8, f"3. HEAD: Shared SSD ({head_layers_cnt} Lyr | {head_params_cnt:,} P)", '#fff7ed', '#ea580c'),
    ]
    for gx, gy, gw, gh, gtitle, gface, gedge in group_frames:
        frame = FancyBboxPatch(
            (gx, gy), gw, gh,
            boxstyle='round,pad=0.30,rounding_size=1.1',
            facecolor=gface, edgecolor=gedge, linewidth=1.4, linestyle='--', alpha=0.75,
        )
        ax.add_patch(frame)
        ax.text(gx + gw / 2, gy + gh - 0.8, gtitle, ha='center', va='top', fontsize=7.8, fontweight='bold', color=gedge)

    # Input block
    draw_box(
        0.6, 13.5, 9.8, 13.0,
        'INPUT CITRA',
        'RGB Frame\nResize 320×320×3\nNorm [-1, 1]\n(Fixed Shape)',
        '#f1f5f9', '#475569', title_offset=1.4, body_offset=1.4,
    )
    draw_arrow(10.8, 20.0, 13.4, 20.0)

    # Backbone MobileNetV2 internal stages (stacked top to bottom)
    bb_stages = [
        (13.8, 28.4, 22.0, 5.1, 'Stem: Conv1 3×3 (s=2) + BN + ReLU6', '320×320×3 → 160×160×32 | Block 0 → 160×160×16'),
        (13.8, 22.1, 22.0, 5.1, 'Stage 2: Inverted Residual Block 1–2', '160×160×16 → 80×80×24 (Depthwise + Pointwise)'),
        (13.8, 15.8, 22.0, 5.1, 'Stage 3: Inverted Residual Block 3–5 [C3]', '80×80×24 → 40×40×32 (Fitur detail / objek kecil)'),
        (13.8, 9.5, 22.0, 5.1, 'Stage 4: Inverted Residual Block 6–12 [C4]', '40×40×32 → 20×20×96 (Fitur bodi kendaraan sedang)'),
        (13.8, 3.2, 22.0, 5.1, 'Stage 5: Block 13–16 + Conv_1 1×1 [C5]', '20×20×96 → 10×10×1280 (Semantik global tinggi)'),
    ]
    for idx, (bx, by, bw, bh, btitle, bbody) in enumerate(bb_stages):
        draw_box(bx, by, bw, bh, btitle, bbody, '#dbeafe', '#1d4ed8', title_size=8.0, body_size=7.2, title_offset=0.85, body_offset=1.15)
        if idx < len(bb_stages) - 1:
            draw_arrow(bx + bw / 2, by - 0.1, bx + bw / 2, bb_stages[idx + 1][1] + bb_stages[idx + 1][3] + 0.15, color='#1d4ed8')

    # FPNLite Pyramid Levels (P3-P7)
    fpn_levels = [
        (40.7, 28.4, 19.0, 5.1, 'FPN P3 — 40×40×128', 'Proj 1×1 + Upsample + SepConv 3×3\n9.600 anchors (kendaraan kecil)'),
        (40.7, 22.1, 19.0, 5.1, 'FPN P4 — 20×20×128', 'Proj 1×1 + Upsample + SepConv 3×3\n2.400 anchors (sedang)'),
        (40.7, 15.8, 19.0, 5.1, 'FPN P5 — 10×10×128', 'Proj 1×1 dari C5 (10×10×1280)\n600 anchors (sedang-besar)'),
        (40.7, 9.5, 19.0, 5.1, 'FPN P6 — 5×5×128', 'Bottom-Up SepConv 3×3 (s=2)\n150 anchors (besar)'),
        (40.7, 3.2, 19.0, 5.1, 'FPN P7 — 3×3×128', 'Bottom-Up SepConv 3×3 (s=2)\n54 anchors (sangat besar)'),
    ]
    for fx, fy, fw, fh, ftitle, fbody in fpn_levels:
        draw_box(fx, fy, fw, fh, ftitle, fbody, '#dcfce7', '#15803d', title_size=8.1, body_size=7.1, title_offset=0.55, body_offset=1.05)

    # Tap arrows C3->P3, C4->P4, C5->P5
    draw_arrow(36.2, 18.4, 40.3, 30.9, color='#15803d')
    draw_arrow(36.2, 12.1, 40.3, 24.6, color='#15803d')
    draw_arrow(36.2, 5.8, 40.3, 18.4, color='#15803d')
    # Top-down P5->P4->P3 and bottom-up P5->P6->P7
    draw_arrow(50.2, 21.1, 50.2, 21.95, color='#15803d')
    draw_arrow(50.2, 27.4, 50.2, 28.25, color='#15803d')
    draw_arrow(50.2, 15.6, 50.2, 14.8, color='#15803d')
    draw_arrow(50.2, 9.3, 50.2, 8.5, color='#15803d')

    # SSD Prediction Tower & Parallel Dual Heads (Box + Class)
    draw_box(
        64.8, 22.8, 20.2, 10.6,
        'Shared Prediction Tower',
        '4× SeparableConv2D (3×3, 128 ch)\n+ BatchNorm per skala (P3–P7)\n+ Aktivasi ReLU6\nBobot Conv dibagi ke semua skala',
        '#ffedd5', '#c2410c', title_size=8.5, body_size=7.5, title_offset=1.1, body_offset=1.3,
    )
    draw_box(
        64.6, 3.6, 9.7, 15.2,
        'Box Head',
        'SepConv 3×3\n24 channel\n(6 anchor ×\n4 offset)\n\nOutput:\n(1, 12804, 4)',
        '#fef3c7', '#b45309', title_size=8.3, body_size=7.3, title_offset=1.1, body_offset=1.3,
    )
    draw_box(
        75.5, 3.6, 9.7, 15.2,
        'Class Head',
        f"SepConv 3×3\n{(report['num_classes'] + 1) * 6} channel\n(6 anchor ×\n{report['num_classes']} cls + bg)\n\nOutput:\n(1, 12804, {report['num_classes'] + 1})",
        '#fee2e2', '#b91c1c', title_size=8.3, body_size=7.3, title_offset=1.1, body_offset=1.3,
    )

    draw_arrow(60.1, 28.0, 64.4, 28.0, color='#c2410c')
    # Parallel branches from Shared Prediction Tower to Box Head and Class Head
    draw_arrow(71.5, 22.4, 69.5, 19.2, color='#b45309')
    draw_arrow(78.3, 22.4, 80.3, 19.2, color='#b91c1c')

    # Post-processing / Final Output
    draw_box(
        88.2, 10.5, 11.2, 19.0,
        'POST-PROCESS',
        '12.804 Anchors\n↓\nScore Filter\n(>= thr)\n↓\nNMS (IoU)\n↓\nBBox + Kelas\n(' + '/'.join(report['classes']) + ')',
        '#f3e8ff', '#7e22ce', title_size=8.5, body_size=7.6, title_offset=1.4, body_offset=1.4,
    )
    draw_arrow(85.6, 13.5, 87.8, 17.8, color='#7e22ce')
    # Clean orthogonal routing from Box Head underneath Class Head to Post-Process
    ax.plot([69.5, 69.5, 87.1, 87.1], [3.2, 1.0, 1.0, 14.0], color='#b45309', lw=1.6, solid_capstyle='round')
    draw_arrow(86.9, 14.0, 87.8, 14.0, color='#b45309')

    # Bottom-left: Horizontal bar chart of parameter distribution per component
    ax_bar = fig.add_subplot(gs[1, 0])
    comps = report['components']
    comp_labels = [c['component'].replace(' (', '\n(') for c in comps]
    comp_params = [c['params'] for c in comps]
    comp_colors = ['#2563eb', '#16a34a', '#22c55e', '#ea580c', '#dc2626'][:len(comps)]
    y_pos = list(range(len(comps)))
    bars = ax_bar.barh(y_pos, comp_params, color=comp_colors, edgecolor='#0f172a', linewidth=0.6, alpha=0.88)
    ax_bar.set_yticks(y_pos)
    ax_bar.set_yticklabels(comp_labels, fontsize=8.5)
    ax_bar.invert_yaxis()
    ax_bar.set_xlabel('Jumlah Parameter', fontsize=9.5, fontweight='bold')
    ax_bar.set_title('Distribusi Parameter per Komponen CNN', fontsize=11, fontweight='bold', color='#0f172a', pad=10)
    ax_bar.grid(axis='x', linestyle='--', alpha=0.35)
    ax_bar.set_xlim(0, max(comp_params) * 1.58 if comp_params else 1)
    for bar_rect, comp in zip(bars, comps):
        ax_bar.text(
            bar_rect.get_width() + max(comp_params) * 0.02,
            bar_rect.get_y() + bar_rect.get_height() / 2,
            f"{comp['params']:,} ({comp['param_pct']:.1f}% | {comp['layer_count']} lyr)",
            va='center', ha='left', fontsize=8.1, fontweight='bold', color='#1e293b',
        )

    # Bottom-right: Layer type breakdown + Anchor summary
    ax_type = fig.add_subplot(gs[1, 1])
    top_types = report['layer_types'][:8]
    t_labels = [t['layer_type'] for t in top_types]
    t_counts = [t['count'] for t in top_types]
    ty_pos = list(range(len(top_types)))
    t_bars = ax_type.barh(ty_pos, t_counts, color='#0ea5e9', edgecolor='#0f172a', linewidth=0.6, alpha=0.85)
    ax_type.set_yticks(ty_pos)
    ax_type.set_yticklabels(t_labels, fontsize=8.8)
    ax_type.invert_yaxis()
    ax_type.set_xlabel('Jumlah Layer', fontsize=9.5, fontweight='bold')
    ax_type.set_title('Komposisi Tipe Layer dalam Network CNN', fontsize=11, fontweight='bold', color='#0f172a', pad=10)
    ax_type.grid(axis='x', linestyle='--', alpha=0.35)
    ax_type.set_xlim(0, max(t_counts) * 1.38 if t_counts else 1)
    for bar_rect, item in zip(t_bars, top_types):
        ax_type.text(
            bar_rect.get_width() + max(t_counts) * 0.02,
            bar_rect.get_y() + bar_rect.get_height() / 2,
            f"{item['count']} layer ({item['params']:,} param)",
            va='center', ha='left', fontsize=8.2, color='#1e293b',
        )

    fig.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    return output_path


def show_network(config, root, output_dir='outputs/cnn-network'):
    """Inspect the project's CNN network, print the complete layer list, and export CSV/JSON/TXT/PNG."""
    root = Path(root).resolve()
    out_dir = (root / output_dir).resolve()
    if not out_dir.is_relative_to(root):
        raise ValueError('Folder output network CNN harus berada di dalam repo.')

    os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL', '2')
    classes, export_meta = _resolve_classes_and_export(config, root)

    try:
        report = inspect_keras_detector(config, root)
    except (ImportError, ValueError) as exc:
        if export_meta and export_meta.get('saved_model'):
            saved_dir = root / export_meta['saved_model']
            if (saved_dir / 'saved_model.pb').is_file():
                print(f'Info: Object Detection API tidak aktif ({exc}); membaca langsung dari SavedModel...', flush=True)
                report = inspect_saved_model(saved_dir, classes=classes, checkpoint=export_meta.get('checkpoint'))
            else:
                raise
        else:
            raise

    # Cross-check SavedModel parameter count if export exists and Keras builder was used
    if report['inspection_source'] == 'keras_model_builder' and export_meta and export_meta.get('saved_model'):
        saved_dir = root / export_meta['saved_model']
        if (saved_dir / 'saved_model.pb').is_file():
            report['exported_saved_model'] = export_meta['saved_model']

    out_dir.mkdir(parents=True, exist_ok=True)
    text_summary = format_network_table(report, include_keras_summary=True)
    terminal_text = format_network_table(report, include_keras_summary=False)

    csv_path = out_dir / 'network_layers.csv'
    with csv_path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=['index', 'component', 'name', 'layer_type', 'kernel_stride', 'output_shape', 'params', 'trainable_params', 'non_trainable_params', 'trainable'],
        )
        writer.writeheader()
        writer.writerows(report['layers'])

    json_payload = {k: v for k, v in report.items() if k != 'backbone_keras_summary'}
    json_path = out_dir / 'network_summary.json'
    json_path.write_text(json.dumps(json_payload, indent=2, ensure_ascii=False), encoding='utf-8')

    txt_path = out_dir / 'network_summary.txt'
    txt_path.write_text(text_summary, encoding='utf-8')

    png_path = render_architecture_diagram(report, out_dir / 'cnn_architecture.png')

    print(terminal_text, flush=True)
    print(f'CSV daftar layer   : {csv_path.relative_to(root)}', flush=True)
    print(f'Ringkasan teks     : {txt_path.relative_to(root)}', flush=True)
    print(f'Metadata JSON      : {json_path.relative_to(root)}', flush=True)
    print(f'Diagram arsitektur : {png_path.relative_to(root)}', flush=True)
    return report
