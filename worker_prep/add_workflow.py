#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml", "requests"]
# ///
"""
一键落地新 workflow（迁移/兼容辅助脚本）。

用法:
  uv run dev/add-workflow.py /path/to/exported-workflow.json
  uv run dev/add-workflow.py workflows/flux2-klein-9b-t2i.json
  uv run dev/add-workflow.py /path/to/workflow.json --dry-run
  uv run dev/add-workflow.py /path/to/workflow.json --apply-nodes

功能:
  1. 复制画布 JSON 到 workflows/（如果来源在 workflows/ 外）
  2. 生成 API prompt 模板 → req/{name}.api.json
  3. 生成参数映射表 → req/{name}.params.json
  4. 检查缺失节点，--apply-nodes 自动写入 config.yml

注意：
  正式主流程现在以 ComfyUI 前端的 “Save (API Format)” 为准。
  本脚本仍然保留，用于已有完整 workflow 的迁移、批量补产物或离线辅助。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from ._lib import (
    build_param_manifest,
    is_canvas_workflow,
    load_json,
    workflow_to_prompt,
)
from .paths import resolve_repo_root

REPO_ROOT = resolve_repo_root()
WORKFLOWS_DIR = REPO_ROOT / "workflows"
REQ_DIR = REPO_ROOT / "req"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="一键落地新 workflow（迁移/兼容辅助）")
    parser.add_argument(
        "source",
        type=Path,
        help="ComfyUI 画布 workflow JSON 文件路径",
    )
    parser.add_argument(
        "--name",
        type=str,
        default=None,
        help="workflow 名称（默认: 文件名去掉 .json）",
    )
    parser.add_argument(
        "--apply-nodes",
        action="store_true",
        help="自动将缺失节点写入 config.yml",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只预览，不写任何文件",
    )
    return parser.parse_args()


def write_json(path: Path, data: dict | list, *, dry_run: bool) -> None:
    if dry_run:
        print(f"  [dry-run] 跳过写入: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"  已写入: {path}")


def main() -> int:
    args = parse_args()
    source = args.source if args.source.is_absolute() else (REPO_ROOT / args.source)
    source = source.resolve()

    # -- 加载并校验 --
    data = load_json(source)
    if not is_canvas_workflow(data):
        print(f"错误: {source} 不是 ComfyUI 画布 workflow（缺少 nodes/links）")
        return 1

    name = args.name or source.stem
    print(f"Workflow: {name}")
    print()

    # -- 1. 复制画布到 workflows/ --
    target_workflow = WORKFLOWS_DIR / f"{name}.json"
    if source != target_workflow.resolve():
        if args.dry_run:
            print(f"  [dry-run] 跳过复制: {source} → {target_workflow}")
        else:
            WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target_workflow)
            print(f"  已复制: {target_workflow}")
    else:
        print(f"  画布已在 workflows/ 中: {target_workflow}")
    print()

    # -- 2. 生成 API prompt --
    print("生成 API prompt...")
    prompt = workflow_to_prompt(data)
    api_request = {"input": {"workflow": prompt, "images": []}}
    api_path = REQ_DIR / f"{name}.api.json"
    write_json(api_path, api_request, dry_run=args.dry_run)
    print(f"  节点数: {len(prompt)}")
    print()

    # -- 3. 生成参数映射表 --
    print("生成参数映射表...")
    params_output = build_param_manifest(name, prompt, data)
    params_path = REQ_DIR / f"{name}.params.json"
    write_json(params_path, params_output, dry_run=args.dry_run)

    params = params_output.get("params", [])
    fixed = params_output.get("fixed", [])
    review = params_output.get("review", [])
    print(f"  用户参数: {len(params)}, fixed: {len(fixed)}, review: {len(review)}")
    if params:
        print("  用户可控参数:")
        for p in params:
            val = repr(p.get("default"))
            if len(val) > 50:
                val = val[:50] + "..."
            targets = ", ".join(
                f"[{target['node_id']}] {target['class_type']}.{target['field']}"
                for target in p.get("targets", [])
            )
            print(f"    {p['key']} ({p['type']}) = {val} -> {targets}")
    if review:
        print("  需要人工确认:")
        for p in review:
            val = repr(p.get("value"))
            if len(val) > 50:
                val = val[:50] + "..."
            print(f"    [{p['node_id']}] {p['class_type']}.{p['field']} = {val}")
    print()

    # -- 4. 检查缺失节点 --
    print("检查缺失节点...")
    resolve_module = "worker_prep.resolve_nodes"
    if True:
        cmd = [
            sys.executable, "-m", resolve_module,
            "--workflow", str(target_workflow),
        ]
        if args.apply_nodes and not args.dry_run:
            cmd.append("--apply")
        env = dict(os.environ)
        env["WORKER_PREP_REPO"] = str(REPO_ROOT)
        result = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env)
        if result.returncode != 0:
            print("  警告: 节点检查发现问题，请查看上方输出")
    print()

    print("完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
