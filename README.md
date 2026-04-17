# blush-worker-prep

`blush-worker-prep` is the main worker management repo. Capability repos stay light and are managed here as child projects.

## Scope

- host-side CLI: validate, export Apollo bundle, resolve nodes, local/remote smoke, workflow import, build hydration
- runtime assets copied into worker images: `pre-start.sh`, `apply_config.sh`, `install_nodes.py`, `sync-models.py`
- capability skeleton for bootstrapping a new repo

## Main model

- `blush-worker-prep` is the main repo
- capability repos live under this repo as child projects, typically in `submodules/`
- worker images build directly from the official `runpod/worker-comfyui:*` base image
- `worker-prep hydrate-build` copies shared runtime assets into a capability repo before image build
- no shared `blush-worker-runtime` image is required

## CLI

Run from the prep repo root:

```bash
uv run worker-prep sync-submodules --remote
uv run worker-prep validate --repo submodules/flux2-klein-9b
uv run worker-prep hydrate-build --repo submodules/flux2-klein-9b --force
uv run worker-prep export-apollo --repo submodules/flux2-klein-9b --provider-mode local
uv run worker-prep smoke-local --repo submodules/flux2-klein-9b submodules/flux2-klein-9b/req/flux2-klein-9b-t2i.api.json --dry-run
```

## Commands

- `validate`
- `export-apollo`
- `export-template`
- `resolve-nodes`
- `smoke-local`
- `smoke-remote`
- `add-workflow`
- `hydrate-build`
- `init-capability`

## Runtime assets

The `runtime/` directory contains the files that `worker-prep hydrate-build` copies into a capability repo's `.worker-build/` directory before image build. The source of truth is here, not in each capability repo.
