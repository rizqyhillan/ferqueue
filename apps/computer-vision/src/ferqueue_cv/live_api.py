"""Serve an explicitly selected SavedModel to the existing Flask camera bridge."""

import argparse
import io
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from time import perf_counter

from PIL import Image, ImageOps

from .postprocessing import select_detections
from .settings import DEFAULT_CONFIG, load_config
from .side_measurement import COIN_REGION_HEADER, estimate_side, parse_coin_region
from .training import detect, load_detector


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        # Browser requests use Flask /api/detect; direct clients need no CORS.
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        if self.path != '/health':
            return self.reply({'error': 'Alamat tidak ditemukan'}, 404)
        context = self.server.context
        if context['detector'] is None:
            return self.reply({'status': 'ready', 'calibration_only': True})
        config = context['config']
        self.reply({'status': 'ready', 'classes': context['classes'],
                    'model': context['metadata']['saved_model'],
                    'checkpoint': context['metadata']['checkpoint'],
                    'preprocessing': context['metadata'].get('preprocessing', {}),
                    'confidence_threshold': config['confidence_threshold'],
                    'nms_iou_threshold': config.get('nms_iou_threshold', .45),
                    'max_detections': config.get('max_detections', 10)})

    def do_POST(self):
        if self.path != '/detect':
            return self.reply({'error': 'Alamat tidak ditemukan'}, 404)
        if self.headers.get('Origin'):
            return self.reply({'error': 'Kirim gambar melalui web /api/detect.'}, 403)
        if self.headers.get('Content-Type', '').split(';')[0] not in {'image/jpeg', 'image/png', 'image/webp'}:
            return self.reply({'error': 'Kirim gambar JPG, PNG, atau WebP.'}, 415)
        region = self.headers.get(COIN_REGION_HEADER)
        try:
            region = parse_coin_region(region) if region is not None else None
        except ValueError:
            return self.reply({'error': 'Area koin harus berupa kotak di dalam gambar.'}, 400)
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 2 * 1024 * 1024:
                return self.reply({'error': 'Ukuran gambar tidak valid'}, 413)
            with Image.open(io.BytesIO(self.rfile.read(size))) as source:
                image = ImageOps.exif_transpose(source).convert('RGB')
        except (ValueError, OSError, Image.DecompressionBombError):
            return self.reply({'error': 'Gambar JPG/PNG/WebP tidak valid.'}, 400)
        context = self.server.context
        started = perf_counter()
        detector = context['detector']
        detections = []
        try:
            if detector is not None:
                result = detect(detector, image, context['metadata'].get('preprocessing'))
                for index in select_detections(result, context['config']):
                    class_id = int(result['detection_classes'][index])
                    if 1 <= class_id <= len(context['classes']):
                        detections.append({'class_name': context['classes'][class_id - 1],
                                           'confidence': float(result['detection_scores'][index]),
                                           'box': result['detection_boxes'][index].tolist()})
        except Exception as error:
            print(f'Inferensi gagal: {error}', flush=True)
            return self.reply({'error': 'Inferensi gagal; periksa terminal PCV.'}, 500)

        payload = {'detections': detections, 'inference_ms': round((perf_counter() - started) * 1000)}
        if detector is None:
            payload['calibration_only'] = True
        if region is not None:
            try:
                payload['calibration'] = estimate_side(image, region, detections)
            except ImportError:
                payload['calibration'] = {'status': 'unavailable'}
        self.reply(payload)


def serve(config, root, host='127.0.0.1', port=8000, *, calibration_only=False):
    context = {'config': config, 'detector': None}
    if calibration_only:
        print('Mode kalibrasi koin.', flush=True)
    else:
        print('Memuat model...', flush=True)
        detector, frozen, metadata = load_detector(config, root)
        detect(detector, Image.new('RGB', (640, 480)), metadata.get('preprocessing'))
        context.update(detector=detector, metadata=metadata, classes=frozen['manifest']['classes'])
        print(f'Model: {metadata["saved_model"]}', flush=True)
    with HTTPServer((host, port), Handler) as server:
        server.context = context
        print(f'API siap: http://{host}:{port}/health', flush=True)
        server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=os.environ.get('CV_CONFIG_PATH', DEFAULT_CONFIG))
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', default=8000, type=int)
    parser.add_argument('--calibration-only', action='store_true')
    args = parser.parse_args()
    root = Path.cwd().resolve()
    serve(load_config(args.config, root), root, args.host, args.port, calibration_only=args.calibration_only)


if __name__ == '__main__':
    main()
