# blush-worker-prep

Worker work starts here.

- sync child repos: `uv run worker-prep sync-submodules --remote`
- prepare one capability: `uv run worker-prep validate --repo submodules/flux2-klein-9b` then `uv run worker-prep hydrate-build --repo submodules/flux2-klein-9b --force`
- start locally: `cd submodules/flux2-klein-9b` then `docker compose --env-file .env.local.example -f docker-compose.yml up --build -d`
- local smoke: `uv run worker-prep smoke-local --repo submodules/flux2-klein-9b req/flux2-klein-9b-t2i.api.json`
- workflow-specific param mapping lives with each capability under `req/*.params.spec.json`
- pin `nodes:` to a tag or commit whenever possible; use `latest` only when pinning is not available
- prep owns shared CLI, runtime assets, templates, and `submodules/`
- capability repos keep only `.worker-build/`, `worker.toml`, `config.yml`, `workflows/`, `req/`, `Dockerfile`, `docker-compose.yml`, `README.md`
