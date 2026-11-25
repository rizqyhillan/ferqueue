import importlib.util
import io
import json
from http.server import HTTPServer
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from PIL import Image

from ferqueue_cv.live_api import Handler


@unittest.skipUnless(importlib.util.find_spec('numpy'), 'NumPy diperlukan untuk hasil deteksi buatan.')
class LiveApiContractTests(unittest.TestCase):
    def setUp(self):
        self.server = HTTPServer(('127.0.0.1', 0), Handler)
        self.server.context = {
            'config': {'confidence_threshold': .7, 'nms_iou_threshold': .3, 'max_detections': 2},
            'classes': ['Mobil'], 'detector': object(),
            'metadata': {'checkpoint': 'ckpt-9', 'saved_model': 'models/example/saved_model',
                         'preprocessing': {'gamma': .8}},
        }
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def send(self, path, data=None, headers=None):
        request = Request(self.base + path, data=data, headers=headers or {})
        try:
            response = urlopen(request, timeout=2)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def test_health_reports_actual_model_and_config_filters(self):
        status, payload = self.send('/health')
        self.assertEqual(status, 200)
        self.assertEqual(payload['status'], 'ready')
        self.assertEqual(payload['confidence_threshold'], .7)
        self.assertEqual(payload['nms_iou_threshold'], .3)
        self.assertEqual(payload['preprocessing'], {'gamma': .8})
        self.assertEqual(payload['checkpoint'], 'ckpt-9')

    def test_valid_frame_uses_exported_processing_and_config_confidence(self):
        import numpy as np
        encoded = io.BytesIO()
        Image.new('RGB', (80, 60), 'red').save(encoded, format='PNG')
        result = {'detection_boxes': np.array([[0, 0, .5, .5], [.5, .5, 1, 1]]),
                  'detection_scores': np.array([.9, .6]), 'detection_classes': np.array([1, 1])}
        with patch('ferqueue_cv.live_api.detect', return_value=result) as detect:
            status, payload = self.send('/detect', encoded.getvalue(), {'Content-Type': 'image/png'})
        self.assertEqual(status, 200)
        self.assertEqual(len(payload['detections']), 1)
        self.assertEqual(payload['detections'][0]['class_name'], 'Mobil')
        self.assertEqual(payload['detections'][0]['box'], [0, 0, .5, .5])
        self.assertIs(detect.call_args.args[0], self.server.context['detector'])
        self.assertEqual(detect.call_args.args[2], {'gamma': .8})

    def test_invalid_uploads_do_not_reach_the_model(self):
        with patch('ferqueue_cv.live_api.detect') as detect:
            cases = [(b'bad', {'Content-Type': 'image/png'}, 400),
                     (b'', {'Content-Type': 'image/png'}, 413),
                     (b'bad', {'Content-Type': 'text/plain'}, 415),
                     (b'bad', {'Content-Type': 'image/png', 'Origin': 'http://localhost:5000'}, 403)]
            for data, headers, expected in cases:
                with self.subTest(expected=expected):
                    status, _ = self.send('/detect', data, headers)
                    self.assertEqual(status, expected)
            detect.assert_not_called()

    def test_invalid_camera_geometry_is_rejected(self):
        for header in ('27.7,14.3', '0,14.3,1.0', '27.7,-1,1.0', '27.7,14.3,0', '27.7,14.3,nan', 'bad,14.3,1.0'):
            with self.subTest(header=header):
                status, _ = self.send('/detect', b'png', {'Content-Type': 'image/png', 'X-Camera-Geometry': header})
                self.assertEqual(status, 400)

    def test_camera_geometry_trigonometry_estimates_length_and_height(self):
        import numpy as np
        encoded = io.BytesIO()
        Image.new('RGB', (640, 360), 'white').save(encoded, format='PNG')
        # Triangle: d_perp = 27.7 cm, d_parallel = 14.3 cm -> D = 31.17 cm, yaw = 27.31 deg.
        # focal_norm = 654.57 / 640 = 1.022766 -> cm_per_px = 31.1734 / 654.57 = 0.047624 cm/px.
        # Box: dx = 0.25 * 640 = 160 px -> proj_len = 7.62 cm -> Mobil (L=2.25) -> P = (7.62 - 2.25*sin)/cos = 7.41 cm.
        #      dy = 0.13 * 360 = 46.8 px -> T = 2.23 cm.
        headers = {'Content-Type': 'image/png', 'X-Camera-Geometry': '27.7,14.3,1.022766'}
        result = {'detection_boxes': np.array([[.45, .40, .58, .65]]),
                  'detection_scores': np.array([.9]), 'detection_classes': np.array([1])}
        with patch('ferqueue_cv.live_api.detect', return_value=result):
            status, payload = self.send('/detect', encoded.getvalue(), headers)
        self.assertEqual(status, 200)
        cal = payload['calibration']
        self.assertEqual(cal['status'], 'ready')
        self.assertEqual(cal['method'], 'trigonometry')
        self.assertAlmostEqual(cal['geometry']['distance_cm'], 31.17, delta=.01)
        self.assertAlmostEqual(cal['geometry']['yaw_deg'], 27.31, delta=.01)
        measurement = cal['measurement']
        self.assertEqual(measurement['status'], 'estimated')
        self.assertAlmostEqual(measurement['length_cm'], 7.41, delta=.02)
        self.assertAlmostEqual(measurement['height_cm'], 2.23, delta=.02)
        self.assertEqual(measurement['assumed_width_cm'], 2.25)

        self.server.context['detector'] = None
        with patch('ferqueue_cv.live_api.detect') as detect:
            status, payload = self.send('/detect', encoded.getvalue(), headers)
            detect.assert_not_called()
        self.assertEqual(status, 200)
        self.assertTrue(payload['calibration_only'])
        self.assertEqual(payload['calibration']['measurement']['status'], 'no_vehicle')

    def test_camera_geometry_edge_cases(self):
        from ferqueue_cv.side_measurement import estimate_side_from_geometry

        frame = Image.new('RGB', (640, 360), 'white')
        geometry = (27.7, 14.3, 1.022766)
        self.assertEqual(estimate_side_from_geometry(frame, geometry, [])['measurement'], {'status': 'no_vehicle'})
        box = {'class_name': 'Mobil', 'box': [.45, .40, .58, .65]}
        self.assertEqual(estimate_side_from_geometry(frame, geometry, [box, box])['measurement'],
                         {'status': 'multiple_vehicles'})
        clipped = {'class_name': 'Mobil', 'box': [.45, 0.0, .58, .65]}
        self.assertEqual(estimate_side_from_geometry(frame, geometry, [clipped])['measurement'],
                         {'status': 'vehicle_clipped'})
        tiny = {'class_name': 'Mobil', 'box': [.45, .40, .48, .41]}
        self.assertEqual(estimate_side_from_geometry(frame, geometry, [tiny])['measurement'],
                         {'status': 'vehicle_too_small'})
        # Perpendicular camera (d_parallel = 0 -> yaw = 0): length equals projected length directly.
        perp = estimate_side_from_geometry(frame, (30.0, 0.0, 1.0), [{'class_name': 'Truk', 'box': [.4, .2, .6, .4]}])
        self.assertEqual(perp['geometry']['yaw_deg'], 0.0)
        self.assertAlmostEqual(perp['measurement']['length_cm'], 6.0, delta=.01)
        self.assertAlmostEqual(perp['measurement']['height_cm'], 3.38, delta=.01)


if __name__ == '__main__':
    unittest.main()
