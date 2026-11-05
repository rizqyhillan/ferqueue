"""Forward camera images to PCV on the server machine, using the web origin."""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import Blueprint, current_app, jsonify, request

cv_api = Blueprint("cv_api", __name__)
MAX_IMAGE_BYTES = 2 * 1024 * 1024


def forward(path, body=None, content_type=None):
    base = current_app.config.get("CV_API_URL", os.environ.get("CV_API_URL", "http://127.0.0.1:8000"))
    headers = {"Content-Type": content_type} if content_type else {}
    upstream = Request(base.rstrip("/") + path, data=body, headers=headers)
    try:
        with urlopen(upstream, timeout=12) as response:
            payload = json.load(response)
        if not isinstance(payload, dict):
            raise ValueError("Respons PCV bukan object JSON")
        if path == "/detect" and not isinstance(payload.get("detections"), list):
            raise ValueError("Respons PCV tidak berisi detections")
        return jsonify(payload)
    except HTTPError as error:
        return jsonify(error="PCV menolak gambar. Pastikan gambar JPG/PNG valid."), error.code
    except (URLError, TimeoutError, OSError):
        return jsonify(error="PCV belum terhubung. Jalankan API PCV di terminal kedua."), 503
    except (ValueError, UnicodeError):
        return jsonify(error="Respons API PCV tidak valid."), 502


@cv_api.get("/api/cv/health")
def health():
    return forward("/health")


@cv_api.post("/api/detect")
def detect():
    if request.mimetype not in {"image/jpeg", "image/png", "image/webp"}:
        return jsonify(error="Kirim gambar JPG, PNG, atau WebP."), 415
    if request.content_length is None or not 0 < request.content_length <= MAX_IMAGE_BYTES:
        return jsonify(error="Ukuran gambar harus antara 1 byte dan 2 MB."), 413
    return forward("/detect", request.get_data(), request.mimetype)
