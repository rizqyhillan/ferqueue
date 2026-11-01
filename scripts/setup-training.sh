#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
if [[ "$(uname -s)" != "Linux" ]]; then
    echo 'Jalankan dari terminal Ubuntu WSL2 pada laptop NVIDIA.' >&2
    exit 1
fi
if ! command -v nvidia-smi >/dev/null 2>&1 && [[ -x /usr/lib/wsl/lib/nvidia-smi ]]; then
    export PATH="/usr/lib/wsl/lib:$PATH"
fi
if ! command -v nvidia-smi >/dev/null 2>&1; then
    echo 'NVIDIA belum terlihat di WSL2. Periksa driver NVIDIA Windows dan panduan docs/TRAINING_GPU_WINDOWS.md.' >&2
    exit 1
fi
nvidia-smi
if [[ ! -x .venv-tools/bin/python ]]; then
    python3 -m venv .venv-tools || {
        echo 'Pasang dukungan venv Ubuntu: sudo apt install python3-venv python3-pip' >&2
        exit 1
    }
fi
.venv-tools/bin/python -m pip install 'uv==0.9.7'
export UV_PYTHON_INSTALL_DIR="$repo_root/.cache/python"
if [[ ! -x .venv-training/bin/python ]]; then
    .venv-tools/bin/uv venv --python 3.11 --seed .venv-training
fi
.venv-training/bin/python scripts/setup_cv.py
bash scripts/cv.sh check --require-gpu
echo 'Environment training NVIDIA siap. Lanjutkan prepare lalu train.'
