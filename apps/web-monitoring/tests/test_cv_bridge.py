import io
import json
import unittest
from unittest.mock import patch
from urllib.error import URLError

from app import app


class CameraIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_page_loads_camera_module_and_assets(self):
        page = self.client.get('/')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'/static/app.js', page.data)
        js = self.client.get('/static/app.js')
        self.assertIn(b"import './live_detection.js'", js.data)
        js.close()
        with self.client.get('/static/live_detection.js') as module:
            self.assertEqual(module.status_code, 200)

    def test_image_reaches_server_side_pcv_without_browser_origin(self):
        payload = {'detections': [{'class_name': 'Mobil', 'confidence': .9, 'box': [0, 0, 1, 1]}], 'inference_ms': 12}
        with patch('cv_bridge.urlopen', return_value=io.BytesIO(json.dumps(payload).encode())) as upstream:
            result = self.client.post('/api/detect', data=b'jpeg-bytes', content_type='image/jpeg')
        self.assertEqual(result.json, payload)
        sent = upstream.call_args.args[0]
        self.assertEqual(sent.full_url, 'http://127.0.0.1:8000/detect')
        self.assertEqual(sent.data, b'jpeg-bytes')
        self.assertNotIn('Origin', sent.headers)

    def test_coin_region_and_measurement_pass_through_bridge(self):
        payload = {'detections': [], 'calibration': {'status': 'coin_not_found'}}
        region = '.2,.6,.4,.8'
        with patch('cv_bridge.urlopen', return_value=io.BytesIO(json.dumps(payload).encode())) as upstream:
            result = self.client.post('/api/detect', data=b'jpeg', content_type='image/jpeg', headers={'X-Coin-Region': region})
        self.assertEqual(result.json, payload)
        self.assertEqual(upstream.call_args.args[0].get_header('X-coin-region'), region)

    def test_pcv_offline_has_actionable_message(self):
        with patch('cv_bridge.urlopen', side_effect=URLError('offline')):
            result = self.client.post('/api/detect', data=b'jpeg', content_type='image/jpeg')
        self.assertEqual(result.status_code, 503)
        self.assertIn('terminal kedua', result.json['error'])

    def test_invalid_images_do_not_reach_pcv(self):
        with patch('cv_bridge.urlopen') as upstream:
            for body, kind, status in [(b'', 'image/jpeg', 413), (b'x', 'text/plain', 415), (b'x' * (2 * 1024 * 1024 + 1), 'image/jpeg', 413)]:
                self.assertEqual(self.client.post('/api/detect', data=body, content_type=kind).status_code, status)
        upstream.assert_not_called()

    def test_health_and_invalid_upstream_response(self):
        with patch('cv_bridge.urlopen', return_value=io.BytesIO(b'{"status":"ready"}')):
            self.assertEqual(self.client.get('/api/cv/health').json['status'], 'ready')
        with patch('cv_bridge.urlopen', return_value=io.BytesIO(b'not-json')):
            self.assertEqual(self.client.post('/api/detect', data=b'jpeg', content_type='image/jpeg').status_code, 502)


if __name__ == '__main__':
    unittest.main()
