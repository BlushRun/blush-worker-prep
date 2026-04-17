# blush-worker-prep repo guide

## Repo role

- Own the shared worker CLI and runtime assets
- Do not carry capability-specific `config.yml`, `workflows/`, or `req/` assets
- Keep capability repos light; shared logic belongs here

## Files that matter

- `worker_prep/cli.py`
- `worker_prep/_worker_meta.py`
- `worker_prep/_apollo.py`
- `worker_prep/validate.py`
- `worker_prep/runpod_local.py`
- `worker_prep/runpod_remote.py`
- `runtime/`
- `templates/capability/`

## Rules

- Changes here must stay generic across capability repos
- If a behavior only applies to one worker, do not hardcode it here
- Runtime assets copied into Docker images should stay minimal and compatible with the official `runpod/worker-comfyui` base image
