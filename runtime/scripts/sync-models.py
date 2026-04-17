# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml", "huggingface-hub", "hf-transfer", "requests"]
# ///
"""
按 config.yml 同步模型到指定目录。

启动时由 pre-start.sh 调用，也可手动运行：
  uv run scripts/sync-models.py [--config config.yml] [--models-dir path]
  uv run scripts/sync-models.py --dry-run
  uv run scripts/sync-models.py --force
  uv run scripts/sync-models.py --parallel 3

下载策略（按优先级）：
  1. HuggingFace URL -> hf_hub + hf_transfer（100-200MB/s）
  2. 其他 HTTPS URL -> requests 多线程分块下载
  3. Fallback -> urllib 单线程
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import requests as req_lib
import yaml

# 启用 hf_transfer 加速
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"
from huggingface_hub import hf_hub_download  # noqa: E402

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

CHUNK_SIZE = 8 * 1024 * 1024  # 8MB
PARALLEL_THREADS = 8

VALID_DESTINATIONS = frozenset({
    "checkpoints", "clip", "clip_vision", "configs", "controlnet",
    "diffusion_models", "embeddings", "loras", "upscale_models", "vae",
    "sams", "detection", "text_encoders", "unet", "style_models", "hypernetworks",
})

VALID_EXTENSIONS = frozenset({
    ".safetensors", ".ckpt", ".pt", ".pth", ".bin",
    ".onnx", ".pb", ".yaml", ".json",
})

HF_URL_PATTERN = re.compile(
    r"https://huggingface\.co/([^/]+/[^/]+)/resolve/([^/]+)/(.+?)(?:\?.*)?$"
)


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModelEntry:
    """config.yml 中的一条模型声明"""
    url: str
    destination: str
    filename: str
    optional: bool = False
    index: int = 0


# ---------------------------------------------------------------------------
# 配置解析
# ---------------------------------------------------------------------------

@dataclass
class ConfigParser:
    """解析 config.yml，提取模型条目并校验"""
    file_path: Path
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def parse(self) -> list[ModelEntry]:
        if not self.file_path.exists():
            self.errors.append(f"配置文件不存在: {self.file_path}")
            return []

        try:
            config = yaml.safe_load(self.file_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            self.errors.append(f"YAML 解析错误: {e}")
            return []

        if not config:
            self.warnings.append("配置文件为空")
            return []

        models_raw = config.get("models") or []
        if not isinstance(models_raw, list):
            self.errors.append("'models' 必须是列表")
            return []

        entries: list[ModelEntry] = []
        for idx, item in enumerate(models_raw, 1):
            if not isinstance(item, dict):
                self.warnings.append(f"条目 {idx}: 不是字典，跳过")
                continue

            url = item.get("url", "")
            destination = item.get("destination", "")
            filename = item.get("filename", "")
            optional = item.get("optional", False)

            if not url:
                self.warnings.append(f"条目 {idx}: 缺少 url")
                continue
            if not destination:
                self.warnings.append(f"条目 {idx}: 缺少 destination")
                continue
            if destination not in VALID_DESTINATIONS:
                self.errors.append(
                    f"条目 {idx}: 无效 destination '{destination}'，"
                    f"可选: {', '.join(sorted(VALID_DESTINATIONS))}"
                )
                continue

            if filename and not isinstance(filename, str):
                self.warnings.append(f"条目 {idx}: filename 不是字符串，跳过")
                continue

            filename = filename.strip()
            if not filename:
                filename = self._extract_filename(url)
            if not filename:
                self.warnings.append(
                    f"条目 {idx}: 无法从 URL 提取文件名，请显式填写 filename: {url}"
                )
                continue

            ext = Path(filename).suffix.lower()
            if ext not in VALID_EXTENSIONS:
                self.warnings.append(f"条目 {idx}: 扩展名 '{ext}' 不常见: {filename}")

            entries.append(ModelEntry(
                url=url, destination=destination,
                filename=filename, optional=optional, index=idx,
            ))

        return entries

    @staticmethod
    def _extract_filename(url: str) -> Optional[str]:
        parsed = urllib.parse.urlparse(url)
        name = Path(parsed.path).name
        if name and "." in name:
            return name
        return None


# ---------------------------------------------------------------------------
# 下载器
# ---------------------------------------------------------------------------

class ModelDownloader:
    """按优先级策略下载模型文件"""

    def __init__(self, base_dir: Path, *, force: bool = False, verbose: bool = False):
        self.base_dir = base_dir
        self.force = force
        self.verbose = verbose
        self.downloaded = 0
        self.skipped = 0
        self.failed = 0

    def process(self, entry: ModelEntry) -> tuple[bool, str]:
        """处理单条模型条目，返回 (成功, 消息)"""
        dest = self.base_dir / entry.destination / entry.filename
        dest.parent.mkdir(parents=True, exist_ok=True)

        # 已存在检查
        if dest.exists() and not self.force:
            size_mb = dest.stat().st_size / 1e6
            self.skipped += 1
            return True, f"跳过 (已存在, {size_mb:.0f} MB): {entry.destination}/{entry.filename}"

        # 下载
        try:
            self._download(entry.url, dest)
            size_mb = dest.stat().st_size / 1e6
            self.downloaded += 1
            return True, f"下载完成 ({size_mb:.0f} MB): {entry.destination}/{entry.filename}"
        except Exception as e:
            self.failed += 1
            msg = f"下载失败: {entry.destination}/{entry.filename} - {e}"
            if entry.optional:
                return True, f"[可选] {msg}"
            return False, msg

    def _download(self, url: str, dest: Path) -> None:
        """按优先级尝试下载"""
        # 1. HuggingFace 加速
        if self._try_hf(url, dest):
            return
        # 2. 多线程分块
        if self._try_parallel(url, dest):
            return
        # 3. 单线程 fallback
        self._download_simple(url, dest)

    def _try_hf(self, url: str, dest: Path) -> bool:
        """HuggingFace URL -> hf_hub + hf_transfer"""
        match = HF_URL_PATTERN.match(url)
        if not match:
            return False

        repo_id, revision, filename = match.groups()
        if self.verbose:
            print(f"    HF 加速: {repo_id} / {filename}")

        try:
            downloaded_path = hf_hub_download(
                repo_id=repo_id,
                revision=revision,
                filename=filename,
                local_dir=str(dest.parent),
            )
            dl = Path(downloaded_path)
            if dl != dest and dl.exists():
                dl.rename(dest)
            return True
        except Exception as e:
            if self.verbose:
                print(f"    HF 失败，回退: {e}")
            return False

    def _try_parallel(self, url: str, dest: Path) -> bool:
        """多线程分块下载"""
        try:
            head = req_lib.head(url, allow_redirects=True, timeout=10)
            if head.headers.get("Accept-Ranges") == "none":
                return False

            total = int(head.headers.get("Content-Length", 0))
            if total == 0:
                return False

            chunk_size = total // PARALLEL_THREADS
            tmp_dir = dest.parent / f".{dest.name}.chunks"
            tmp_dir.mkdir(exist_ok=True)

            if self.verbose:
                print(f"    多线程: {total / 1e9:.1f} GB, {PARALLEL_THREADS} 线程")

            def fetch_chunk(i: int, start: int, end: int) -> bool:
                chunk_file = tmp_dir / f"chunk_{i}"
                try:
                    r = req_lib.get(
                        url, headers={"Range": f"bytes={start}-{end}"},
                        stream=True, timeout=300,
                    )
                    r.raise_for_status()
                    with open(chunk_file, "wb") as f:
                        for data in r.iter_content(chunk_size=CHUNK_SIZE):
                            f.write(data)
                    return True
                except Exception:
                    return False

            with ThreadPoolExecutor(max_workers=PARALLEL_THREADS) as pool:
                futures = []
                for i in range(PARALLEL_THREADS):
                    s = i * chunk_size
                    e = s + chunk_size - 1 if i < PARALLEL_THREADS - 1 else total - 1
                    futures.append(pool.submit(fetch_chunk, i, s, e))

                done = 0
                for future in as_completed(futures):
                    if not future.result():
                        shutil.rmtree(tmp_dir, ignore_errors=True)
                        return False
                    done += 1
                    print(f"\r    进度: {done}/{PARALLEL_THREADS} 块", end="", flush=True)
                print()

            # 合并
            with open(dest, "wb") as out:
                for i in range(PARALLEL_THREADS):
                    with open(tmp_dir / f"chunk_{i}", "rb") as chunk:
                        out.write(chunk.read())
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return True

        except Exception:
            return False

    @staticmethod
    def _download_simple(url: str, dest: Path) -> None:
        """单线程 fallback"""
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "blush-worker/1.0"})
            with urllib.request.urlopen(request) as resp, open(tmp, "wb") as f:
                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                while chunk := resp.read(CHUNK_SIZE):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        pct = downloaded / total * 100
                        print(
                            f"\r    进度: {downloaded / 1e9:.1f} / {total / 1e9:.1f} GB ({pct:.0f}%)",
                            end="", flush=True,
                        )
                if total > 0:
                    print()
            tmp.rename(dest)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def detect_models_dir() -> Path:
    """自动检测模型目标目录"""
    if Path("/runpod-volume/models").exists():
        return Path("/runpod-volume/models")
    if Path("/workspace/models").exists():
        return Path("/workspace/models")
    script_dir = Path(__file__).resolve().parent
    return script_dir.parent / "volumes" / "runpod-volume" / "models"


def main() -> int:
    parser = argparse.ArgumentParser(description="按 config.yml 同步模型")
    parser.add_argument("--config", type=Path, default=Path("config.yml"),
                        help="配置文件路径 (默认: ./config.yml)")
    parser.add_argument("--models-dir", type=Path, default=None,
                        help="模型目标目录 (默认: 自动检测)")
    parser.add_argument("--dry-run", action="store_true",
                        help="只显示会下载什么，不实际下载")
    parser.add_argument("--force", action="store_true",
                        help="强制重新下载已存在的文件")
    parser.add_argument("--parallel", type=int, default=1,
                        help="并行下载多个模型 (默认: 1)")
    parser.add_argument("--verbose", action="store_true",
                        help="显示详细输出")
    args = parser.parse_args()

    models_dir = args.models_dir or detect_models_dir()

    # 解析配置
    cfg = ConfigParser(args.config)
    entries = cfg.parse()

    if cfg.errors:
        for err in cfg.errors:
            print(f"  错误: {err}")
        return 1

    if cfg.warnings:
        for warn in cfg.warnings:
            print(f"  警告: {warn}")

    if not entries:
        print("config.yml 中没有模型条目，跳过")
        return 0

    print(f"配置: {args.config}")
    print(f"目标: {models_dir}")
    print(f"模型数: {len(entries)}")
    print()

    # dry-run
    if args.dry_run:
        print("DRY RUN - 不会实际下载\n")
        for entry in entries:
            tag = "[可选]" if entry.optional else "[必须]"
            print(f"  {tag} {entry.url}")
            print(f"       -> {models_dir / entry.destination / entry.filename}")
        return 0

    # 下载
    downloader = ModelDownloader(models_dir, force=args.force, verbose=args.verbose)

    if args.parallel > 1:
        with ThreadPoolExecutor(max_workers=args.parallel) as pool:
            futures = {pool.submit(downloader.process, e): e for e in entries}
            for future in as_completed(futures):
                ok, msg = future.result()
                print(f"  {'OK' if ok else 'FAIL'} {msg}")
    else:
        for entry in entries:
            ok, msg = downloader.process(entry)
            print(f"  {'OK' if ok else 'FAIL'} {msg}")

    # 汇总
    print()
    print(f"下载: {downloader.downloaded}  跳过: {downloader.skipped}  失败: {downloader.failed}")

    return 1 if downloader.failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
