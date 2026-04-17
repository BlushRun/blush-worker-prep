from __future__ import annotations

import argparse
from pathlib import Path
import sys

from ._lib import (
    is_canvas_workflow,
    is_runpod_request,
    load_json,
    load_workflow_param_specs,
    workflow_param_spec_path,
)
from ._worker_meta import load_worker_meta
from .paths import resolve_repo_root


def workflows_dir() -> Path:
    return resolve_repo_root() / "workflows"


def req_dir() -> Path:
    return resolve_repo_root() / "req"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a worker capability repo")
    parser.add_argument(
        "--template",
        action="store_true",
        help="allow workflows/ and req/ to be empty placeholder directories",
    )
    return parser.parse_args()


def list_workflow_keys() -> list[str]:
    return sorted(
        path.stem
        for path in workflows_dir().glob("*.json")
        if path.is_file() and path.name != ".gitkeep"
    )


def validate_canvas(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        data = load_json(path)
    except ValueError as exc:
        return [f"{path.name}: {exc}"]
    if not is_canvas_workflow(data):
        errors.append(f"{path.name}: not a valid ComfyUI canvas workflow")
    return errors


def validate_api(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        data = load_json(path)
    except ValueError as exc:
        return [f"{path.name}: {exc}"]

    if not is_runpod_request(data):
        errors.append(f"{path.name}: top-level JSON is not a valid RunPod request")
        return errors

    input_data = data.get("input")
    workflow = input_data.get("workflow") if isinstance(input_data, dict) else None
    images = input_data.get("images") if isinstance(input_data, dict) else None
    if not isinstance(workflow, dict):
        errors.append(f"{path.name}: input.workflow is missing or not an object")
    if images is not None and not isinstance(images, list):
        errors.append(f"{path.name}: input.images is not a list")
    return errors


def validate_params(path: Path, workflow_key: str) -> list[str]:
    errors: list[str] = []
    try:
        data = load_json(path)
    except ValueError as exc:
        return [f"{path.name}: {exc}"]

    if data.get("schema_version") != 2:
        errors.append(f"{path.name}: schema_version must be 2")
    if data.get("workflow") != workflow_key:
        errors.append(f"{path.name}: workflow must equal {workflow_key}")
    if not isinstance(data.get("params"), list):
        errors.append(f"{path.name}: params must be a list")
    if not isinstance(data.get("fixed"), list):
        errors.append(f"{path.name}: fixed must be a list")
    review = data.get("review")
    if not isinstance(review, list):
        errors.append(f"{path.name}: review must be a list")
    elif review:
        errors.append(f"{path.name}: review must be empty, found {len(review)} items")
    return errors


def validate_smoke(path: Path, workflow_key: str) -> list[str]:
    errors: list[str] = []
    try:
        data = load_json(path)
    except ValueError as exc:
        return [f"{path.name}: {exc}"]

    if data.get("workflow") != workflow_key:
        errors.append(f"{path.name}: workflow must equal {workflow_key}")
    if data.get("mode") not in {"sync", "async"}:
        errors.append(f"{path.name}: mode must be sync or async")
    params = data.get("params")
    if params is not None and not isinstance(params, dict):
        errors.append(f"{path.name}: params must be an object")
    images = data.get("images")
    if images is not None and not isinstance(images, dict):
        errors.append(f"{path.name}: images must be an object")
    return errors


def validate_param_spec(workflow_key: str) -> list[str]:
    spec_path = workflow_param_spec_path(workflow_key)
    if not spec_path.exists():
        return []
    try:
        load_workflow_param_specs(workflow_key)
    except ValueError as exc:
        return [f"{spec_path.name}: {exc}"]
    return []


def find_extra_req_files(workflow_keys: set[str]) -> list[str]:
    extras: list[str] = []
    patterns = (
        "*.api.json",
        "*.params.json",
        "*.params.spec.json",
        "*.smoke.local.json",
        "*.smoke.remote.json",
    )
    suffixes = (
        ".api.json",
        ".params.json",
        ".params.spec.json",
        ".smoke.local.json",
        ".smoke.remote.json",
    )
    for pattern, suffix in zip(patterns, suffixes):
        for path in req_dir().glob(pattern):
            key = path.name[: -len(suffix)]
            if key not in workflow_keys:
                extras.append(path.name)
    return sorted(extras)


def validate_template_skeleton() -> list[str]:
    errors: list[str] = []
    for directory in (workflows_dir(), req_dir()):
        if not directory.exists():
            errors.append(f"{directory.name}/ is missing")
            continue
        if not (directory / ".gitkeep").exists():
            errors.append(f"{directory.name}/.gitkeep is missing")
    return errors


def main() -> int:
    args = parse_args()
    repo_root = resolve_repo_root()
    errors: list[str] = []

    try:
        meta = load_worker_meta()
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"worker={meta.slug}")
    print(f"provider_key={meta.provider_key}")
    print(f"local_image={meta.local_image}")

    if not (repo_root / "config.yml").exists():
        errors.append("config.yml is missing")

    workflow_keys = list_workflow_keys()
    if not workflow_keys:
        if args.template:
            errors.extend(validate_template_skeleton())
        else:
            errors.append("workflows/ does not contain any *.json files")

    for workflow_key in workflow_keys:
        workflow_path = workflows_dir() / f"{workflow_key}.json"
        api_path = req_dir() / f"{workflow_key}.api.json"
        params_path = req_dir() / f"{workflow_key}.params.json"
        smoke_local_path = req_dir() / f"{workflow_key}.smoke.local.json"
        smoke_remote_path = req_dir() / f"{workflow_key}.smoke.remote.json"

        errors.extend(validate_canvas(workflow_path))

        if not api_path.exists():
            errors.append(f"{api_path.name}: missing API workflow")
        else:
            errors.extend(validate_api(api_path))

        if not params_path.exists():
            errors.append(f"{params_path.name}: missing params manifest")
        else:
            errors.extend(validate_params(params_path, workflow_key))
        errors.extend(validate_param_spec(workflow_key))

        if not smoke_local_path.exists():
            errors.append(f"{smoke_local_path.name}: missing local smoke file")
        else:
            errors.extend(validate_smoke(smoke_local_path, workflow_key))

        if not smoke_remote_path.exists():
            errors.append(f"{smoke_remote_path.name}: missing remote smoke file")
        else:
            errors.extend(validate_smoke(smoke_remote_path, workflow_key))

    for extra in find_extra_req_files(set(workflow_keys)):
        errors.append(f"{extra}: corresponding workflows/*.json file is missing")

    if errors:
        print("\nvalidation failed", file=sys.stderr)
        for item in errors:
            print(f"  - {item}", file=sys.stderr)
        return 1

    if workflow_keys:
        print(f"\nvalidation passed: {len(workflow_keys)} workflow(s)")
    else:
        print("\nvalidation passed: template skeleton is complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
