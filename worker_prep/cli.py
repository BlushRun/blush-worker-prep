from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path


COMMANDS: dict[str, str] = {
    "add-workflow": "worker_prep.add_workflow",
    "export-apollo": "worker_prep.export_apollo",
    "export-template": "worker_prep.export_template",
    "hydrate-build": "worker_prep.hydrate_build",
    "init-capability": "worker_prep.init_capability",
    "resolve-nodes": "worker_prep.resolve_nodes",
    "smoke-local": "worker_prep.runpod_local",
    "smoke-remote": "worker_prep.runpod_remote",
    "sync-submodules": "worker_prep.sync_submodules",
    "validate": "worker_prep.validate",
}


def usage() -> str:
    lines = [
        "worker-prep <command> [--repo PATH] [args...]",
        "",
        "Commands:",
    ]
    for name in sorted(COMMANDS):
        lines.append(f"  {name}")
    return "\n".join(lines)


def discover_capability_repo(start: Path) -> Path | None:
    for candidate in (start, *start.parents):
        if (candidate / "worker.toml").exists():
            return candidate
    return None


def normalize_repo_path(repo: Path) -> Path:
    if repo.is_absolute():
        return repo.resolve()

    cwd = Path.cwd().resolve()
    direct = (cwd / repo).resolve()
    if (direct / "worker.toml").exists():
        return direct

    discovered = discover_capability_repo(cwd)
    if discovered is not None:
        if repo == Path("."):
            return discovered
        nested = (discovered / repo).resolve()
        if (nested / "worker.toml").exists():
            return nested

    return direct


def extract_repo_arg(argv: list[str]) -> tuple[Path, list[str]]:
    repo = Path(".")
    filtered: list[str] = []
    index = 0
    while index < len(argv):
        item = argv[index]
        if item == "--repo":
            if index + 1 >= len(argv):
                raise SystemExit("--repo requires a value")
            repo = Path(argv[index + 1])
            index += 2
            continue
        if item.startswith("--repo="):
            repo = Path(item.split("=", 1)[1])
            index += 1
            continue
        filtered.append(item)
        index += 1
    return normalize_repo_path(repo), filtered


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    repo_root, args = extract_repo_arg(args)
    if not args or args[0] in {"-h", "--help", "help"}:
        print(usage())
        return 0

    command = args[0]
    module_name = COMMANDS.get(command)
    if module_name is None:
        print(f"unknown command: {command}", file=sys.stderr)
        print(usage(), file=sys.stderr)
        return 1

    os.environ["WORKER_PREP_REPO"] = str(repo_root)
    sys.argv = [f"worker-prep {command}", *args[1:]]
    module = importlib.import_module(module_name)
    return int(module.main())


if __name__ == "__main__":
    raise SystemExit(main())
