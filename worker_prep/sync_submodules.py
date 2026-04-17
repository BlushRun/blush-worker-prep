from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from .paths import PROJECT_DIR


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync and update prep-managed submodules")
    parser.add_argument(
        "--remote",
        action="store_true",
        help="advance submodules to their configured remote branch",
    )
    return parser.parse_args()


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, cwd=str(PROJECT_DIR), check=True)


def main() -> int:
    args = parse_args()
    run(["git", "submodule", "sync", "--recursive"])
    update_cmd = ["git", "submodule", "update", "--init", "--recursive"]
    if args.remote:
        update_cmd.append("--remote")
    run(update_cmd)
    print(PROJECT_DIR / "submodules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
