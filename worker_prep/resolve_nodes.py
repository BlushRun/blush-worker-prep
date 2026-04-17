# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml", "requests"]
# ///
"""
扫描 workflows/*.json，自动解析缺失的自定义节点并输出 config.yml 配置。

用法:
  uv run dev/resolve-nodes.py                       # 检查缺失节点
  uv run dev/resolve-nodes.py --apply               # 自动写入 config.yml
  uv run dev/resolve-nodes.py --workflow file.json   # 只检查单个 workflow

数据源:
  ComfyUI-Manager 的 extension-node-map.json
  https://github.com/ltdrdata/ComfyUI-Manager
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import requests
import yaml

from .paths import resolve_repo_root

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

NODE_MAP_URL = (
    "https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager"
    "/main/extension-node-map.json"
)

NODE_MAP_CACHE = Path(__file__).resolve().parent / ".node-map-cache.json"
CACHE_MAX_AGE = 86400  # 1 天


# ---------------------------------------------------------------------------
# 节点映射
# ---------------------------------------------------------------------------


@dataclass
class NodeMap:
    """node_type -> (repo_url, title) 的反向映射"""
    _map: dict[str, tuple[str, str]] = field(default_factory=dict)

    def lookup(self, node_type: str) -> tuple[str, str] | None:
        """查找节点类型对应的 (repo_url, title)"""
        return self._map.get(node_type)

    @classmethod
    def load(cls, *, offline: bool = False) -> NodeMap:
        """从缓存或远程加载节点映射"""
        raw = None

        # 尝试缓存
        if NODE_MAP_CACHE.exists():
            import time
            age = time.time() - NODE_MAP_CACHE.stat().st_mtime
            if age < CACHE_MAX_AGE or offline:
                raw = json.loads(NODE_MAP_CACHE.read_text(encoding="utf-8"))

        # 远程拉取
        if raw is None and not offline:
            try:
                print("拉取 ComfyUI-Manager 节点映射...")
                resp = requests.get(NODE_MAP_URL, timeout=30)
                resp.raise_for_status()
                raw = resp.json()
                NODE_MAP_CACHE.write_text(
                    json.dumps(raw, ensure_ascii=False), encoding="utf-8"
                )
            except Exception as e:
                print(f"  警告: 拉取失败: {e}")
                if NODE_MAP_CACHE.exists():
                    raw = json.loads(NODE_MAP_CACHE.read_text(encoding="utf-8"))

        if raw is None:
            print("  错误: 无法加载节点映射")
            return cls()

        # 反转: repo_url -> [node_types] 变为 node_type -> (repo_url, title)
        mapping: dict[str, tuple[str, str]] = {}
        for repo_url, (node_types, meta) in raw.items():
            title = meta.get("title_aux", "")
            for nt in node_types:
                mapping[nt] = (repo_url, title)

        return cls(_map=mapping)


# ---------------------------------------------------------------------------
# Workflow 解析
# ---------------------------------------------------------------------------


def extract_custom_nodes(workflow_path: Path) -> set[str]:
    """从 workflow JSON 提取非核心节点类型"""
    data = json.loads(workflow_path.read_text(encoding="utf-8"))
    nodes = data.get("nodes", [])

    custom = set()
    for node in nodes:
        node_type = node.get("type", "")
        if not node_type:
            continue
        # 核心节点带 cnr_id: "comfy-core"
        props = node.get("properties", {})
        if props.get("cnr_id") == "comfy-core":
            continue
        custom.add(node_type)

    return custom


def scan_workflows(workflows_dir: Path) -> dict[str, set[str]]:
    """扫描目录下所有 workflow，返回 {node_type: {来源文件名...}}"""
    result: dict[str, set[str]] = {}
    for wf in sorted(workflows_dir.glob("*.json")):
        for nt in extract_custom_nodes(wf):
            result.setdefault(nt, set()).add(wf.name)
    return result


# ---------------------------------------------------------------------------
# Config 对比
# ---------------------------------------------------------------------------


def existing_repos(config_path: Path) -> set[str]:
    """读取 config.yml 中已声明的节点 repo URL"""
    if not config_path.exists():
        return set()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not config:
        return set()
    nodes = config.get("nodes") or []
    return {n.get("url", "").rstrip(".git").rstrip("/") for n in nodes if isinstance(n, dict)}


def normalize_url(url: str) -> str:
    """统一 URL 格式用于比较"""
    return url.rstrip(".git").rstrip("/")


def repo_git_url(url: str) -> str:
    normalized = url.rstrip("/")
    if normalized.endswith(".git"):
        return normalized
    return f"{normalized}.git"


def preferred_node_version(repo_url: str) -> str:
    """优先返回最新 tag；没有 tag 时返回默认分支 HEAD commit；失败时回退 latest。"""
    url = repo_git_url(repo_url)

    try:
        result = subprocess.run(
            ["git", "ls-remote", "--tags", "--refs", "--sort=-version:refname", url],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        first_line = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
        if first_line:
            ref = first_line.split()[1]
            prefix = "refs/tags/"
            if ref.startswith(prefix):
                return ref[len(prefix) :]
    except Exception:
        pass

    try:
        result = subprocess.run(
            ["git", "ls-remote", url, "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        first_line = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
        if first_line:
            sha = first_line.split()[0]
            if len(sha) >= 12:
                return sha[:12]
    except Exception:
        pass

    return "latest"


# ---------------------------------------------------------------------------
# 输出 & 应用
# ---------------------------------------------------------------------------


@dataclass
class MissingNode:
    node_type: str
    repo_url: str
    title: str
    workflows: set[str]


def find_missing(
    custom_nodes: dict[str, set[str]],
    node_map: NodeMap,
    known_repos: set[str],
) -> tuple[list[MissingNode], list[str]]:
    """返回 (可解析的缺失节点, 无法解析的节点类型)"""
    missing: dict[str, MissingNode] = {}  # repo_url -> MissingNode
    unresolved: list[str] = []

    for node_type, workflows in sorted(custom_nodes.items()):
        result = node_map.lookup(node_type)
        if result is None:
            unresolved.append(node_type)
            continue

        repo_url, title = result
        if normalize_url(repo_url) in known_repos:
            continue

        key = normalize_url(repo_url)
        if key in missing:
            missing[key].workflows.update(workflows)
        else:
            missing[key] = MissingNode(
                node_type=node_type,
                repo_url=repo_url,
                title=title,
                workflows=set(workflows),
            )

    return list(missing.values()), unresolved


def apply_to_config(config_path: Path, nodes: list[MissingNode]) -> None:
    """将缺失节点追加到 config.yml"""
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    existing = config.get("nodes") or []

    for node in nodes:
        url = node.repo_url
        if not url.endswith(".git"):
            url += ".git"
        existing.append({"url": url, "version": preferred_node_version(url)})

    config["nodes"] = existing

    # 保留注释头部，重写 nodes 部分
    text = config_path.read_text(encoding="utf-8")
    # 找到 nodes: 行的位置
    lines = text.splitlines(keepends=True)
    nodes_start = None
    for i, line in enumerate(lines):
        if line.strip().startswith("nodes:"):
            nodes_start = i
            break

    if nodes_start is None:
        # 没有 nodes 段，直接追加
        with open(config_path, "a", encoding="utf-8") as f:
            f.write("\nnodes:\n")
            for node in nodes:
                url = node.repo_url
                if not url.endswith(".git"):
                    url += ".git"
                version = preferred_node_version(url)
                f.write(f"  # {node.title} ({node.node_type})\n")
                f.write(f"  - url: {url}\n")
                f.write(f"    version: {version}\n\n")
        return

    # 找到 nodes 段结尾
    nodes_end = len(lines)
    for i in range(nodes_start + 1, len(lines)):
        stripped = lines[i].strip()
        # 遇到下一个顶级 key 就停
        if stripped and not stripped.startswith("#") and not stripped.startswith("-") and not stripped.startswith("url") and not stripped.startswith("version") and ":" in stripped and not stripped.startswith(" "):
            nodes_end = i
            break

    # 构建新的追加行
    new_lines: list[str] = []
    for node in nodes:
        url = node.repo_url
        if not url.endswith(".git"):
            url += ".git"
        version = preferred_node_version(url)
        new_lines.append(f"\n  # {node.title} ({node.node_type})\n")
        new_lines.append(f"  - url: {url}\n")
        new_lines.append(f"    version: {version}\n")

    # 插入到 nodes 段末尾
    result = lines[:nodes_end] + new_lines + lines[nodes_end:]
    config_path.write_text("".join(result), encoding="utf-8")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def main() -> int:
    repo_root = resolve_repo_root()
    parser = argparse.ArgumentParser(
        description="扫描 workflow，解析缺失的自定义节点"
    )
    parser.add_argument(
        "--workflow", type=Path, default=None,
        help="只检查单个 workflow 文件",
    )
    parser.add_argument(
        "--workflows-dir", type=Path, default=repo_root / "workflows",
        help="workflow 目录 (默认: ./workflows)",
    )
    parser.add_argument(
        "--config", type=Path, default=repo_root / "config.yml",
        help="config.yml 路径 (默认: ./config.yml)",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="自动将缺失节点写入 config.yml",
    )
    parser.add_argument(
        "--offline", action="store_true",
        help="只用本地缓存，不拉取远程数据",
    )
    args = parser.parse_args()
    if args.workflow is not None and not args.workflow.is_absolute():
        args.workflow = repo_root / args.workflow
    if not args.workflows_dir.is_absolute():
        args.workflows_dir = repo_root / args.workflows_dir
    if not args.config.is_absolute():
        args.config = repo_root / args.config

    # 加载节点映射
    node_map = NodeMap.load(offline=args.offline)

    # 扫描 workflow
    if args.workflow:
        if not args.workflow.exists():
            print(f"错误: 文件不存在: {args.workflow}")
            return 1
        custom_nodes = {}
        for nt in extract_custom_nodes(args.workflow):
            custom_nodes[nt] = {args.workflow.name}
    else:
        if not args.workflows_dir.exists():
            print(f"错误: 目录不存在: {args.workflows_dir}")
            return 1
        custom_nodes = scan_workflows(args.workflows_dir)

    if not custom_nodes:
        print("没有发现自定义节点")
        return 0

    print(f"发现 {len(custom_nodes)} 个自定义节点类型\n")

    # 对比 config.yml
    known = existing_repos(args.config)
    missing, unresolved = find_missing(custom_nodes, node_map, known)

    if not missing and not unresolved:
        print("所有自定义节点已在 config.yml 中声明")
        return 0

    # 输出缺失节点
    if missing:
        print("缺失节点:")
        for node in missing:
            wf_list = ", ".join(sorted(node.workflows))
            print(f"  {node.node_type}")
            print(f"    -> {node.repo_url}")
            print(f"    来源: {wf_list}")
        print()

        if args.apply:
            apply_to_config(args.config, missing)
            print(f"已写入 {len(missing)} 条节点到 {args.config}")
        else:
            print("建议添加到 config.yml:\n")
            for node in missing:
                url = node.repo_url
                if not url.endswith(".git"):
                    url += ".git"
                version = preferred_node_version(url)
                print(f"  # {node.title} ({node.node_type})")
                print(f"  - url: {url}")
                print(f"    version: {version}")
                print()

    # 无法解析的节点
    if unresolved:
        print("无法解析的节点 (不在 ComfyUI-Manager 数据库中):")
        for nt in unresolved:
            print(f"  {nt}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
