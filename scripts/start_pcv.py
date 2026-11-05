"""Start the existing camera model with the correct repository/import paths."""
import argparse
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description="Jalankan API kamera PCV pada port 8000.")
    parser.add_argument("--config", default="configs/training-coco-bn.json")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    suffix = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    candidates = [root / name / suffix for name in (".venv-training", ".venv-inference")]
    python = next((str(p) for p in candidates if p.is_file()), sys.executable)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "apps/computer-vision/src") + os.pathsep + env.get("PYTHONPATH", "")
    env["CV_CONFIG_PATH"] = args.config
    env.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
    print("PCV memuat model; tunggu sampai muncul API siap pada port 8000.", flush=True)
    return subprocess.call([python, "-m", "ferqueue_cv.live_api"], cwd=root, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
