"""Install the pinned Object Detection sources and protoc into the repo cache."""

import argparse
from pathlib import Path, PurePosixPath
import platform
import shutil
import subprocess
import sys
import urllib.request
import zipfile

MODELS_COMMIT = '40695ad8964145a90ae1abbcc740c086e7364eac'
PROTOC_VERSION = '3.20.3'


def download(url, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix('.download')
    print(f'Mengunduh {url}', flush=True)
    try:
        with urllib.request.urlopen(url, timeout=120) as source, partial.open('wb') as target:
            shutil.copyfileobj(source, target)
        partial.replace(path)
    finally:
        partial.unlink(missing_ok=True)


def setup_sources(root):
    cache = root / '.cache'
    target = cache / 'tensorflow-models'
    marker = target / '.ferqueue-commit'
    if marker.is_file() and marker.read_text().strip() == MODELS_COMMIT:
        print(f'Sumber TensorFlow sudah siap: {target}')
        return target
    if marker.is_file():
        raise ValueError(f'{target} berasal dari commit lain. Pindahkan folder itu lalu ulangi setup.')
    archive = cache / f'tensorflow-models-{MODELS_COMMIT}.zip'
    if not archive.is_file():
        download(f'https://codeload.github.com/tensorflow/models/zip/{MODELS_COMMIT}', archive)
    with zipfile.ZipFile(archive) as handle:
        for info in handle.infolist():
            relative = PurePosixPath(*PurePosixPath(info.filename).parts[1:])
            if not relative.parts or relative.parts[0] != 'research':
                continue
            if relative.parts[0] == 'research' and (len(relative.parts) < 2 or relative.parts[1] not in ('object_detection', 'slim')):
                continue
            destination = (target / str(relative)).resolve()
            if not destination.is_relative_to(target.resolve()):
                raise ValueError(f'Path arsip tidak valid: {info.filename}')
            if info.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with handle.open(info) as source, destination.open('wb') as output:
                    shutil.copyfileobj(source, output)
    research = target / 'research'
    if not (research / 'object_detection/protos/pipeline.proto').is_file():
        raise ValueError('Arsip TensorFlow tidak berisi Object Detection API yang diharapkan.')
    protoc = setup_protoc(cache)
    protos = sorted((research / 'object_detection/protos').glob('*.proto'))
    subprocess.run([str(protoc), '--proto_path=.', '--python_out=.',
                    *[path.relative_to(research).as_posix() for path in protos]], cwd=research, check=True)
    marker.write_text(MODELS_COMMIT, encoding='ascii')
    return target


def setup_protoc(cache):
    system = platform.system()
    if platform.machine().lower() not in ('amd64', 'x86_64'):
        raise ValueError('Setup sumber TensorFlow ini mendukung Windows/Linux x86_64.')
    suffix = 'win64' if system == 'Windows' else 'linux-x86_64' if system == 'Linux' else None
    if suffix is None:
        raise ValueError('Setup sumber TensorFlow ini mendukung Windows/Linux.')
    directory = cache / f'protoc-{PROTOC_VERSION}-{suffix}'
    executable = directory / 'bin' / ('protoc.exe' if system == 'Windows' else 'protoc')
    if not executable.is_file():
        archive = cache / f'protoc-{PROTOC_VERSION}-{suffix}.zip'
        if not archive.is_file():
            download(f'https://github.com/protocolbuffers/protobuf/releases/download/v{PROTOC_VERSION}/protoc-{PROTOC_VERSION}-{suffix}.zip', archive)
        with zipfile.ZipFile(archive) as handle:
            for info in handle.infolist():
                destination = (directory / info.filename).resolve()
                if not destination.is_relative_to(directory.resolve()):
                    raise ValueError('Path arsip protoc tidak valid.')
            handle.extractall(directory)
        if system != 'Windows':
            executable.chmod(0o755)
    return executable


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources-only', action='store_true')
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 11) or sys.maxsize <= 2 ** 32:
        raise SystemExit('Gunakan Python 3.11 64-bit untuk environment training.')
    root = Path(__file__).resolve().parents[1]
    if not args.sources_only and platform.system() != 'Linux':
        raise SystemExit('Setup training GPU dijalankan dari Ubuntu WSL2 di laptop NVIDIA, bukan PowerShell Windows.')
    try:
        if not args.sources_only:
            subprocess.run([sys.executable, '-m', 'pip', 'install', '-r',
                            str(root / 'apps/computer-vision/requirements-training.txt')], check=True)
            subprocess.run([sys.executable, str(root / 'scripts/fix_tf_slim.py')], check=True)
        setup_sources(root)
        print('Setup training selesai. Jalankan check untuk menguji forward pass model.', flush=True)
    except (OSError, ValueError, subprocess.CalledProcessError, zipfile.BadZipFile) as error:
        raise SystemExit(f'Setup gagal: {error}') from error


if __name__ == '__main__':
    main()
