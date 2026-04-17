# blush-worker-__SLUG__

Managed from `blush-worker-prep`.

- prepare from prep root: `uv run worker-prep validate --repo submodules/__SLUG__` then `uv run worker-prep hydrate-build --repo submodules/__SLUG__ --force`
- start here: `docker compose --env-file .env.local.example -f docker-compose.yml up --build -d`
- declare workflow-specific param mapping in `req/*.params.spec.json` when generic extraction is not enough
- keep only `.worker-build/`, `worker.toml`, `config.yml`, `workflows/`, `req/`, `Dockerfile`, `docker-compose.yml`, `README.md`, `AGENTS.md`
