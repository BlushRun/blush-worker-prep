"""
blush-worker 开发工具共享库。

提供 workflow 画布 -> API prompt 转换、参数提取与参数清单生成逻辑。
不直接运行，由 dev/ 下的脚本导入。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


# -- 自动分类规则 --

_EXPOSE_RULES: set[tuple[str, str]] = {
    ("CLIPTextEncode", "text"),
    ("RandomNoise", "noise_seed"),
    ("FluxGuidance", "guidance"),
    ("EmptyFlux2LatentImage", "batch_size"),
    ("EmptyFlux2LatentImage", "width"),
    ("EmptyFlux2LatentImage", "height"),
    ("EmptySD3LatentImage", "batch_size"),
    ("EmptySD3LatentImage", "width"),
    ("EmptySD3LatentImage", "height"),
    ("ImageScaleBy", "scale_by"),
}

_FIXED_CLASS_TYPES: set[str] = {
    "UNETLoader",
    "CLIPLoader",
    "VAELoader",
    "CheckpointLoaderSimple",
    "SaveImage",
    "PreviewImage",
    "VAEDecode",
    "VAEEncode",
    "BasicGuider",
    "SamplerCustomAdvanced",
    "ReferenceLatent",
    "GetImageSize+",
}

_FIXED_RULES: set[tuple[str, str]] = {
    ("ImageScaleBy", "upscale_method"),
    ("ImageResizeKJv2", "upscale_method"),
    ("ImageResizeKJv2", "keep_proportion"),
    ("ImageResizeKJv2", "pad_color"),
    ("ImageResizeKJv2", "crop_position"),
    ("ImageResizeKJv2", "divisible_by"),
    ("ImageResizeKJv2", "device"),
    ("LoadImage", "image"),
    ("LoadImage", "upload"),
}

_EXPOSE_TITLES: set[str] = {"步长", "步数", "steps", "step", "宽", "width", "高", "height"}

_GENERIC_PARAM_KEYS: dict[tuple[str, str], tuple[str, str]] = {
    ("CLIPTextEncode", "text"): ("prompt", "提示词"),
    ("RandomNoise", "noise_seed"): ("seed", "随机种子"),
    ("FluxGuidance", "guidance"): ("guidance", "引导强度"),
    ("EmptyFlux2LatentImage", "batch_size"): ("batch_size", "出图数量"),
    ("EmptySD3LatentImage", "batch_size"): ("batch_size", "出图数量"),
    ("EmptyFlux2LatentImage", "width"): ("width", "宽度"),
    ("EmptyFlux2LatentImage", "height"): ("height", "高度"),
    ("EmptySD3LatentImage", "width"): ("width", "宽度"),
    ("EmptySD3LatentImage", "height"): ("height", "高度"),
    ("Flux2Scheduler", "width"): ("width", "宽度"),
    ("Flux2Scheduler", "height"): ("height", "高度"),
    ("ImageScaleBy", "scale_by"): ("scale_by", "缩放系数"),
}

_WORKFLOW_PARAM_SPECS: dict[str, list[dict[str, Any]]] = {
    "flux2-klein-9b-t2i": [
        {
            "key": "prompt",
            "title": "提示词",
            "required": True,
            "targets": [("9", "text")],
        },
        {
            "key": "seed",
            "title": "随机种子",
            "targets": [("8", "noise_seed")],
        },
        {
            "key": "guidance",
            "title": "引导强度",
            "targets": [("2", "guidance")],
        },
        {
            "key": "steps",
            "title": "步数",
            "targets": [("14", "int")],
        },
        {
            "key": "width",
            "title": "宽度",
            "targets": [("7", "width"), ("10", "width")],
        },
        {
            "key": "height",
            "title": "高度",
            "targets": [("7", "height"), ("10", "height")],
        },
        {
            "key": "batch_size",
            "title": "出图数量",
            "targets": [("7", "batch_size")],
        },
    ],
    "flux2-klein-9b-i2i": [
        {
            "key": "input_image",
            "title": "输入图",
            "type": "image",
            "default": "input.png",
            "required": True,
            "targets": [("33", "image")],
            "transport": {
                "kind": "runpod_input_image",
                "name": "input.png",
                "format": "base64_or_data_uri",
            },
        },
        {
            "key": "prompt",
            "title": "提示词",
            "required": True,
            "targets": [("19", "text")],
        },
        {
            "key": "guidance",
            "title": "引导强度",
            "targets": [("15", "guidance")],
        },
        {
            "key": "width",
            "title": "宽度",
            "targets": [("43", "width")],
        },
        {
            "key": "height",
            "title": "高度",
            "targets": [("43", "height")],
        },
        {
            "key": "seed",
            "title": "随机种子",
            "targets": [("23", "noise_seed")],
        },
        {
            "key": "steps",
            "title": "步数",
            "targets": [("35", "int")],
        },
        {
            "key": "batch_size",
            "title": "出图数量",
            "targets": [("25", "batch_size")],
        },
    ],
}


def load_json(path: Path) -> dict[str, Any]:
    """加载 JSON 文件，要求顶层为 object（不支持数组）。"""
    if not path.exists():
        raise ValueError(f"文件不存在: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 解析失败: {path} ({exc})") from exc
    if not isinstance(data, dict):
        raise ValueError("顶层 JSON 必须是 object")
    return data


def is_canvas_workflow(data: dict[str, Any]) -> bool:
    return isinstance(data.get("nodes"), list) and isinstance(data.get("links"), list)


def is_comfy_prompt(data: dict[str, Any]) -> bool:
    if not data:
        return False
    return all(
        isinstance(nid, str)
        and isinstance(nd, dict)
        and isinstance(nd.get("inputs"), dict)
        and isinstance(nd.get("class_type"), str)
        for nid, nd in data.items()
    )


def is_runpod_request(data: dict[str, Any]) -> bool:
    return isinstance(data.get("input"), dict)


def workflow_to_prompt(workflow: dict[str, Any]) -> dict[str, Any]:
    """将 ComfyUI 画布 workflow JSON 转为 API prompt 格式。"""
    links = workflow.get("links")
    nodes = workflow.get("nodes")
    if not isinstance(links, list) or not isinstance(nodes, list):
        raise ValueError("不是合法的 ComfyUI 画布 workflow")

    links_by_id: dict[int, list[Any]] = {}
    for link in links:
        if not isinstance(link, list) or len(link) < 4:
            raise ValueError(f"发现不合法的 link: {link!r}")
        link_id = link[0]
        if not isinstance(link_id, int):
            raise ValueError(f"link id 不是整数: {link!r}")
        links_by_id[link_id] = link

    prompt: dict[str, Any] = {}
    for node in nodes:
        if not isinstance(node, dict):
            raise ValueError(f"发现不合法的 node: {node!r}")

        node_id = node.get("id")
        node_type = node.get("type")
        node_inputs = node.get("inputs") or []
        widget_values = node.get("widgets_values") or []

        if not isinstance(node_id, int) or not isinstance(node_type, str):
            raise ValueError(f"node 缺少合法的 id/type: {node!r}")
        if not isinstance(node_inputs, list):
            raise ValueError(f"node.inputs 不是数组: {node_id}")
        if not isinstance(widget_values, list):
            raise ValueError(f"node.widgets_values 不是数组: {node_id}")

        converted_inputs: dict[str, Any] = {}
        widget_index = 0

        for input_def in node_inputs:
            if not isinstance(input_def, dict):
                raise ValueError(f"node {node_id} 存在不合法的 input 定义: {input_def!r}")

            input_name = input_def.get("name")
            if not isinstance(input_name, str):
                raise ValueError(f"node {node_id} 存在缺少 name 的 input")

            has_widget = bool(input_def.get("widget"))
            widget_value: Any = None
            if has_widget and widget_index < len(widget_values):
                widget_value = widget_values[widget_index]
                widget_index += 1

            link_id = input_def.get("link")
            if isinstance(link_id, int):
                link = links_by_id.get(link_id)
                if link is None:
                    raise ValueError(f"node {node_id} 引用了不存在的 link: {link_id}")
                converted_inputs[input_name] = [str(link[1]), link[2]]
            elif has_widget:
                converted_inputs[input_name] = widget_value

        title = ((node.get("properties") or {}).get("Node name for S&R") or node_type)
        prompt[str(node_id)] = {
            "class_type": node_type,
            "inputs": converted_inputs,
            "_meta": {"title": title},
        }

    return prompt


def _infer_type(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    return "unknown"


def _normalize_title(value: str) -> str:
    return value.strip().lower().replace("_", "").replace(" ", "")


def _classify_param(class_type: str, field: str, title: str) -> bool | str:
    """返回 True (expose), False (fixed), 或 "review"。"""
    if (class_type, field) in _EXPOSE_RULES:
        return True
    if class_type in _FIXED_CLASS_TYPES:
        return False
    if (class_type, field) in _FIXED_RULES:
        return False
    if class_type == "Int Literal" and _normalize_title(title) in {
        _normalize_title(item) for item in _EXPOSE_TITLES
    }:
        return True
    if class_type == "KSamplerSelect":
        return False
    return "review"


def extract_params(
    prompt: dict[str, Any],
    canvas: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """从 API prompt 中提取所有非连线的直接值参数。"""
    canvas_titles: dict[int, str] = {}
    if canvas and isinstance(canvas.get("nodes"), list):
        for node in canvas["nodes"]:
            nid = node.get("id")
            title = node.get("title") or ""
            if isinstance(nid, int) and title:
                canvas_titles[nid] = title

    params: list[dict[str, Any]] = []
    for node_id, node_def in prompt.items():
        if not isinstance(node_def, dict):
            continue
        class_type = node_def.get("class_type", "")
        inputs = node_def.get("inputs", {})
        title = (node_def.get("_meta") or {}).get("title", class_type)
        try:
            canvas_title = canvas_titles.get(int(node_id), "")
        except (ValueError, TypeError):
            canvas_title = ""

        for field, value in inputs.items():
            if isinstance(value, list) and len(value) == 2:
                continue

            effective_title = canvas_title or title
            expose = _classify_param(class_type, field, effective_title)
            params.append(
                {
                    "node_id": node_id,
                    "class_type": class_type,
                    "field": field,
                    "value": value,
                    "type": _infer_type(value),
                    "title": effective_title,
                    "expose": expose,
                }
            )

    return params


def _infer_generic_param_identity(raw_param: dict[str, Any]) -> tuple[str, str] | None:
    key = _GENERIC_PARAM_KEYS.get((raw_param["class_type"], raw_param["field"]))
    if key is not None:
        return key

    if raw_param["class_type"] == "Int Literal":
        title = _normalize_title(str(raw_param.get("title", "")))
        if "步" in title or "step" in title:
            return "steps", "步数"
        if title in {"宽", "width"}:
            return "width", "宽度"
        if title in {"高", "height"}:
            return "height", "高度"

    return None


def _build_target(raw_param: dict[str, Any]) -> dict[str, str]:
    return {
        "node_id": str(raw_param["node_id"]),
        "class_type": str(raw_param["class_type"]),
        "field": str(raw_param["field"]),
    }


def _build_generic_manifest(
    workflow_name: str,
    raw_params: list[dict[str, Any]],
) -> dict[str, Any]:
    grouped: dict[str, dict[str, Any]] = {}
    fixed: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []

    for raw in raw_params:
        expose = raw["expose"]
        if expose is True:
            identity = _infer_generic_param_identity(raw)
            if identity is None:
                review.append(raw)
                continue

            key, title = identity
            existing = grouped.get(key)
            if existing is None:
                existing = {
                    "key": key,
                    "title": title,
                    "type": raw["type"],
                    "default": raw["value"],
                    "targets": [],
                }
                grouped[key] = existing
            existing["targets"].append(_build_target(raw))
        elif expose is False:
            fixed.append(raw)
        else:
            review.append(raw)

    return {
        "schema_version": 2,
        "workflow": workflow_name,
        "params": list(grouped.values()),
        "fixed": fixed,
        "review": review,
    }


def _build_manifest_from_specs(
    workflow_name: str,
    raw_params: list[dict[str, Any]],
    specs: list[dict[str, Any]],
) -> dict[str, Any]:
    raw_index = {(str(item["node_id"]), str(item["field"])): item for item in raw_params}
    consumed: set[tuple[str, str]] = set()
    params: list[dict[str, Any]] = []

    for spec in specs:
        targets: list[dict[str, str]] = []
        default: Any = spec.get("default")
        inferred_type = spec.get("type")

        for node_id, field in spec["targets"]:
            raw = raw_index.get((str(node_id), str(field)))
            if raw is None:
                raise ValueError(
                    f"workflow {workflow_name} 的参数 {spec['key']} 目标不存在: {node_id}.{field}"
                )
            targets.append(_build_target(raw))
            consumed.add((str(node_id), str(field)))
            if default is None:
                default = raw["value"]
            if inferred_type is None:
                inferred_type = raw["type"]

        entry: dict[str, Any] = {
            "key": spec["key"],
            "title": spec.get("title", spec["key"]),
            "type": inferred_type or "unknown",
            "default": default,
            "targets": targets,
        }
        if spec.get("required") is True:
            entry["required"] = True
        if "transport" in spec:
            entry["transport"] = spec["transport"]
        params.append(entry)

    fixed: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    for raw in raw_params:
        target_key = (str(raw["node_id"]), str(raw["field"]))
        if target_key in consumed:
            continue
        if raw["expose"] is False:
            fixed.append(raw)
        else:
            review.append(raw)

    return {
        "schema_version": 2,
        "workflow": workflow_name,
        "params": params,
        "fixed": fixed,
        "review": review,
    }


def build_param_manifest(
    workflow_name: str,
    prompt: dict[str, Any],
    canvas: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """按“用户参数”视角生成参数清单。"""
    raw_params = extract_params(prompt, canvas)
    specs = _WORKFLOW_PARAM_SPECS.get(workflow_name)
    if specs is None:
        return _build_generic_manifest(workflow_name, raw_params)
    return _build_manifest_from_specs(workflow_name, raw_params, specs)
