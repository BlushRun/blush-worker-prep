# blush-worker-__SLUG__

Managed from `blush-worker-prep`.

- run `uv run worker-prep validate --repo submodules/__SLUG__`
- run `docker build -f submodules/__SLUG__/Dockerfile .`
- run `docker compose --env-file submodules/__SLUG__/.env.local.example -f submodules/__SLUG__/docker-compose.yml up --build -d`
- keep only `worker.toml`, `config.yml`, `workflows/`, `req/`, `Dockerfile`, `docker-compose.yml`, `README.md`, `AGENTS.md`
