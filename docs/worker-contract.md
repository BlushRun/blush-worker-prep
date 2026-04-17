# Worker Contract

## Entry

- All worker operations start in `blush-worker-prep`
- Sync child repos with `uv run worker-prep sync-submodules --remote`

## Prep owns

- shared CLI in `worker_prep/`
- shared runtime assets in `runtime/`
- capability skeleton in `templates/capability/`
- child capability repos in `submodules/`

## Capability repo keeps only

- `worker.toml`
- `config.yml`
- `workflows/`
- `req/`
- `Dockerfile`
- `docker-compose.yml`
- `README.md`
- `AGENTS.md`

## Capability repo must not keep

- `dev/`
- shared runtime scripts
- a prep submodule
- extra architecture docs

## Build flow

1. `uv run worker-prep hydrate-build --repo submodules/<slug> --force`
2. run Docker from that capability repo

Hydrated files live in `.worker-build/` and are generated.
