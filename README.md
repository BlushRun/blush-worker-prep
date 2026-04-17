# blush-worker-prep

Worker work starts here.

- sync child repos: `uv run worker-prep sync-submodules --remote`
- validate one capability: `uv run worker-prep validate --repo submodules/flux2-klein-9b`
- hydrate shared runtime assets: `uv run worker-prep hydrate-build --repo submodules/flux2-klein-9b --force`
- then run Docker from `submodules/flux2-klein-9b/`
- local smoke: `uv run worker-prep smoke-local --repo submodules/flux2-klein-9b req/flux2-klein-9b-t2i.api.json`
- prep owns shared CLI, runtime assets, templates, and `submodules/`
- capability repos keep only `worker.toml`, `config.yml`, `workflows/`, `req/`, `Dockerfile`, `docker-compose.yml`, `README.md`, `AGENTS.md`
