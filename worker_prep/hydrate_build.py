from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from .paths import RUNTIME_DIR, resolve_repo_root


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Copy runtime assets into .worker-build/")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="override output directory (default: <repo>/.worker-build/runtime)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace an existing output directory",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = resolve_repo_root()
    out_dir = args.out_dir or (repo_root / ".worker-build" / "runtime")

    if out_dir.exists():
        if not args.force:
            raise SystemExit(f"output already exists: {out_dir} (use --force)")
        shutil.rmtree(out_dir)

    out_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(RUNTIME_DIR, out_dir)
    print(out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
