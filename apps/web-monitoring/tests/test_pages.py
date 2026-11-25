import base64
from pathlib import Path
import unittest
from unittest.mock import patch
from app import app, antrean_perintah, riwayat_pemeriksaan, CAPTURES_DIR


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
            'used_vision': False,
            'used_fallback': False,
            'retrieval_mode': 'hybrid_vector_keyword',
        }
        with patch('app.rag_service.generate_answer', return_value=mock_reply) as mock_gen:
            res = self.client.post('/api/ai/query', json={
                'query': 'Berapa batas berat Golongan A?',
                'history': [
                    {'role': 'user', 'content': 'Halo'},
                    {'role': 'assistant', 'content': 'Halo petugas!'},
                ],
            })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get('status'), 'success')
        self.assertIn('55 gram', data.get('summary', ''))
        self.assertEqual(data.get('sources'), ['aturan_berat.md'])
        kwargs = mock_gen.call_args.kwargs
        self.assertEqual(len(kwargs['chat_history']), 2)
        self.assertIn('ringkasan_hari_ini', kwargs['operational_summary'])

    def test_api_ai_daily_audit_and_multimodal_vision(self):
        fake_jpeg = base64.b64encode(b'\xff\xd8\xff\xe0vision-test-jpeg\xff\xd9').decode('ascii')
        data_url = f'data:image/jpeg;base64,{fake_jpeg}'

        with patch('app.simpan_pemeriksaan', return_value=False), \
             patch('app.ambil_semua_riwayat', return_value=[]):
            self.client.post('/api/tiket', json={
                'pengemudi': 'Rizal',
                'golongan': 'C',
                'berat_gram': 130.0,
                'panjang_cm': 12.0,
                'tinggi_cm': 3.6,
            })

            # Uji ringkasan audit harian dengan fallback lokal (tanpa perlu koneksi Gemini)
            with patch('rag_service._get_genai_client', side_effect=RuntimeError('offline-test')):
                res_audit = self.client.post('/api/ai/query', json={
                    'query': 'Buatkan ringkasan audit harian hari ini',
                })
            self.assertEqual(res_audit.status_code, 200)
            audit_json = res_audit.get_json()
            self.assertEqual(audit_json['mode'], 'audit_harian')
            self.assertTrue(audit_json['used_fallback'])
            self.assertIn('Ringkasan Audit Harian', audit_json['summary'])
            self.assertIn('Overweight: 1', audit_json['summary'])

            # Uji audit visual multimodal lewat lampiran foto di chat
            mock_vision = {
                'answer': 'Foto menunjukkan kendaraan jenis Truk (Golongan C).',
                'sources': ['aturan_berat.md'],
                'used_vision': True,
                'used_fallback': False,
                'retrieval_mode': 'keyword_local',
            }
            with patch('app.rag_service.generate_answer', return_value=mock_vision) as mock_gen:
                res_vis = self.client.post('/api/ai/query', json={
                    'query': 'Verifikasi golongan kendaraan pada foto ini',
                    'image': data_url,
                })
            self.assertEqual(res_vis.status_code, 200)
            vis_json = res_vis.get_json()
            self.assertTrue(vis_json['used_vision'])
            self.assertEqual(vis_json['mode'], 'audit_visual_bebas')
            self.assertEqual(mock_gen.call_args.kwargs['image_mime'], 'image/jpeg')
            self.assertTrue(len(mock_gen.call_args.kwargs['image_bytes']) > 0)

    def test_api_ai_knowledge_crud_and_reindex(self):
        test_filename = 'test_sop_sementara_unit.md'
        try:
            list_res = self.client.get('/api/ai/knowledge')
            self.assertEqual(list_res.status_code, 200)
            files = [f['filename'] for f in list_res.get_json()['files']]
            self.assertIn('aturan_berat.md', files)
            self.assertIn('tarif_dan_golongan.md', files)

            with patch('rag_service.reindex_knowledge', return_value={
                'indexed_files': len(files) + 1,
                'indexed_chunks': 10,
                'vector_ready': True,
                'warning': None,
            }):
                create_res = self.client.post('/api/ai/knowledge', json={
                    'filename': test_filename,
                    'content': '# SOP Uji Sementara\nAturan uji manajemen SOP.',
                })
                self.assertEqual(create_res.status_code, 200)
                self.assertEqual(create_res.get_json()['file']['filename'], test_filename)

                read_res = self.client.get(f'/api/ai/knowledge/{test_filename}')
                self.assertEqual(read_res.status_code, 200)
                self.assertIn('SOP Uji Sementara', read_res.get_json()['file']['content'])

                # Tolak path traversal
                bad_res = self.client.post('/api/ai/knowledge', json={
                    'filename': '../bahaya.py',
                    'content': 'x',
                })
                self.assertEqual(bad_res.status_code, 400)

                del_res = self.client.delete(f'/api/ai/knowledge/{test_filename}')
                self.assertEqual(del_res.status_code, 200)
                self.assertEqual(del_res.get_json()['deleted'], test_filename)
        finally:
            from rag_service import KNOWLEDGE_DIR
            leftover = KNOWLEDGE_DIR / test_filename
            if leftover.exists():
                leftover.unlink()

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

    def test_ticket_saves_captured_photo_for_riwayat_and_opens_gate(self):
        fake_jpeg = base64.b64encode(b'\xff\xd8\xff\xe0test-jpeg-bytes\xff\xd9').decode('ascii')
        data_url = f'data:image/jpeg;base64,{fake_jpeg}'
        saved_path = None
        try:
            with patch('app.simpan_pemeriksaan', return_value=False), \
                 patch('app.ambil_semua_riwayat', return_value=[]):
                res = self.client.post('/api/tiket', json={
                    'pengemudi': 'Siti',
                    'golongan': 'A',
                    'berat_gram': 42.0,
                    'panjang_cm': 11.4,
                    'tinggi_cm': 4.8,
                    'foto': data_url,
                })
                self.assertEqual(res.status_code, 200)
                tiket = res.get_json()['tiket']
                foto_url = tiket.get('foto_url')
                self.assertIsNotNone(foto_url)
                self.assertTrue(foto_url.startswith('/static/captures/'))

                saved_path = CAPTURES_DIR / Path(foto_url).name
                self.assertTrue(saved_path.exists())
                self.assertIn('buka', antrean_perintah)

                # Foto bisa diakses lewat URL statis & muncul di API riwayat
                img_res = self.client.get(foto_url)
                self.assertEqual(img_res.status_code, 200)
                img_res.close()

                riwayat_res = self.client.get('/api/tiket')
                self.assertEqual(riwayat_res.status_code, 200)
                rows = riwayat_res.get_json()['data']
                self.assertEqual(rows[0]['foto_url'], foto_url)
        finally:
            if saved_path and saved_path.exists():
                saved_path.unlink()

    def test_logout_clears_session(self):
        with self.client.session_transaction() as sess:
            sess['user'] = 'operator'
        res = self.client.get('/logout')
        self.assertEqual(res.status_code, 302)
        self.assertIn('/login', res.headers['Location'])
        with self.client.session_transaction() as sess:
            self.assertNotIn('user', sess)

    def test_api_stats(self):
        with patch('app.ambil_semua_riwayat', return_value=[]):
            res_empty = self.client.get('/api/stats')
            self.assertEqual(res_empty.status_code, 200)
            empty_data = res_empty.get_json()
            self.assertEqual(empty_data['total_kendaraan'], 0)
            self.assertEqual(empty_data['total_truk'], 0)
            self.assertEqual(empty_data['total_bus'], 0)
            self.assertEqual(empty_data['total_mobil'], 0)
            self.assertEqual(len(empty_data['density_truk']), 24)
            self.assertEqual(len(empty_data['density_2h']), 12)

            with patch('app.simpan_pemeriksaan', return_value=False):
                self.client.post('/api/tiket', json={
                    'pengemudi': 'Andi',
                    'golongan': 'A',
                    'berat_gram': 40.0,
                    'panjang_cm': 6.0,
                    'tinggi_cm': 2.2,
                })
                self.client.post('/api/tiket', json={
                    'pengemudi': 'Budi',
                    'golongan': 'C',
                    'berat_gram': 120.0,
                    'panjang_cm': 11.0,
                    'tinggi_cm': 3.5,
                })

            res = self.client.get('/api/stats')
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data['total_kendaraan'], 2)
            self.assertEqual(data['total_mobil'], 1)
            self.assertEqual(data['total_truk'], 1)
            self.assertEqual(data['total_bus'], 0)
            self.assertEqual(data['total_normal'], 1)
            self.assertEqual(data['total_overweight'], 1)
            self.assertEqual(data['rata_rata']['mobil']['berat_gram'], 40.0)
            self.assertEqual(data['rata_rata']['truk']['panjang_cm'], 11.0)

    def test_api_aktivitas(self):
        with patch('app.ambil_semua_riwayat', return_value=[]):
            res = self.client.get('/api/aktivitas')
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 0)

            with patch('app.simpan_pemeriksaan', return_value=False):
                self.client.post('/api/tiket', json={
                    'pengemudi': 'Citra',
                    'golongan': 'B',
                    'berat_gram': 75.0,
                    'panjang_cm': 10.5,
                    'tinggi_cm': 3.2,
                })
            res2 = self.client.get('/api/aktivitas')
            rows = res2.get_json()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['nama_pengemudi'], 'Citra')
            self.assertEqual(rows[0]['jenis_kendaraan'], 'Bus')

    def test_api_system_status(self):
        with patch('app.is_cv_api_reachable', return_value=False), \
             patch('app.ambil_kendaraan_bermasalah', return_value=[]):
            res = self.client.get('/api/system-status')
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertIn('sensor_live', data)
            self.assertIn('gerbang', data)
            self.assertEqual(data['cv_online'], False)
            self.assertEqual(data['overweight_count'], 0)

    def test_bounding_box_has_no_percentage_and_enter_prints_then_exits(self):
        with self.client.session_transaction() as sess:
            sess['user'] = 'operator'
        mon_page = self.client.get('/monitoring')
        self.assertEqual(mon_page.status_code, 200)
        self.assertNotIn(b'AI ACC:', mon_page.data)
        self.assertNotIn(b'98.4%', mon_page.data)

        with self.client.get('/static/js/live_detection.js') as live_js:
            self.assertEqual(live_js.status_code, 200)
            self.assertNotIn(b'confidence * 100', live_js.data)

        with self.client.get('/static/js/monitoring.js') as mon_js:
            self.assertEqual(mon_js.status_code, 200)
            self.assertIn(b'printAndCloseTicketModal', mon_js.data)
            self.assertIn(b'window.print()', mon_js.data)
            self.assertIn(b'afterprint', mon_js.data)

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
            '/static/js/live_detection.js',
            '/static/assets/camera-demo.svg',
            '/static/assets/favicon.svg',
        ]
        for asset in assets:
            with self.client.get(asset) as res:
                self.assertEqual(res.status_code, 200, f'Asset {asset} failed to load')


if __name__ == '__main__':
    unittest.main()
