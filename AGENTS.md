# blush-worker-prep repo guide

- This is the only worker entry repo
- Capability repos are managed here under `submodules/`
- Shared CLI, runtime assets, and capability skeleton stay here
- Do not move shared logic into capability repos
- Build and compose run from each capability repo directory
- Disposable generated dirs: `tmp/`, `submodules/*/volumes/output/runpod-local`
- Create new capability repos from here with `uv run worker-prep init-capability --target submodules/<slug> ...`; do not handcraft the skeleton
- Workflow-derived capability repos must use a `workflow-` prefix in repo slug, workflow filename, and req filenames
- Do not run `git init` in parallel with `init-capability`; generate the template first, then initialize git/remote on the finished repo
- When landing a new workflow repo, normalize exported placeholder inputs like `LoadImage.image` and transport names to stable filenames such as `input.png`, `source.png`, or `reference.png`
- Put workflow-specific param mapping in `req/*.params.spec.json`; shared workflow conversion bugs belong in `worker_prep/`, not in one capability repo
- Pin `nodes:` to a tag or commit whenever possible; use `latest` only when the upstream repo has neither a usable tag nor a commit policy you can pin
- Preferred new capability flow: init template -> add workflow/config/spec/smoke -> run `add-workflow`, `validate`, `hydrate-build`, `export-apollo` -> commit repo -> create/push remote -> add it back to `.gitmodules`
