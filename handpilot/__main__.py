"""python -m handpilot [--video FILE] [--dry-run] [--debug]"""
from __future__ import annotations

import argparse
import logging
import os
import sys


def _filter_native_stderr() -> None:
    """Linux: libjpeg prints 'Corrupt JPEG data' straight to fd 2 for every damaged
    webcam frame. Drop those lines (the frame is skipped anyway), keep everything else."""
    import threading
    saved = os.dup(2)
    r, w = os.pipe()
    os.dup2(w, 2)
    os.close(w)
    sys.stderr = os.fdopen(os.dup(saved), "w", buffering=1, encoding="utf-8", errors="replace")

    def pump():
        with os.fdopen(r, "rb") as src, os.fdopen(saved, "wb", buffering=0) as dst:
            for line in src:
                if b"Corrupt JPEG" not in line:
                    dst.write(line)
    threading.Thread(target=pump, name="stderr-filter", daemon=True).start()


def main() -> int:
    ap = argparse.ArgumentParser(prog="handpilot", description="Управление компьютером жестами рук")
    ap.add_argument("--video", default="", help="использовать видеофайл вместо камеры (демо)")
    ap.add_argument("--dry-run", action="store_true", help="распознавать, но не двигать мышь и не печатать")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    if sys.platform.startswith("linux") and not os.environ.get("HANDPILOT_RAW_STDERR"):
        _filter_native_stderr()
    log_file = {}
    if sys.stderr is None:      # pythonw / no console: keep a log file instead of losing messages
        from .config import config_dir
        log_file = {"filename": os.path.join(config_dir(), "handpilot.log"), "encoding": "utf-8"}
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", **log_file)
    os.environ.setdefault("GLOG_minloglevel", "2")          # quieter MediaPipe
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

    from .ui.app import run
    return run(video=args.video, inject=not args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
