from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from .paths import RUNTIME_DIR, resolve_repo_root

TEXT_RUNTIME_SUFFIXES = {".py", ".sh", ".txt"}


def copy_runtime_tree(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for child in src.iterdir():
        target = dst / child.name
        if child.is_dir():
            copy_runtime_tree(child, target)
            shutil.copystat(child, target)
            continue

        if child.suffix in TEXT_RUNTIME_SUFFIXES:
            content = child.read_text(encoding="utf-8")
            normalized = content.replace("\r\n", "\n").replace("\r", "\n")
            target.write_text(normalized, encoding="utf-8", newline="\n")
            shutil.copystat(child, target)
            continue

        shutil.copy2(child, target)


def hydrate_runtime(repo_root: Path, *, out_dir: Path | None = None, force: bool = False) -> Path:
    target = out_dir or (repo_root / ".worker-build" / "runtime")

    if target.exists():
        if not force:
            raise SystemExit(f"output already exists: {target} (use --force)")
        shutil.rmtree(target)

    target.parent.mkdir(parents=True, exist_ok=True)
    # Keep generated runtime assets stable across Windows and Unix checkouts.
    copy_runtime_tree(RUNTIME_DIR, target)
    return target


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
    target = hydrate_runtime(repo_root, out_dir=args.out_dir, force=args.force)
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
