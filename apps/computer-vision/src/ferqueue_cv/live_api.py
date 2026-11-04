import io
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from time import perf_counter

import tensorflow as tf
from PIL import Image

from .__main__ import load_config
from .training import detect, load_detector

ROOT = Path.cwd()
CONFIG = load_config("configs/training-coco-bn.json", ROOT)

CONFIDENCE = 0.25
NMS_IOU = 0.45
ORIGINS = {
    "http://localhost:4173",
    "http://127.0.0.1:4173",
}

print("Memuat model...", flush=True)
detector, frozen, metadata = load_detector(CONFIG, ROOT)
classes = frozen["manifest"]["classes"]

# Pemanasan model sebelum menerima frame kamera.
detect(detector, Image.new("RGB", (640, 480)))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)

        origin = self.headers.get("Origin")
        if origin in ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)

        self.send_header(
            "Access-Control-Allow-Methods", "GET, POST, OPTIONS"
        )
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()

        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_OPTIONS(self):
        self.reply({})

    def do_GET(self):
        if self.path != "/health":
            return self.reply({"error": "Alamat tidak ditemukan"}, 404)

        self.reply({
            "status": "ready",
            "classes": classes,
            "model": metadata["saved_model"],
        })

    def do_POST(self):
        if self.path != "/detect":
            return self.reply({"error": "Alamat tidak ditemukan"}, 404)

        if self.headers.get("Origin") not in ORIGINS | {None}:
            return self.reply({"error": "Origin tidak diizinkan"}, 403)

        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 2 * 1024 * 1024:
                return self.reply(
                    {"error": "Ukuran gambar tidak valid"}, 413
                )

            with Image.open(
                io.BytesIO(self.rfile.read(size))
            ) as source:
                image = source.convert("RGB")

            started = perf_counter()
            result = detect(detector, image)

            # Penyaringan tambahan untuk kotak yang bertumpuk,
            # termasuk ketika satu objek mendapat dua kelas.
            keep = tf.image.non_max_suppression(
                result["detection_boxes"],
                result["detection_scores"],
                max_output_size=10,
                iou_threshold=NMS_IOU,
                score_threshold=CONFIDENCE,
            ).numpy()

            detections = []
            for i in keep:
                class_id = int(result["detection_classes"][i])
                if 1 <= class_id <= len(classes):
                    detections.append({
                        "class_name": classes[class_id - 1],
                        "confidence": float(
                            result["detection_scores"][i]
                        ),
                        "box": result["detection_boxes"][i].tolist(),
                    })

            self.reply({
                "detections": detections,
                "inference_ms": round(
                    (perf_counter() - started) * 1000
                ),
            })
        except Exception as error:
            self.reply({"error": str(error)}, 400)


print("Model:", metadata["saved_model"], flush=True)
print("API siap: http://127.0.0.1:8000/health", flush=True)
HTTPServer(("127.0.0.1", 8000), Handler).serve_forever()