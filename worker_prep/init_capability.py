from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from ._worker_meta import WorkerMeta, render_env_file
from .paths import TEMPLATE_DIR


TEXT_TEMPLATE_FILES = (
    "worker.toml",
    ".env.local.example",
    ".gitignore",
    "AGENTS.md",
    "README.md",
    "Dockerfile",
    "docker-compose.yml",
    "config.yml",
    ".github/workflows/ci.yml",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Initialize a lightweight capability repo")
    parser.add_argument("--target", type=Path, default=Path("."), help="target directory")
    parser.add_argument("--slug", required=True, help="capability slug")
    parser.add_argument("--display-name", required=True, help="display name")
    parser.add_argument("--provider-key", required=True, help="provider key")
    parser.add_argument("--local-slot", required=True, type=int, help="local slot number")
    parser.add_argument("--registry", default="docker.io/blushrun", help="image registry")
    parser.add_argument(
        "--base-image",
        default="runpod/worker-comfyui:5.8.5-base",
        help="official base image",
    )
    parser.add_argument(
        "--prep-submodule-path",
        default="tools/blush-worker-prep",
        help="relative submodule path inside the capability repo",
    )
    parser.add_argument(
        "--prep-submodule-url",
        default="https://github.com/BlushRun/blush-worker-prep.git",
        help="submodule remote URL",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="allow writing into a non-empty target directory",
    )
    return parser.parse_args()


def copy_tree(src: Path, dst: Path) -> None:
    for child in src.iterdir():
        target = dst / child.name
        if child.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            copy_tree(child, target)
        else:
            shutil.copy2(child, target)


def replace_tokens(text: str, meta: WorkerMeta) -> str:
    replacements = {
        "__SLUG__": meta.slug,
        "__DISPLAY_NAME__": meta.display_name,
        "__PROVIDER_KEY__": meta.provider_key,
        "__LOCAL_SLOT__": str(meta.local_slot),
        "__REGISTRY__": meta.registry,
        "__BASE_IMAGE__": meta.base_image,
        "__PREP_SUBMODULE_PATH__": meta.prep_submodule_path,
        "__PREP_SUBMODULE_URL__": meta.prep_submodule_url,
        "__LOCAL_BASE_URL__": meta.local_base_url,
    }
    rendered = text
    for key, value in replacements.items():
        rendered = rendered.replace(key, value)
    return rendered


def main() -> int:
    args = parse_args()
    target = args.target.resolve()
    target.mkdir(parents=True, exist_ok=True)

    if any(target.iterdir()) and not args.force:
        raise SystemExit(f"target directory is not empty: {target} (use --force)")

    meta = WorkerMeta(
        slug=args.slug.strip(),
        display_name=args.display_name.strip(),
        registry=args.registry.strip(),
        base_image=args.base_image.strip(),
        prep_submodule_path=args.prep_submodule_path.strip(),
        prep_submodule_url=args.prep_submodule_url.strip(),
        provider_key=args.provider_key.strip(),
        local_slot=args.local_slot,
    )

    copy_tree(TEMPLATE_DIR, target)

    for relative in TEXT_TEMPLATE_FILES:
        path = target / relative
        rendered = replace_tokens(path.read_text(encoding="utf-8"), meta)
        path.write_text(rendered, encoding="utf-8")

    (target / ".env.local.example").write_text(render_env_file(meta), encoding="utf-8")

    print(target)
    print(f"next: git submodule add {meta.prep_submodule_url} {meta.prep_submodule_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
