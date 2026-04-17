from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ._lib import is_runpod_request, load_json
from .paths import resolve_repo_root


def req_dir() -> Path:
    return resolve_repo_root() / "req"


def iter_workflow_names(explicit: list[str]) -> list[str]:
    if explicit:
        return explicit

    names: list[str] = []
    for path in sorted(req_dir().glob("*.api.json")):
        names.append(path.name[: -len(".api.json")])
    if not names:
        raise ValueError("req/ does not contain any *.api.json files")
    return names


def validate_request_payload(path: Path, data: dict[str, Any]) -> dict[str, Any]:
    if not is_runpod_request(data):
        raise ValueError(f"invalid RunPod request: {path}")
    input_data = data.get("input")
    if not isinstance(input_data, dict):
        raise ValueError(f"request is missing input object: {path}")
    workflow = input_data.get("workflow")
    if not isinstance(workflow, dict):
        raise ValueError(f"request is missing input.workflow: {path}")
    return workflow


def build_system_fields(manifest: dict[str, Any], workflow_name: str) -> dict[str, Any]:
    fixed = manifest.get("fixed")
    if not isinstance(fixed, list):
        raise ValueError(f"params manifest is missing fixed: {workflow_name}")

    prefix_targets: list[dict[str, str]] = []
    prefix_value: str | None = None
    for item in fixed:
        if not isinstance(item, dict):
            continue
        if item.get("class_type") != "SaveImage" or item.get("field") != "filename_prefix":
            continue
        value = item.get("value")
        if not isinstance(value, str) or not value:
            raise ValueError(f"workflow {workflow_name} has an empty filename_prefix")
        if prefix_value is not None and value != prefix_value:
            raise ValueError(
                f"workflow {workflow_name} has conflicting SaveImage.filename_prefix values: "
                f"{prefix_value!r} vs {value!r}"
            )
        prefix_value = value
        node_id = item.get("node_id")
        if node_id is None or str(node_id) == "":
            raise ValueError(f"workflow {workflow_name} is missing node_id for filename_prefix")
        prefix_targets.append(
            {
                "node_id": str(node_id),
                "class_type": "SaveImage",
                "field": "filename_prefix",
            }
        )

    if prefix_value is None or not prefix_targets:
        raise ValueError(f"workflow {workflow_name} is missing SaveImage.filename_prefix")

    return {
        "filename_prefix": {
            "value": prefix_value,
            "targets": prefix_targets,
        }
    }


def build_template_value(workflow_name: str) -> dict[str, Any]:
    api_path = req_dir() / f"{workflow_name}.api.json"
    params_path = req_dir() / f"{workflow_name}.params.json"

    api_data = load_json(api_path)
    manifest = load_json(params_path)

    review = manifest.get("review")
    if not isinstance(review, list):
        raise ValueError(f"params manifest is missing review: {params_path}")
    if review:
        raise ValueError(f"workflow {workflow_name} still has review items and cannot be exported")

    params = manifest.get("params")
    if not isinstance(params, list):
        raise ValueError(f"params manifest is missing params: {params_path}")

    schema_version = manifest.get("schema_version")
    if schema_version != 2:
        raise ValueError(f"only schema_version=2 is supported: {params_path}")

    body = validate_request_payload(api_path, api_data)
    return {
        "schema_version": 2,
        "workflow": workflow_name,
        "body": body,
        "params": params,
        "system_fields": build_system_fields(manifest, workflow_name),
    }


def render_properties(entries: list[tuple[str, Any]]) -> str:
    lines: list[str] = []
    for key, value in entries:
        serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        lines.append(f"{key}={serialized}")
    return "\n".join(lines) + "\n"


def render_template_properties(workflow_names: list[str], *, value_only: bool = False) -> str:
    lines: list[str] = []
    for workflow_name in workflow_names:
        template = build_template_value(workflow_name)
        serialized = json.dumps(template, ensure_ascii=False, separators=(",", ":"))
        lines.append(serialized if value_only else f"{workflow_name}={serialized}")
    return "\n".join(lines) + "\n"


def build_generation_value(workflow_names: list[str], provider_key: str) -> dict[str, Any]:
    workflows: dict[str, Any] = {}
    for workflow_name in workflow_names:
        workflows[workflow_name] = {
            "enabled": True,
            "template_key": workflow_name,
            "provider_key": provider_key,
        }
    return {"workflows": workflows}


def build_provider_value(
    *,
    base_url: str,
    endpoint_id: str,
    api_key: str,
    status_method: str,
    request_timeout: str,
) -> dict[str, Any]:
    return {
        "kind": "runpod_serverless",
        "runpod": {
            "base_url": base_url,
            "endpoint_id": endpoint_id,
            "api_key": api_key,
            "status_method": status_method,
            "request_timeout": request_timeout,
        },
    }


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
