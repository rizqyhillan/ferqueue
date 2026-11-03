#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
export PIP_CACHE_DIR="$repo_root/.cache/pip"
export UV_CACHE_DIR="$repo_root/.cache/uv"
device=cpu
if [[ "${1:-}" == "--device" && $# == 2 ]]; then
    device="$2"
elif [[ $# != 0 ]]; then
    echo 'Pemakaian: bash scripts/cv.sh setup [--device cpu|cuda]' >&2
    exit 1
fi
if [[ "$device" != cpu && "$device" != cuda ]]; then
    echo 'Device setup harus cpu atau cuda.' >&2
    exit 1
fi
if [[ "$(uname -s)" != "Linux" ]]; then
    echo 'Jalankan dari terminal Linux (native atau WSL2).' >&2
    exit 1
fi
if [[ "$device" == cuda ]]; then
    if ! command -v nvidia-smi >/dev/null 2>&1 && [[ -x /usr/lib/wsl/lib/nvidia-smi ]]; then
        export PATH="/usr/lib/wsl/lib:$PATH"
    fi
    if ! command -v nvidia-smi >/dev/null 2>&1; then
        echo 'NVIDIA belum terlihat. Periksa driver dan docs/TRAINING_GPU_WINDOWS.md.' >&2
        exit 1
    fi
    nvidia-smi
fi
if [[ ! -x .venv-tools/bin/python ]]; then
    python3 -m venv .venv-tools || {
        echo 'Pasang dukungan Python venv/pip dari package manager Linux lalu ulangi setup.' >&2
        exit 1
    }
fi
.venv-tools/bin/python -m pip install 'uv==0.9.7'
export UV_PYTHON_INSTALL_DIR="$repo_root/.cache/python"
if [[ ! -x .venv-training/bin/python ]]; then
    .venv-tools/bin/uv venv --python 3.11 --seed .venv-training
fi
.venv-training/bin/python scripts/setup_cv.py --device "$device"
if [[ "$device" == cuda ]]; then
    bash scripts/cv.sh check --require-gpu
else
    bash scripts/cv.sh check
fi
echo "Environment training $device siap. Setelah dataset lengkap, lanjutkan prepare lalu benchmark/train."
