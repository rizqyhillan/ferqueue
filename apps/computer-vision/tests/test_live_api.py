import importlib.util
import io
import json
from http.server import HTTPServer
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw

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

    @unittest.skipUnless(importlib.util.find_spec('cv2'), 'OpenCV diperlukan untuk kalibrasi koin.')
    def test_same_frame_provides_coin_scale_and_dimensions(self):
        import numpy as np
        image = Image.new('RGB', (640, 320), 'white')
        ImageDraw.Draw(image).ellipse((488, 128, 552, 192), fill='black')
        encoded = io.BytesIO()
        image.save(encoded, format='PNG')
        region = {'Content-Type': 'image/png', 'X-Coin-Region': '.3,.7,.7,.95'}
        result = {'detection_boxes': np.array([[.4, .2, .6, .4]]),
                  'detection_scores': np.array([.9]), 'detection_classes': np.array([1])}
        with patch('ferqueue_cv.live_api.detect', return_value=result):
            status, payload = self.send('/detect', encoded.getvalue(), region)
        self.assertEqual(status, 200)
        calibration = payload['calibration']
        self.assertEqual(calibration['status'], 'ready')
        measurement = calibration['measurement']
        self.assertEqual(measurement['status'], 'estimated')
        self.assertAlmostEqual(measurement['length_cm'], 4.2, delta=.1)
        self.assertAlmostEqual(measurement['height_cm'], 2.1, delta=.06)

        self.server.context['detector'] = None
        with patch('ferqueue_cv.live_api.detect') as detect:
            status, payload = self.send('/detect', encoded.getvalue(), region)
            detect.assert_not_called()
        self.assertEqual(status, 200)
        self.assertTrue(payload['calibration_only'])
        self.assertEqual(payload['calibration']['measurement']['status'], 'no_vehicle')

    @unittest.skipUnless(importlib.util.find_spec('cv2'), 'OpenCV diperlukan untuk kalibrasi koin.')
    def test_tilted_coin_and_partial_vehicle_do_not_produce_dimensions(self):
        from ferqueue_cv.side_measurement import estimate_side

        frame = Image.new('RGB', (640, 320), 'white')
        region = (.3, .7, .7, .95)
        ImageDraw.Draw(frame).ellipse((488, 128, 552, 170), fill='black')
        self.assertEqual(estimate_side(frame, region, [])['status'], 'coin_not_found')

        ImageDraw.Draw(frame).ellipse((488, 128, 552, 192), fill='black')
        partial = {'box': [.4, 0, .6, .4]}
        self.assertEqual(estimate_side(frame, region, [partial])['measurement'], {'status': 'vehicle_clipped'})
        self.assertEqual(estimate_side(frame, region, [partial, partial])['measurement'], {'status': 'multiple_vehicles'})

    def test_invalid_coin_region_is_rejected(self):
        for region in ('0,0,1', '0,0,1,1.1', '0,0,nan,1', '0,.5,1,.5'):
            with self.subTest(region=region):
                status, _ = self.send('/detect', b'png', {'Content-Type': 'image/png', 'X-Coin-Region': region})
                self.assertEqual(status, 400)


if __name__ == '__main__':
    unittest.main()
