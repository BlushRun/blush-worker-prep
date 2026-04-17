#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# ///
"""
宿主机侧 RunPod 本地调试工具。

支持三种输入:
1. ComfyUI 画布 workflow JSON
2. ComfyUI API prompt JSON
3. 完整 RunPod request JSON

额外支持:
- 根据 req/*.params.json 用 --param 覆盖业务参数
- 根据 RunPod input.images 用 --image 上传输入图
"""

from __future__ import annotations

import argparse
import base64
import copy
import json
import mimetypes
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from ._lib import (
    build_param_manifest,
    is_canvas_workflow,
    is_comfy_prompt,
    is_runpod_request,
    load_json,
    workflow_to_prompt,
)
from ._worker_meta import load_worker_meta
from .paths import resolve_repo_root


REPO_ROOT = resolve_repo_root()
REQ_DIR = REPO_ROOT / "req"
TERMINAL_STATUSES = {"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"}


def parse_args() -> argparse.Namespace:
    default_base_url = load_worker_meta().local_base_url
    parser = argparse.ArgumentParser(description=f"调用本地 RunPod worker ({default_base_url})")
    parser.add_argument(
        "source",
        type=Path,
        help="JSON 文件路径：支持 ComfyUI 画布 workflow、API prompt、完整 RunPod request",
    )
    parser.add_argument(
        "--base-url",
        default=default_base_url,
        help=f"RunPod 本地 API 地址 (默认: {default_base_url})",
    )
    parser.add_argument(
        "--mode",
        choices=("sync", "async"),
        default="sync",
        help="sync = /runsync；async = /run + /status 轮询",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="async 模式下的状态轮询间隔秒数 (默认: 2)",
    )
    parser.add_argument(
        "--request-timeout",
        type=int,
        default=600,
        help="单次 HTTP 请求超时秒数 (默认: 600)",
    )
    parser.add_argument(
        "--save-dir",
        type=Path,
        default=Path("volumes/output/runpod-local"),
        help="响应摘要和解码图片的保存目录",
    )
    parser.add_argument(
        "--params-file",
        type=Path,
        default=None,
        help="参数清单文件路径（默认尝试匹配 req/<source-stem>.params.json）",
    )
    parser.add_argument(
        "--param",
        action="append",
        default=[],
        help="覆盖参数，格式 key=value，可重复传入",
    )
    parser.add_argument(
        "--image",
        action="append",
        default=[],
        help="上传输入图，格式 param_key=path，可重复传入",
    )
    parser.add_argument(
        "--dump-request",
        type=Path,
        default=None,
        help="把最终提交到 RunPod 的 JSON 请求体落盘，便于排查格式问题",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只做格式识别和转换，不发 HTTP 请求",
    )
    parser.epilog = f"默认 --base-url 跟随 worker.toml 推导为 {default_base_url}"
    return parser.parse_args()


def repo_path(path: Path) -> Path:
    return path if path.is_absolute() else (REPO_ROOT / path)


def build_request(data: dict[str, Any]) -> tuple[dict[str, Any], str]:
    if is_runpod_request(data):
        payload = copy.deepcopy(data)
    elif is_comfy_prompt(data):
        payload = {"input": {"workflow": data, "images": []}}
    elif is_canvas_workflow(data):
        payload = {"input": {"workflow": workflow_to_prompt(data), "images": []}}
    else:
        raise ValueError(
            "无法识别 JSON 类型。仅支持 ComfyUI 画布 workflow、ComfyUI API prompt、完整 RunPod request。"
        )

    if not isinstance(payload.get("input"), dict):
        raise ValueError("RunPod request 缺少 input")
    payload["input"].setdefault("images", [])

    if is_runpod_request(data):
        return payload, "runpod-request"
    if is_comfy_prompt(data):
        return payload, "comfy-prompt"
    return payload, "canvas-workflow"


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def request_json(method: str, url: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    body = None
    if method.upper() != "GET":
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"请求失败: {exc.code} {exc.reason}\n{error_body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"请求失败: {exc.reason}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"响应不是合法 JSON: {raw[:500]}") from exc

    if not isinstance(data, dict):
        raise RuntimeError("响应顶层不是 JSON object")
    return data


def poll_status(base_url: str, job_id: str, timeout: int, interval: float) -> dict[str, Any]:
    status_url = f"{base_url}/status/{job_id}"
    while True:
        result = request_json("POST", status_url, {}, timeout)
        status = result.get("status")
        if isinstance(status, str) and status in TERMINAL_STATUSES:
            return result
        time.sleep(interval)


def parse_assignments(items: list[str], flag_name: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"{flag_name} 参数格式必须是 key=value: {item}")
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise ValueError(f"{flag_name} 参数 key 不能为空: {item}")
        parsed[key] = value
    return parsed


def infer_params_file(source: Path) -> Path | None:
    stems = [source.stem]
    if source.name.endswith(".api.json"):
        stems.insert(0, source.name[: -len(".api.json")])

    for stem in stems:
        candidate = REQ_DIR / f"{stem}.params.json"
        if candidate.exists():
            return candidate
    return None


def load_param_manifest_from_file(path: Path) -> dict[str, Any]:
    manifest = load_json(path)
    if not isinstance(manifest.get("params"), list):
        raise ValueError(f"参数清单格式不合法: {path}")
    return manifest


def infer_param_manifest(
    args: argparse.Namespace,
    source_kind: str,
    source_data: dict[str, Any],
    payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, Path | None]:
    if args.params_file is not None:
        manifest_path = args.params_file
        return load_param_manifest_from_file(manifest_path), manifest_path

    manifest_path = infer_params_file(args.source)
    if manifest_path is not None:
        return load_param_manifest_from_file(manifest_path), manifest_path

    if source_kind == "canvas-workflow":
        workflow = payload.get("input", {}).get("workflow")
        if isinstance(workflow, dict):
            return build_param_manifest(args.source.stem, workflow, source_data), None

    return None, None


def coerce_param_value(raw_value: str, type_name: str) -> Any:
    if type_name == "string":
        return raw_value
    if type_name == "int":
        return int(raw_value)
    if type_name == "float":
        return float(raw_value)
    if type_name == "bool":
        normalized = raw_value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"无法解析 bool 值: {raw_value}")
    raise ValueError(f"暂不支持的参数类型: {type_name}")


def encode_image_data_uri(path: Path) -> str:
    candidate = repo_path(path)
    if not candidate.exists():
        raise ValueError(f"输入图不存在: {candidate}")
    mime_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(candidate.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def set_workflow_input(payload: dict[str, Any], node_id: str, field: str, value: Any) -> None:
    workflow = payload.setdefault("input", {}).setdefault("workflow", {})
    if not isinstance(workflow, dict):
        raise ValueError("payload.input.workflow 不是 object")
    node = workflow.get(str(node_id))
    if not isinstance(node, dict):
        raise ValueError(f"workflow 中不存在节点 {node_id}")
    inputs = node.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError(f"workflow 节点 {node_id} 缺少 inputs")
    inputs[field] = value


def upsert_runpod_image(payload: dict[str, Any], image_name: str, image_value: str) -> None:
    images = payload.setdefault("input", {}).setdefault("images", [])
    if not isinstance(images, list):
        raise ValueError("payload.input.images 不是数组")

    for image in images:
        if isinstance(image, dict) and image.get("name") == image_name:
            image["image"] = image_value
            return

    images.append({"name": image_name, "image": image_value})


def build_param_index(manifest: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    params = manifest.get("params", [])
    by_key: dict[str, dict[str, Any]] = {}
    by_transport_name: dict[str, dict[str, Any]] = {}

    for param in params:
        if not isinstance(param, dict):
            continue
        key = param.get("key")
        if isinstance(key, str) and key:
            by_key[key] = param
        transport = param.get("transport")
        if isinstance(transport, dict):
            name = transport.get("name")
            if isinstance(name, str) and name:
                by_transport_name[name] = param

    return by_key, by_transport_name


def apply_manifest_overrides(
    payload: dict[str, Any],
    manifest: dict[str, Any],
    param_assignments: dict[str, str],
    image_assignments: dict[str, str],
) -> None:
    params_by_key, params_by_transport_name = build_param_index(manifest)

    for key, raw_value in param_assignments.items():
        param = params_by_key.get(key)
        if param is None:
            raise ValueError(f"参数清单中不存在参数: {key}")
        if param.get("type") == "image":
            raise ValueError(f"图片参数请使用 --image: {key}")
        value = coerce_param_value(raw_value, str(param.get("type", "string")))
        for target in param.get("targets", []):
            set_workflow_input(payload, str(target["node_id"]), str(target["field"]), value)

    for image_key, image_path_raw in image_assignments.items():
        param = params_by_key.get(image_key) or params_by_transport_name.get(image_key)
        if param is None:
            raise ValueError(f"参数清单中不存在图片参数: {image_key}")
        if param.get("type") != "image":
            raise ValueError(f"不是图片参数，不能使用 --image: {image_key}")
        transport = param.get("transport")
        if not isinstance(transport, dict) or transport.get("kind") != "runpod_input_image":
            raise ValueError(f"图片参数缺少 runpod_input_image transport: {image_key}")

        image_name = transport.get("name")
        if not isinstance(image_name, str) or not image_name:
            raise ValueError(f"图片参数缺少 transport.name: {image_key}")

        image_path = Path(image_path_raw)
        image_value = encode_image_data_uri(image_path)
        upsert_runpod_image(payload, image_name, image_value)

        for target in param.get("targets", []):
            set_workflow_input(payload, str(target["node_id"]), str(target["field"]), image_name)


def maybe_dump_request(path: Path | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    write_json(path, payload)


def save_outputs(response: dict[str, Any], save_dir: Path) -> tuple[Path, list[Path]]:
    save_dir.mkdir(parents=True, exist_ok=True)
    job_id = str(response.get("id") or "unknown-job")
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    response_copy = copy.deepcopy(response)
    saved_images: list[Path] = []

    output = response_copy.get("output")
    if isinstance(output, dict):
        images = output.get("images")
        if isinstance(images, list):
            for index, image in enumerate(images, start=1):
                if not isinstance(image, dict):
                    continue
                if image.get("type") != "base64":
                    continue
                encoded = image.get("data")
                if not isinstance(encoded, str):
                    continue

                filename = image.get("filename")
                if not isinstance(filename, str) or not filename.strip():
                    filename = f"{job_id}-{index}.bin"
                output_path = save_dir / Path(filename).name
                output_path.write_bytes(base64.b64decode(encoded))
                image["data"] = f"<base64 omitted; saved to {output_path.name}>"
                saved_images.append(output_path)

    response_path = save_dir / f"{timestamp}-{job_id}-response.json"
    write_json(response_path, response_copy)
    return response_path, saved_images


def print_summary(
    source_kind: str,
    response: dict[str, Any],
    response_path: Path,
    image_paths: list[Path],
) -> None:
    job_id = response.get("id", "-")
    status = response.get("status", "-")
    print(f"来源类型: {source_kind}")
    print(f"任务 ID: {job_id}")
    print(f"状态: {status}")
    print(f"响应摘要: {response_path}")
    for image_path in image_paths:
        print(f"图片: {image_path}")
    error = response.get("error")
    if error:
        print(f"错误: {error}", file=sys.stderr)


def main() -> int:
    args = parse_args()

    try:
        args.source = repo_path(args.source)
        if args.params_file is not None:
            args.params_file = repo_path(args.params_file)
        if args.dump_request is not None:
            args.dump_request = repo_path(args.dump_request)
        args.save_dir = repo_path(args.save_dir)

        data = load_json(args.source)
        payload, source_kind = build_request(data)

        param_assignments = parse_assignments(args.param, "--param")
        image_assignments = parse_assignments(args.image, "--image")

        manifest, manifest_path = infer_param_manifest(args, source_kind, data, payload)
        if param_assignments or image_assignments:
            if manifest is None:
                raise ValueError("未找到参数清单，无法使用 --param/--image")
            apply_manifest_overrides(payload, manifest, param_assignments, image_assignments)

        maybe_dump_request(args.dump_request, payload)

        if args.dry_run:
            print(f"来源类型: {source_kind}")
            print("dry-run: 未发送请求")
            workflow = payload.get("input", {}).get("workflow")
            if isinstance(workflow, dict):
                print(f"节点数: {len(workflow)}")
            images = payload.get("input", {}).get("images")
            if isinstance(images, list):
                print(f"输入图: {len(images)}")
            if manifest_path is not None:
                print(f"参数清单: {manifest_path}")
            if args.dump_request is not None:
                print(f"请求体: {args.dump_request}")
            return 0

        base_url = args.base_url.rstrip("/")
        if args.mode == "sync":
            response = request_json("POST", f"{base_url}/runsync", payload, args.request_timeout)
        else:
            queued = request_json("POST", f"{base_url}/run", payload, args.request_timeout)
            job_id = queued.get("id")
            if not isinstance(job_id, str) or not job_id:
                raise RuntimeError(f"/run 响应缺少任务 ID: {queued}")
            response = poll_status(base_url, job_id, args.request_timeout, args.poll_interval)

        response_path, image_paths = save_outputs(response, args.save_dir)
        print_summary(source_kind, response, response_path, image_paths)

        status = response.get("status")
        if status != "COMPLETED":
            return 1
        return 0
    except Exception as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
