# blush-worker-prep

`blush-worker-prep` is the shared worker toolchain repo. Capability repos stay light and consume it as a git submodule.

## Scope

- host-side CLI: validate, export Apollo bundle, resolve nodes, local/remote smoke, workflow import
- runtime assets copied into worker images: `pre-start.sh`, `apply_config.sh`, `install_nodes.py`, `sync-models.py`
- capability skeleton for bootstrapping a new repo

## Main model

- capability repo is the main repo
- `blush-worker-prep` is pinned as a submodule, usually at `tools/blush-worker-prep`
- worker images build directly from the official `runpod/worker-comfyui:*` base image
- no shared `blush-worker-runtime` image is required

## CLI

Run from a capability repo:

```bash
uv --directory tools/blush-worker-prep run worker-prep validate --repo .
uv --directory tools/blush-worker-prep run worker-prep export-apollo --repo . --provider-mode local
uv --directory tools/blush-worker-prep run worker-prep smoke-local --repo . req/my-worker.api.json --dry-run
uv --directory tools/blush-worker-prep run worker-prep smoke-remote --repo . --smoke-file req/my-worker.smoke.remote.json --dry-run --endpoint-id demo
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

The `runtime/` directory contains the files that capability repos copy into their Docker image. The source of truth is here, not in each capability repo.
