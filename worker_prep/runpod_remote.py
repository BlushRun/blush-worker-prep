#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["runpod"]
# ///
"""
对远端 RunPod endpoint 执行 smoke test。

默认读取 req/<workflow>.api.json 与 req/<workflow>.params.json，
再叠加 req/<workflow>.smoke.remote.json 中的 params / images。

设计约束：
- 官方 RunPod endpoint 优先走官方 Python SDK，避免自己维护远端协议细节。
- `--base-url` 只保留给本地 worker / 自定义地址调试，继续走轻量 HTTP fallback。
"""

from __future__ import annotations

import argparse
import base64
import copy
import json
import mimetypes
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request

from ._lib import load_json
from .paths import resolve_repo_root


REPO_ROOT = resolve_repo_root()
REQ_DIR = REPO_ROOT / "req"
TERMINAL_STATUSES = {"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"}


def repo_path(path: Path) -> Path:
    return path if path.is_absolute() else (REPO_ROOT / path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="执行远端 RunPod smoke test")
    parser.add_argument(
        "--smoke-file",
        type=Path,
        required=True,
        help="smoke 文件路径，例如 req/workflow-flux2-klein-9b-t2i.smoke.remote.json",
    )
    parser.add_argument(
        "--base-url",
        default="",
        help="完整 HTTP base URL；用于本地 worker 或自定义地址，传入后不走官方 SDK",
    )
    parser.add_argument(
        "--endpoint-id",
        default="",
        help="官方 RunPod endpoint id；base_url 为空时走官方 Python SDK",
    )
    parser.add_argument(
        "--api-key",
        default="",
        help="RunPod API key；调用官方 endpoint 时通常必填",
    )
    parser.add_argument(
        "--status-method",
        choices=("GET", "POST"),
        default="GET",
        help="仅 HTTP fallback 使用；轮询 /status 的 method（默认 GET）",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="async 模式下的状态轮询间隔秒数（默认 2）",
    )
    parser.add_argument(
        "--request-timeout",
        type=int,
        default=600,
        help="单次 HTTP 请求超时秒数（默认 600）",
    )
    parser.add_argument(
        "--save-dir",
        type=Path,
        default=Path("tmp/runpod-remote"),
        help="响应和解码图片的保存目录",
    )
    parser.add_argument(
        "--dump-request",
        type=Path,
        default=None,
        help="把最终提交给 RunPod 的 JSON 请求体写到文件",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只输出最终请求体，不发 HTTP 请求",
    )
    return parser.parse_args()


def load_manifest(path: Path) -> dict:
    data = load_json(path)
    if not isinstance(data.get("params"), list):
        raise ValueError(f"参数清单格式不合法: {path}")
    return data


def normalize_base_url(args: argparse.Namespace) -> str:
    base_url = args.base_url.strip()
    if base_url:
        return base_url.rstrip("/")
    endpoint_id = args.endpoint_id.strip()
    if not endpoint_id:
        raise ValueError("--base-url 或 --endpoint-id 必须二选一")
    return f"https://api.runpod.ai/v2/{endpoint_id}"


def resolve_transport(args: argparse.Namespace) -> str:
    if args.base_url.strip():
        return "http"
    if args.endpoint_id.strip():
        return "runpod-sdk"
    raise ValueError("--base-url 或 --endpoint-id 必须二选一")


def parse_smoke_file(path: Path) -> dict:
    data = load_json(repo_path(path))
    workflow = data.get("workflow")
    if not isinstance(workflow, str) or not workflow.strip():
        raise ValueError(f"smoke 文件缺少 workflow: {path}")
    if data.get("mode") not in {"sync", "async"}:
        raise ValueError(f"smoke 文件 mode 必须是 sync 或 async: {path}")
    params = data.get("params")
    images = data.get("images")
    if params is not None and not isinstance(params, dict):
        raise ValueError(f"smoke 文件 params 必须是 object: {path}")
    if images is not None and not isinstance(images, dict):
        raise ValueError(f"smoke 文件 images 必须是 object: {path}")
    return data


def build_param_index(manifest: dict) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for param in manifest.get("params", []):
        if not isinstance(param, dict):
            continue
        key = param.get("key")
        if isinstance(key, str) and key:
            result[key] = param
    return result


def normalize_param_value(type_name: str, value):
    if type_name == "string":
        if isinstance(value, str):
            return value
        return str(value)
    if type_name == "int":
        if isinstance(value, bool):
            raise ValueError("bool 不能作为 int")
        return int(value)
    if type_name == "float":
        if isinstance(value, bool):
            raise ValueError("bool 不能作为 float")
        return float(value)
    if type_name == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        raise ValueError(f"无法解析 bool 值: {value!r}")
    return value


def set_workflow_input(payload: dict, node_id: str, field: str, value) -> None:
    workflow = payload.setdefault("input", {}).setdefault("workflow", {})
    node = workflow.get(str(node_id))
    if not isinstance(node, dict):
        raise ValueError(f"workflow 中不存在节点 {node_id}")
    inputs = node.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError(f"workflow 节点 {node_id} 缺少 inputs")
    inputs[field] = value


def upsert_runpod_image(payload: dict, image_name: str, image_value: str) -> None:
    images = payload.setdefault("input", {}).setdefault("images", [])
    if not isinstance(images, list):
        raise ValueError("payload.input.images 不是数组")
    for item in images:
        if isinstance(item, dict) and item.get("name") == image_name:
            item["image"] = image_value
            return
    images.append({"name": image_name, "image": image_value})


def encode_image_data_uri(path: Path) -> str:
    candidate = path if path.is_absolute() else (REPO_ROOT / path)
    if not candidate.exists():
        raise ValueError(f"输入图不存在: {candidate}")
    mime_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(candidate.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def apply_smoke_overrides(payload: dict, manifest: dict, smoke: dict) -> None:
    params_by_key = build_param_index(manifest)

    for key, raw_value in (smoke.get("params") or {}).items():
        param = params_by_key.get(key)
        if param is None:
            raise ValueError(f"smoke 参数未在 params.json 中声明: {key}")
        if param.get("type") == "image":
            raise ValueError(f"图片参数应放在 images 中，不应出现在 params: {key}")
        value = normalize_param_value(str(param.get("type", "string")), raw_value)
        for target in param.get("targets", []):
            set_workflow_input(payload, str(target["node_id"]), str(target["field"]), value)

    for key, image_path in (smoke.get("images") or {}).items():
        param = params_by_key.get(key)
        if param is None:
            raise ValueError(f"smoke 图片参数未在 params.json 中声明: {key}")
        if param.get("type") != "image":
            raise ValueError(f"不是图片参数，不能放在 images: {key}")
        transport = param.get("transport")
        if not isinstance(transport, dict) or transport.get("kind") != "runpod_input_image":
            raise ValueError(f"图片参数缺少 runpod_input_image transport: {key}")
        image_name = transport.get("name")
        if not isinstance(image_name, str) or not image_name:
            raise ValueError(f"图片参数缺少 transport.name: {key}")

        image_value = encode_image_data_uri(Path(str(image_path)))
        upsert_runpod_image(payload, image_name, image_value)
        for target in param.get("targets", []):
            set_workflow_input(payload, str(target["node_id"]), str(target["field"]), image_name)


def request_json(method: str, url: str, payload: dict, timeout: int, headers: dict[str, str]) -> dict:
    body = None
    if method.upper() != "GET":
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers=headers,
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


def build_runpod_endpoint(endpoint_id: str, api_key: str):
    """
    官方 endpoint 调用统一走 RunPod Python SDK。

    这样我们只保留 payload 拼装和结果落盘逻辑，不再手写官方远端协议的 run/status 轮询细节。
    """
    try:
        import runpod
    except ImportError as exc:
        raise RuntimeError("缺少 runpod SDK；请使用 `uv run` 执行本脚本") from exc

    cleaned_api_key = api_key.strip() or None
    return runpod.Endpoint(endpoint_id, api_key=cleaned_api_key)


def request_with_runpod_sdk(args: argparse.Namespace, payload: dict, smoke: dict) -> dict:
    endpoint = build_runpod_endpoint(args.endpoint_id.strip(), args.api_key)

    if smoke["mode"] == "sync":
        # 官方 SDK 的 run_sync 会直接返回 output，不保留完整 envelope。
        # 我们在这里补一个最小响应壳，保证后续落盘和摘要逻辑保持一致。
        output = endpoint.run_sync(payload, timeout=args.request_timeout)
        return {"status": "COMPLETED", "output": output}

    job = endpoint.run(payload)
    output = job.output(timeout=args.request_timeout)
    status = job.status()
    return {
        "id": job.job_id,
        "status": status,
        "output": output,
    }


def request_with_http_fallback(args: argparse.Namespace, base_url: str, payload: dict, smoke: dict) -> dict:
    headers = {"Content-Type": "application/json"}
    if args.api_key.strip():
        headers["Authorization"] = f"Bearer {args.api_key.strip()}"

    if smoke["mode"] == "sync":
        return request_json("POST", f"{base_url}/runsync", payload, args.request_timeout, headers)

    queued = request_json("POST", f"{base_url}/run", payload, args.request_timeout, headers)
    job_id = queued.get("id")
    if not isinstance(job_id, str) or not job_id:
        raise RuntimeError(f"/run 响应缺少任务 ID: {queued}")
    return poll_status(
        base_url,
        job_id,
        args.request_timeout,
        args.poll_interval,
        headers,
        args.status_method,
    )


def poll_status(base_url: str, job_id: str, timeout: int, interval: float, headers: dict[str, str], status_method: str) -> dict:
    status_url = f"{base_url}/status/{job_id}"
    while True:
        if status_method == "GET":
            result = request_json("GET", status_url, {}, timeout, headers)
        else:
            result = request_json("POST", status_url, {}, timeout, headers)
        status = result.get("status")
        if isinstance(status, str) and status in TERMINAL_STATUSES:
            return result
        time.sleep(interval)


def save_outputs(response: dict, save_dir: Path) -> tuple[Path, list[Path]]:
    save_dir.mkdir(parents=True, exist_ok=True)
    saved_images: list[Path] = []
    response_copy = copy.deepcopy(response)
    output = response_copy.get("output")
    if isinstance(output, dict):
        images = output.get("images")
        if isinstance(images, list):
            for idx, image in enumerate(images, start=1):
                if not isinstance(image, dict):
                    continue
                if image.get("type") != "base64":
                    continue
                encoded = image.get("data")
                if not isinstance(encoded, str):
                    continue
                filename = image.get("filename") or f"image-{idx}.bin"
                output_path = save_dir / Path(str(filename)).name
                output_path.write_bytes(base64.b64decode(encoded))
                image["data"] = f"<base64 omitted; saved to {output_path.name}>"
                saved_images.append(output_path)

    response_path = save_dir / "response.json"
    response_path.write_text(
        json.dumps(response_copy, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return response_path, saved_images


def main() -> int:
    args = parse_args()

    try:
        args.smoke_file = repo_path(args.smoke_file)
        args.save_dir = repo_path(args.save_dir)
        if args.dump_request is not None:
            args.dump_request = repo_path(args.dump_request)
        transport = resolve_transport(args)
        smoke = parse_smoke_file(args.smoke_file)
        workflow_key = smoke["workflow"]
        api_path = REQ_DIR / f"{workflow_key}.api.json"
        params_path = REQ_DIR / f"{workflow_key}.params.json"

        payload = copy.deepcopy(load_json(api_path))
        manifest = load_manifest(params_path)
        apply_smoke_overrides(payload, manifest, smoke)

        if args.dump_request is not None:
            args.dump_request.parent.mkdir(parents=True, exist_ok=True)
            args.dump_request.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

        if args.dry_run:
            print(f"workflow: {workflow_key}")
            print(f"mode: {smoke['mode']}")
            print(f"transport: {transport}")
            if transport == "runpod-sdk":
                # dry-run 也实例化一次 SDK 对象，尽早暴露依赖缺失或接口变更问题。
                build_runpod_endpoint(args.endpoint_id.strip(), args.api_key)
                print(f"endpoint_id: {args.endpoint_id.strip()}")
            else:
                print(f"base_url: {normalize_base_url(args)}")
            if args.dump_request is not None:
                print(f"request: {args.dump_request}")
            return 0

        if transport == "runpod-sdk":
            result = request_with_runpod_sdk(args, payload, smoke)
        else:
            base_url = normalize_base_url(args)
            result = request_with_http_fallback(args, base_url, payload, smoke)

        save_root = args.save_dir / workflow_key
        response_path, image_paths = save_outputs(result, save_root)
        print(f"workflow: {workflow_key}")
        print(f"transport: {transport}")
        print(f"status: {result.get('status', '-')}")
        print(f"response: {response_path}")
        for image_path in image_paths:
            print(f"image: {image_path}")
        if result.get("status") != "COMPLETED":
            print(f"错误: {result.get('error', 'RunPod 任务未完成')}", file=sys.stderr)
            return 1
        return 0
    except Exception as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
