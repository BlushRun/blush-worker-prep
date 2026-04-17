from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .paths import resolve_repo_root


@dataclass(frozen=True)
class WorkerMeta:
    slug: str
    display_name: str
    registry: str
    base_image: str
    prep_submodule_path: str
    prep_submodule_url: str
    provider_key: str
    local_slot: int

    @property
    def compose_project(self) -> str:
        return f"bw-{self.slug}"

    @property
    def image_repository(self) -> str:
        return f"{self.registry.rstrip('/')}/blush-worker-{self.slug}"

    @property
    def local_image(self) -> str:
        return f"{self.image_repository}:local"

    @property
    def local_api_port(self) -> int:
        return 40000 + self.local_slot

    @property
    def local_comfyui_port(self) -> int:
        return 41000 + self.local_slot

    @property
    def local_jupyter_port(self) -> int:
        return 42000 + self.local_slot

    @property
    def local_portal_port(self) -> int:
        return 43000 + self.local_slot

    @property
    def local_base_url(self) -> str:
        return f"http://localhost:{self.local_api_port}"

    def env_map(self) -> dict[str, str]:
        return {
            "WORKER_SLUG": self.slug,
            "COMPOSE_PROJECT_NAME": self.compose_project,
            "LOCAL_IMAGE": self.local_image,
            "BASE_IMAGE": self.base_image,
            "LOCAL_API_PORT": str(self.local_api_port),
            "LOCAL_COMFYUI_PORT": str(self.local_comfyui_port),
            "LOCAL_JUPYTER_PORT": str(self.local_jupyter_port),
            "LOCAL_PORTAL_PORT": str(self.local_portal_port),
            "COMFY_LOG_LEVEL": "DEBUG",
            "NETWORK_VOLUME_DEBUG": "false",
        }


REQUIRED_KEYS = {
    "slug",
    "display_name",
    "registry",
    "base_image",
    "prep_submodule_path",
    "prep_submodule_url",
    "provider_key",
    "local_slot",
}


def parse_simple_toml(text: str) -> dict[str, object]:
    data: dict[str, object] = {}
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if "=" not in line:
            raise ValueError(f"invalid worker.toml line: {raw_line}")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            data[key] = value[1:-1]
            continue
        try:
            data[key] = int(value)
        except ValueError as exc:
            raise ValueError(f"unsupported worker.toml value for {key}: {value}") from exc
    return data


def load_worker_meta(path: Path | None = None) -> WorkerMeta:
    meta_path = path or (resolve_repo_root() / "worker.toml")
    if not meta_path.exists():
        raise ValueError(f"worker.toml not found: {meta_path}")

    data = parse_simple_toml(meta_path.read_text(encoding="utf-8"))
    missing = [key for key in sorted(REQUIRED_KEYS) if key not in data]
    if missing:
        raise ValueError(f"worker.toml missing fields: {', '.join(missing)}")

    slug = str(data["slug"]).strip()
    display_name = str(data["display_name"]).strip()
    registry = str(data["registry"]).strip()
    base_image = str(data["base_image"]).strip()
    prep_submodule_path = str(data["prep_submodule_path"]).strip()
    prep_submodule_url = str(data["prep_submodule_url"]).strip()
    provider_key = str(data["provider_key"]).strip()
    local_slot = int(data["local_slot"])

    if not slug:
        raise ValueError("worker.toml slug must not be empty")
    if not display_name:
        raise ValueError("worker.toml display_name must not be empty")
    if not registry:
        raise ValueError("worker.toml registry must not be empty")
    if not base_image:
        raise ValueError("worker.toml base_image must not be empty")
    if not prep_submodule_path:
        raise ValueError("worker.toml prep_submodule_path must not be empty")
    if not prep_submodule_url:
        raise ValueError("worker.toml prep_submodule_url must not be empty")
    if not provider_key:
        raise ValueError("worker.toml provider_key must not be empty")
    if local_slot <= 0:
        raise ValueError("worker.toml local_slot must be > 0")

    return WorkerMeta(
        slug=slug,
        display_name=display_name,
        registry=registry,
        base_image=base_image,
        prep_submodule_path=prep_submodule_path,
        prep_submodule_url=prep_submodule_url,
        provider_key=provider_key,
        local_slot=local_slot,
    )


def render_env_file(meta: WorkerMeta) -> str:
    lines = [
        "# Derived from worker.toml. Copy to .env.local before docker compose runs.",
    ]
    for key, value in meta.env_map().items():
        lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"
