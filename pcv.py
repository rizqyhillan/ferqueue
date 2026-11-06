"""Manual PCV entry point: use the current Python environment, with no setup steps."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
if Path.cwd().resolve() != ROOT:
    raise SystemExit('Jalankan dari root folder ferqueue agar path dataset/config konsisten.')
sys.path.insert(0, str(ROOT / 'apps/computer-vision/src'))

from ferqueue_cv.__main__ import main


if __name__ == '__main__':
    raise SystemExit(main())
