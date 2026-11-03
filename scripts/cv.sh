#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
if [[ "${1:-}" == "setup" ]]; then
    shift
    exec bash scripts/setup-training.sh "$@"
fi
if [[ ! -x .venv-training/bin/python ]]; then
    echo 'Jalankan bash scripts/cv.sh setup terlebih dahulu di terminal Linux.' >&2
    exit 1
fi
export PYTHONPATH="$repo_root/apps/computer-vision/src${PYTHONPATH:+:$PYTHONPATH}"
export TF_CPP_MIN_LOG_LEVEL=2
export TF_FORCE_GPU_ALLOW_GROWTH=true
export TF_NUM_INTRAOP_THREADS="${TF_NUM_INTRAOP_THREADS:-6}"
export TF_NUM_INTEROP_THREADS="${TF_NUM_INTEROP_THREADS:-2}"
# pip installs CUDA libraries in this venv, without a system CUDA toolkit.
cuda_paths="$(.venv-training/bin/python -c 'import pathlib,site; print(":".join(str(p) for d in site.getsitepackages() for p in pathlib.Path(d).glob("nvidia/*/lib")))')"
if [[ -n "$cuda_paths" ]]; then
    export LD_LIBRARY_PATH="$cuda_paths${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
cuda_bin="$(.venv-training/bin/python -c 'import pathlib,site; print(":".join(str(p) for d in site.getsitepackages() for p in pathlib.Path(d).glob("nvidia/*/bin")))')"
if [[ -n "$cuda_bin" ]]; then export PATH="$cuda_bin:$PATH"; fi
exec .venv-training/bin/python -m ferqueue_cv "$@"
