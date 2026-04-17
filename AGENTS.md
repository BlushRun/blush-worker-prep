# blush-worker-prep repo guide

- This is the only worker entry repo
- Capability repos are managed here under `submodules/`
- Shared CLI, runtime assets, and capability skeleton stay here
- Do not move shared logic into capability repos
- Disposable generated dirs: `submodules/*/.worker-build`, `submodules/*/volumes/output/runpod-local`
