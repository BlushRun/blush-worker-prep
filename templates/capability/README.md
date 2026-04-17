# blush-worker-__SLUG__

Managed from `blush-worker-prep`.

- run `uv run worker-prep validate --repo submodules/__SLUG__`
- run `uv run worker-prep hydrate-build --repo submodules/__SLUG__ --force`
- then run Docker from this repo directory
- keep only `worker.toml`, `config.yml`, `workflows/`, `req/`, `Dockerfile`, `docker-compose.yml`, `README.md`, `AGENTS.md`
