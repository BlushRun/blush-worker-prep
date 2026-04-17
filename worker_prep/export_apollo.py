from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ._apollo import (
    build_generation_value,
    build_provider_value,
    iter_workflow_names,
    render_properties,
    render_template_properties,
    write_text,
)
from ._worker_meta import load_worker_meta


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export Apollo template/generation/provider bundle")
    parser.add_argument(
        "--workflow",
        action="append",
        default=[],
        help="workflow name, repeatable; defaults to all req/*.api.json entries",
    )
    parser.add_argument(
        "--provider-mode",
        choices=("local", "remote"),
        default="local",
        help="provider.properties output mode",
    )
    parser.add_argument("--provider-base-url", default="", help="override runpod.base_url")
    parser.add_argument("--provider-endpoint-id", default="", help="override runpod.endpoint_id")
    parser.add_argument("--provider-api-key", default="", help="override runpod.api_key")
    parser.add_argument("--provider-status-method", default="", help="override runpod.status_method")
    parser.add_argument(
        "--request-timeout",
        default="90s",
        help="provider.runpod.request_timeout (default: 90s)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("tmp/apollo"),
        help="output directory (default: tmp/apollo)",
    )
    return parser.parse_args()


def resolve_provider_fields(args: argparse.Namespace, *, local_base_url: str) -> tuple[str, str, str, str]:
    if args.provider_mode == "local":
        return (
            args.provider_base_url.strip() or local_base_url,
            "",
            "",
            args.provider_status_method.strip() or "POST",
        )

    return (
        args.provider_base_url.strip(),
        args.provider_endpoint_id.strip() or "<runpod-endpoint-id>",
        args.provider_api_key.strip() or "<runpod-api-key>",
        args.provider_status_method.strip() or "GET",
    )


def main() -> int:
    args = parse_args()
    try:
        meta = load_worker_meta()
        workflow_names = iter_workflow_names(args.workflow)
        base_url, endpoint_id, api_key, status_method = resolve_provider_fields(
            args,
            local_base_url=meta.local_base_url,
        )

        template_output = render_template_properties(workflow_names)
        generation_output = render_properties(
            [("workflows", build_generation_value(workflow_names, meta.provider_key)["workflows"])]
        )
        provider_output = render_properties(
            [
                (
                    meta.provider_key,
                    build_provider_value(
                        base_url=base_url,
                        endpoint_id=endpoint_id,
                        api_key=api_key,
                        status_method=status_method,
                        request_timeout=args.request_timeout.strip(),
                    ),
                )
            ]
        )

        out_dir = args.out_dir
        write_text(out_dir / "template.properties", template_output)
        write_text(out_dir / "generation.properties", generation_output)
        write_text(out_dir / "provider.properties", provider_output)

        print(f"provider_key={meta.provider_key}")
        print(f"provider_mode={args.provider_mode}")
        print(out_dir)
        return 0
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
