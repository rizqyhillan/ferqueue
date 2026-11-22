import unittest
from unittest.mock import patch
from app import app, antrean_perintah, riwayat_pemeriksaan


class WebMonitoringPagesTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        antrean_perintah.clear()
        riwayat_pemeriksaan.clear()

    def test_root_redirects_to_login_when_unauthenticated(self):
        res = self.client.get('/')
        self.assertEqual(res.status_code, 302)
        self.assertIn('/login', res.headers['Location'])

    def test_login_page_renders_ok(self):
        res = self.client.get('/login')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'FERQUEUE', res.data)
        self.assertIn(b'Masuk ke akun operasional Anda', res.data)
        self.assertIn(b'/static/css/login.css', res.data)

    def test_login_post_and_redirect_to_dashboard(self):
        res = self.client.post('/login', data={'username': 'operator', 'password': 'password123'})
        self.assertEqual(res.status_code, 302)
        self.assertIn('/dashboard', res.headers['Location'])

        # Following redirect to dashboard
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get('user'), 'operator')

        dash = self.client.get('/dashboard')
        self.assertEqual(dash.status_code, 200)
        self.assertIn(b'Ringkasan Operasional Hari Ini', dash.data)
        self.assertIn(b'/static/css/dashboard.css', dash.data)
        self.assertIn(b'/static/js/dashboard.js', dash.data)

    def test_protected_routes_redirect_unauthenticated_users(self):
        for path in ['/dashboard', '/monitoring', '/riwayat', '/ai-assistant']:
            res = self.client.get(path)
            self.assertEqual(res.status_code, 302, f'{path} should redirect when unauthenticated')
            self.assertIn('/login', res.headers['Location'])

    def test_monitoring_page_renders_for_authenticated_user(self):
        with self.client.session_transaction() as sess:
            sess['user'] = 'operator'
        res = self.client.get('/monitoring')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Pemeriksaan Kendaraan', res.data)
        self.assertIn(b'/static/css/monitoring.css', res.data)
        self.assertIn(b'/static/js/monitoring.js', res.data)
        self.assertIn(b'/static/assets/camera-demo.svg', res.data)

    def test_riwayat_page_renders_for_authenticated_user(self):
        with self.client.session_transaction() as sess:
            sess['user'] = 'operator'
        res = self.client.get('/riwayat')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Riwayat Pemeriksaan', res.data)
        self.assertIn(b'/static/css/riwayat.css', res.data)
        self.assertIn(b'/static/js/riwayat.js', res.data)

    def test_ai_assistant_page_renders_for_authenticated_user(self):
        with self.client.session_transaction() as sess:
            sess['user'] = 'operator'
        res = self.client.get('/ai-assistant')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'AI Assistant', res.data)
        self.assertIn(b'/static/css/ai_assistant.css', res.data)
        self.assertIn(b'/static/js/ai_assistant.js', res.data)

    def test_api_ai_query(self):
        mock_reply = {
            'answer': 'Batas berat Golongan A adalah 55 gram sesuai SOP FERQUEUE.',
            'sources': ['aturan_berat.md'],
        }
        with patch('app.rag_service.generate_answer', return_value=mock_reply):
            res = self.client.post('/api/ai/query', json={'query': 'Berapa batas berat Golongan A?'})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get('status'), 'success')
        self.assertIn('55 gram', data.get('summary', ''))
        self.assertEqual(data.get('sources'), ['aturan_berat.md'])

    def test_iot_berat_and_gate_commands(self):
        buka = self.client.post('/api/buka')
        self.assertEqual(buka.status_code, 200)
        post = self.client.post('/api/berat', json={'berat': 62.5, 'jarak': 12.0, 'servo': 0, 'gerbang': 'tutup'})
        self.assertEqual(post.status_code, 200)
        self.assertEqual(post.data.decode(), 'buka')

        get = self.client.get('/api/berat')
        self.assertEqual(get.status_code, 200)
        payload = get.get_json()
        self.assertEqual(payload['berat_gram'], 62.5)
        self.assertEqual(payload['gerbang'], 'tutup')

        servo = self.client.post('/api/servo', json={'posisi': 90})
        self.assertEqual(servo.status_code, 200)
        post2 = self.client.post('/api/berat', json={'berat': 0.0})
        self.assertEqual(post2.data.decode(), 'servo90')

    def test_ticket_overweight_and_problematic_list(self):
        with patch('app.simpan_pemeriksaan', return_value=False), \
             patch('app.ambil_kendaraan_bermasalah', return_value=[]):
            res = self.client.post('/api/tiket', json={
                'pengemudi': 'Budi',
                'golongan': 'A',
                'berat_gram': 70.0,
                'panjang_cm': 12.5,
                'tinggi_cm': 5.2,
            })
            self.assertEqual(res.status_code, 200)
            tiket = res.get_json()['tiket']
            self.assertEqual(tiket['status'], 'Overweight')
            self.assertEqual(tiket['kelebihan'], 15.0)

            prob = self.client.get('/api/kendaraan-bermasalah')
            self.assertEqual(prob.status_code, 200)
            self.assertEqual(prob.get_json()['total'], 1)

    def test_logout_clears_session(self):
        with self.client.session_transaction() as sess:
            sess['user'] = 'operator'
        res = self.client.get('/logout')
        self.assertEqual(res.status_code, 302)
        self.assertIn('/login', res.headers['Location'])
        with self.client.session_transaction() as sess:
            self.assertNotIn('user', sess)

    def test_api_stats(self):
        res = self.client.get('/api/stats')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('total_kendaraan', data)
        self.assertIn('total_truk', data)
        self.assertIn('total_bus', data)
        self.assertIn('total_mobil', data)
        self.assertIn('density_truk', data)

    def test_api_aktivitas(self):
        res = self.client.get('/api/aktivitas')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIsInstance(data, list)

    def test_static_assets_exist(self):
        assets = [
            '/static/css/variables.css',
            '/static/css/base.css',
            '/static/css/login.css',
            '/static/css/dashboard.css',
            '/static/css/monitoring.css',
            '/static/css/riwayat.css',
            '/static/css/ai_assistant.css',
            '/static/js/utils.js',
            '/static/js/dashboard.js',
            '/static/js/monitoring.js',
            '/static/js/riwayat.js',
            '/static/js/ai_assistant.js',
            '/static/js/tickets.js',
            '/static/js/live_detection.js',
            '/static/assets/camera-demo.svg',
            '/static/assets/favicon.svg',
        ]
        for asset in assets:
            res = self.client.get(asset)
            self.assertEqual(res.status_code, 200, f'Asset {asset} failed to load')


if __name__ == '__main__':
    unittest.main()
