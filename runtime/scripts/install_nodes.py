# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""
按 config.yml 安装 ComfyUI 自定义节点，支持版本锁定。

用法:
  python install_nodes.py [--config config.yml] [--comfyui-dir /comfyui]
  python install_nodes.py --dry-run
  python install_nodes.py --force

版本控制:
  latest   — 最新 tag（无 tag 则 fallback 到默认分支最新提交）
  nightly  — 默认分支最新提交（每次启动都 pull）
  v1.2.3   — 指定 tag
  abc1234  — 指定 commit hash
  main     — 指定分支
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
import yaml

# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NodeEntry:
    """config.yml 中的一条节点声明"""
    url: str
    version: str
    index: int = 0

    @property
    def repo_name(self) -> str:
        match = re.search(r"/([^/]+?)(?:\.git)?$", self.url)
        return match.group(1) if match else "unknown"


# ---------------------------------------------------------------------------
# 配置解析
# ---------------------------------------------------------------------------


@dataclass
class NodeConfigParser:
    """解析 config.yml 的 nodes 部分"""
    file_path: Path
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def parse(self) -> list[NodeEntry]:
        if not self.file_path.exists():
            self.errors.append(f"配置文件不存在: {self.file_path}")
            return []

        try:
            config = yaml.safe_load(self.file_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            self.errors.append(f"YAML 解析错误: {e}")
            return []

        if not config:
            return []

        nodes_raw = config.get("nodes") or []
        if not isinstance(nodes_raw, list):
            self.errors.append("'nodes' 必须是列表")
            return []

        entries: list[NodeEntry] = []
        for idx, item in enumerate(nodes_raw, 1):
            if not isinstance(item, dict):
                self.warnings.append(f"节点 {idx}: 不是字典，跳过")
                continue

            url = item.get("url", "")
            version = item.get("version", "latest")

            if not url:
                self.warnings.append(f"节点 {idx}: 缺少 url")
                continue

            if not self._valid_url(url):
                self.warnings.append(f"节点 {idx}: URL 不像 git 仓库: {url}")

            entries.append(NodeEntry(url=url, version=version, index=idx))

        return entries

    @staticmethod
    def _valid_url(url: str) -> bool:
        return bool(
            re.search(r"(github|gitlab|gitea|bitbucket)\.", url)
            or url.endswith(".git")
        )


# ---------------------------------------------------------------------------
# 节点安装器
# ---------------------------------------------------------------------------


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """执行命令，默认捕获输出"""
    kwargs.setdefault("timeout", 300)
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


class NodeInstaller:
    """安装/更新 ComfyUI 自定义节点，支持版本控制"""

    def __init__(self, comfyui_dir: Path, *, force: bool = False, verbose: bool = False):
        self.custom_nodes_dir = comfyui_dir / "custom_nodes"
        self.force = force
        self.verbose = verbose
        self.runtime_python = self._detect_runtime_python()
        self.installed = 0
        self.updated = 0
        self.skipped = 0
        self.failed = 0

    def process(self, entry: NodeEntry) -> tuple[bool, str]:
        """处理单条节点条目"""
        node_dir = self.custom_nodes_dir / entry.repo_name
        self.custom_nodes_dir.mkdir(parents=True, exist_ok=True)

        if node_dir.exists():
            if self.force:
                shutil.rmtree(node_dir)
                return self._clone(entry, node_dir)

            if self._at_target_version(node_dir, entry.version):
                self._install_deps(node_dir, entry.repo_name)
                self.skipped += 1
                return True, f"跳过 (已在 {entry.version}): {entry.repo_name}"
            return self._update(entry, node_dir)

        return self._clone(entry, node_dir)

    @staticmethod
    def _detect_runtime_python() -> list[str]:
        """优先使用 ComfyUI 实际运行的虚拟环境 Python"""
        for candidate in ("/opt/venv/bin/python3", "/opt/venv/bin/python"):
            if Path(candidate).exists():
                return [candidate]
        return [sys.executable or "python3"]

    def _clone(self, entry: NodeEntry, node_dir: Path) -> tuple[bool, str]:
        """克隆节点仓库"""
        try:
            r = _run(["git", "clone", "--recursive", entry.url, str(node_dir)])
            if r.returncode != 0:
                self.failed += 1
                return False, f"克隆失败: {entry.repo_name} — {r.stderr[:200]}"

            ok, msg = self._checkout(entry, node_dir)
            if not ok:
                self.failed += 1
                return False, msg

            self._install_deps(node_dir, entry.repo_name)
            self.installed += 1
            return True, f"安装完成: {entry.repo_name} @ {entry.version}"

        except subprocess.TimeoutExpired:
            self.failed += 1
            return False, f"克隆超时: {entry.repo_name}"
        except Exception as e:
            self.failed += 1
            return False, f"克隆异常: {entry.repo_name} — {e}"

    def _update(self, entry: NodeEntry, node_dir: Path) -> tuple[bool, str]:
        """更新已有节点到目标版本"""
        try:
            _run(["git", "-C", str(node_dir), "fetch", "--tags", "--all"])
            ok, msg = self._checkout(entry, node_dir)
            if not ok:
                self.failed += 1
                return False, msg

            _run(["git", "-C", str(node_dir), "submodule", "update", "--init", "--recursive"])
            self._install_deps(node_dir, entry.repo_name)
            self.updated += 1
            return True, f"更新完成: {entry.repo_name} @ {entry.version}"

        except Exception as e:
            self.failed += 1
            return False, f"更新失败: {entry.repo_name} — {e}"

    def _checkout(self, entry: NodeEntry, node_dir: Path) -> tuple[bool, str]:
        """切换到目标版本"""
        d = str(node_dir)
        try:
            if entry.version == "nightly":
                # 默认分支最新
                r = _run(["git", "-C", d, "symbolic-ref", "refs/remotes/origin/HEAD"])
                branch = r.stdout.strip().split("/")[-1] if r.returncode == 0 else "main"
                _run(["git", "-C", d, "checkout", branch])
                _run(["git", "-C", d, "pull"])

            elif entry.version == "latest":
                # 最新 tag
                r = _run(["git", "-C", d, "describe", "--tags", "--abbrev=0"])
                if r.returncode == 0 and r.stdout.strip():
                    _run(["git", "-C", d, "checkout", r.stdout.strip()])
                else:
                    # 无 tag，fallback 到 nightly
                    return self._checkout(
                        NodeEntry(entry.url, "nightly", entry.index), node_dir
                    )
            else:
                # 指定 tag / commit / 分支
                r = _run(["git", "-C", d, "checkout", entry.version])
                if r.returncode != 0:
                    return False, f"checkout 失败: {entry.repo_name} @ {entry.version} — {r.stderr[:200]}"

            return True, ""
        except Exception as e:
            return False, f"checkout 异常: {entry.repo_name} — {e}"

    def _at_target_version(self, node_dir: Path, target: str) -> bool:
        """检查节点是否已在目标版本"""
        d = str(node_dir)
        try:
            if target == "nightly":
                return False  # 总是 pull

            if target == "latest":
                r1 = _run(["git", "-C", d, "describe", "--tags", "--exact-match"])
                if r1.returncode != 0:
                    return False
                current_tag = r1.stdout.strip()
                r2 = _run(["git", "-C", d, "describe", "--tags", "--abbrev=0"])
                return r2.returncode == 0 and current_tag == r2.stdout.strip()

            # 指定版本：比较 HEAD commit
            r_head = _run(["git", "-C", d, "rev-parse", "HEAD"])
            r_target = _run(["git", "-C", d, "rev-parse", target])
            if r_head.returncode == 0 and r_target.returncode == 0:
                return r_head.stdout.strip() == r_target.stdout.strip()
            return False
        except Exception:
            return False

    def _install_deps(self, node_dir: Path, name: str) -> None:
        """安装节点的 requirements.txt，然后运行 install.py（如果存在）"""
        req_file = node_dir / "requirements.txt"
        if req_file.exists():
            if self.verbose:
                print(f"    安装依赖: {name}")

            r = _run([
                *self.runtime_python, "-m", "pip", "install", "--no-cache-dir",
                "-r", str(req_file),
            ], timeout=600)
            if r.returncode != 0:
                print(f"    警告: {name} requirements 安装失败 (exit {r.returncode})")
                if r.stderr:
                    print(f"      stderr: {r.stderr[:300]}")

        # 运行 install.py（许多节点把依赖安装写在这里而非 requirements.txt）
        install_script = node_dir / "install.py"
        if install_script.exists():
            print(f"    运行 install.py: {name}")
            try:
                r = _run(
                    [*self.runtime_python, "install.py"],
                    timeout=300,
                    cwd=str(node_dir),
                )
                if r.returncode != 0:
                    print(f"    警告: {name} install.py 失败 (exit {r.returncode})")
                    if r.stderr:
                        print(f"      stderr: {r.stderr[:300]}")
            except Exception as e:
                print(f"    警告: {name} install.py 执行异常 — {e}")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def detect_comfyui_dir() -> Path:
    """自动检测 ComfyUI 目录"""
    for p in ["/comfyui", "/runpod-volume/ComfyUI", "/workspace/ComfyUI"]:
        if Path(p).exists():
            return Path(p)
    return Path("/comfyui")


def main() -> int:
    parser = argparse.ArgumentParser(description="按 config.yml 安装 ComfyUI 自定义节点")
    parser.add_argument("--config", type=Path, default=Path("config.yml"))
    parser.add_argument("--comfyui-dir", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true", help="只显示，不实际安装")
    parser.add_argument("--force", action="store_true", help="强制重新安装")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    comfyui_dir = args.comfyui_dir or detect_comfyui_dir()

    cfg = NodeConfigParser(args.config)
    entries = cfg.parse()

    if cfg.errors:
        for err in cfg.errors:
            print(f"  错误: {err}")
        return 1

    if cfg.warnings:
        for warn in cfg.warnings:
            print(f"  警告: {warn}")

    if not entries:
        print("config.yml 中没有节点条目，跳过")
        return 0

    print(f"配置: {args.config}")
    print(f"ComfyUI: {comfyui_dir}")
    print(f"节点数: {len(entries)}")
    print()

    if args.dry_run:
        print("DRY RUN\n")
        for entry in entries:
            print(f"  {entry.repo_name} @ {entry.version}")
            print(f"    {entry.url}")
        return 0

    installer = NodeInstaller(comfyui_dir, force=args.force, verbose=args.verbose)
    for entry in entries:
        ok, msg = installer.process(entry)
        print(f"  {'OK' if ok else 'FAIL'} {msg}")

    print()
    print(f"安装: {installer.installed}  更新: {installer.updated}  跳过: {installer.skipped}  失败: {installer.failed}")
    return 1 if installer.failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
