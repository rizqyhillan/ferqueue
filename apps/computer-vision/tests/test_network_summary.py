import importlib.util
from pathlib import Path
import tempfile
import unittest

from ferqueue_cv import network_summary as ns


class NetworkSummaryUnitTests(unittest.TestCase):
    def sample_layers(self):
        return [
            {
                'index': 1,
                'component': ns.classify_component('Conv1'),
                'name': 'Conv1',
                'layer_type': 'Conv2D',
                'kernel_stride': '3x3, s=2',
                'output_shape': '(1, 160, 160, 32)',
                'params': 864,
                'trainable_params': 864,
                'non_trainable_params': 0,
                'trainable': True,
            },
            {
                'index': 2,
                'component': ns.classify_component('bn_Conv1'),
                'name': 'bn_Conv1',
                'layer_type': 'BatchNormalization',
                'kernel_stride': '-',
                'output_shape': '(1, 160, 160, 32)',
                'params': 128,
                'trainable_params': 64,
                'non_trainable_params': 64,
                'trainable': True,
            },
            {
                'index': 3,
                'component': ns.classify_component('projection_3'),
                'name': 'projection_3',
                'layer_type': 'Conv2D',
                'kernel_stride': '1x1, s=1',
                'output_shape': '(1, 10, 10, 128)',
                'params': 163968,
                'trainable_params': 163968,
                'non_trainable_params': 0,
                'trainable': True,
            },
            {
                'index': 4,
                'component': ns.classify_component('bottom_up_Conv2d_20_depthwise_conv'),
                'name': 'bottom_up_Conv2d_20_depthwise_conv',
                'layer_type': 'SeparableConv2D',
                'kernel_stride': '3x3, s=2',
                'output_shape': '(1, 5, 5, 128)',
                'params': 17536,
                'trainable_params': 17536,
                'non_trainable_params': 0,
                'trainable': True,
            },
            {
                'index': 5,
                'component': ns.classify_component('PredictionTower/conv2d_0'),
                'name': 'PredictionTower/conv2d_0',
                'layer_type': 'SeparableConv2D',
                'kernel_stride': '3x3, s=1',
                'output_shape': 'Shared (P3..P7, 128 ch)',
                'params': 17536,
                'trainable_params': 17536,
                'non_trainable_params': 0,
                'trainable': True,
            },
            {
                'index': 6,
                'component': ns.classify_component('WeightSharedConvolutionalBoxPredictor/WeightSharedConvolutionalClassHead/ClassPredictor'),
                'name': 'ClassPredictor',
                'layer_type': 'SeparableConv2D',
                'kernel_stride': '3x3, s=1',
                'output_shape': 'Shared (P3..P7, 24 ch)',
                'params': 4248,
                'trainable_params': 4248,
                'non_trainable_params': 0,
                'trainable': True,
            },
        ]

    def test_classify_component_covers_all_five_cnn_parts(self):
        self.assertEqual(ns.classify_component('block_3_depthwise'), 'Backbone (MobileNetV2)')
        self.assertEqual(ns.classify_component('smoothing_1_depthwise_conv'), 'Neck (FPNLite Top-Down P3-P5)')
        self.assertEqual(ns.classify_component('bottom_up_Conv2d_21_batchnorm'), 'Neck (FPNLite Coarse P6-P7)')
        self.assertEqual(ns.classify_component('PredictionTower/conv2d_2/BatchNorm/feature_1'), 'Head (SSD Shared Tower)')
        self.assertEqual(
            ns.classify_component('WeightSharedConvolutionalBoxPredictor/PredictionTower/conv2d_0/BatchNorm/feature_4'),
            'Head (SSD Shared Tower)',
        )
        self.assertEqual(ns.classify_component('BoxPredictor'), 'Head (SSD Box & Class Predictor)')
        self.assertEqual(
            ns.classify_component('WeightSharedConvolutionalBoxPredictor/WeightSharedConvolutionalBoxHead/BoxPredictor'),
            'Head (SSD Box & Class Predictor)',
        )

    def test_summaries_and_formatted_table(self):
        layers = self.sample_layers()
        components = ns.summarize_components(layers)
        layer_types = ns.summarize_layer_types(layers)
        total_params = sum(row['params'] for row in layers)

        self.assertEqual(len(components), 5)
        self.assertEqual(sum(c['params'] for c in components), total_params)
        self.assertAlmostEqual(sum(c['param_pct'] for c in components), 100.0, places=1)
        self.assertEqual(layer_types[0]['layer_type'], 'Conv2D')

        report = {
            'architecture': 'SSD MobileNet V2 FPNLite 320x320',
            'model_id': 'ssd_mobilenet_v2_fpnlite_320x320_coco17_tpu-8',
            'checkpoint': 'ckpt-42',
            'inspection_source': 'unit_test',
            'input_shape': '(1, 320, 320, 3)',
            'classes': ['Mobil', 'Truk', 'Bus'],
            'num_classes': 3,
            'total_layers': len(layers),
            'total_params': total_params,
            'trainable_params': sum(row['trainable_params'] for row in layers),
            'non_trainable_params': sum(row['non_trainable_params'] for row in layers),
            'estimated_size_mb_fp32': round(total_params * 4 / (1024 * 1024), 2),
            'fpn_feature_map_shapes': ['(1, 40, 40, 128)', '(1, 20, 20, 128)', '(1, 10, 10, 128)', '(1, 5, 5, 128)', '(1, 3, 3, 128)'],
            'total_anchors': 12804,
            'anchor_specs': ns.ANCHOR_SPECS,
            'components': components,
            'layer_types': layer_types,
            'layers': layers,
            'backbone_keras_summary': None,
        }
        table = ns.format_network_table(report)
        self.assertIn('DAFTAR LENGKAP SELURUH LAYER NETWORK CNN', table)
        self.assertIn('Conv1', table)
        self.assertIn('ClassPredictor', table)
        self.assertIn(f'{total_params:,}', table)

    @unittest.skipUnless(importlib.util.find_spec('matplotlib'), 'Render diagram memerlukan Matplotlib.')
    def test_render_architecture_diagram_writes_png(self):
        layers = self.sample_layers()
        total_params = sum(row['params'] for row in layers)
        report = {
            'architecture': 'SSD MobileNet V2 FPNLite 320x320',
            'model_id': 'ssd_mobilenet_v2_fpnlite_320x320_coco17_tpu-8',
            'classes': ['Mobil', 'Truk', 'Bus'],
            'num_classes': 3,
            'total_layers': len(layers),
            'total_params': total_params,
            'trainable_params': sum(row['trainable_params'] for row in layers),
            'non_trainable_params': sum(row['non_trainable_params'] for row in layers),
            'estimated_size_mb_fp32': round(total_params * 4 / (1024 * 1024), 2),
            'total_anchors': 12804,
            'components': ns.summarize_components(layers),
            'layer_types': ns.summarize_layer_types(layers),
            'layers': layers,
        }
        with tempfile.TemporaryDirectory() as tmp:
            png_path = Path(tmp) / 'cnn_architecture.png'
            ns.render_architecture_diagram(report, png_path)
            self.assertTrue(png_path.is_file())
            self.assertGreater(png_path.stat().st_size, 10000)


if __name__ == '__main__':
    unittest.main()
