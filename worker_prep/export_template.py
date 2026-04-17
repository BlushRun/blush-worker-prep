from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ._apollo import iter_workflow_names, render_template_properties, write_text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export template.properties entries")
    parser.add_argument(
        "--workflow",
        action="append",
        default=[],
        help="workflow name, repeatable; defaults to all req/*.api.json entries",
    )
    parser.add_argument(
        "--value-only",
        action="store_true",
        help="print only the JSON value, without the key prefix",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="write to a file instead of stdout",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        workflow_names = iter_workflow_names(args.workflow)
        output = render_template_properties(workflow_names, value_only=args.value_only)
        if args.out is not None:
            write_text(args.out, output)
            print(args.out)
        else:
            sys.stdout.write(output)
        return 0
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
