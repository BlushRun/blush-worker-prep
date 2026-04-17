# blush-worker-prep

Worker work starts here.

- sync child repos: `uv run worker-prep sync-submodules --remote`
- validate one capability: `uv run worker-prep validate --repo submodules/flux2-klein-9b`
- local build: `docker build -f submodules/flux2-klein-9b/Dockerfile .`
- local compose: `docker compose --env-file submodules/flux2-klein-9b/.env.local.example -f submodules/flux2-klein-9b/docker-compose.yml up --build -d`
- local smoke: `uv run worker-prep smoke-local --repo submodules/flux2-klein-9b req/flux2-klein-9b-t2i.api.json`
- prep owns shared CLI, runtime assets, templates, and `submodules/`
- capability repos keep only `worker.toml`, `config.yml`, `workflows/`, `req/`, `Dockerfile`, `docker-compose.yml`, `README.md`, `AGENTS.md`
