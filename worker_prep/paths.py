from __future__ import annotations

import os
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent
RUNTIME_DIR = PROJECT_DIR / "runtime"
TEMPLATE_DIR = PROJECT_DIR / "templates" / "capability"


def resolve_repo_root() -> Path:
    override = os.environ.get("WORKER_PREP_REPO", "").strip()
    if override:
        return Path(override).resolve()
    return Path.cwd().resolve()
