# blush-worker-prep

Worker work starts here.

- sync child repos: `uv run worker-prep sync-submodules --remote`
- validate one capability: `uv run worker-prep validate --repo submodules/flux2-klein-9b`
- hydrate shared runtime assets: `uv run worker-prep hydrate-build --repo submodules/flux2-klein-9b --force`
- local smoke: `uv run worker-prep smoke-local --repo submodules/flux2-klein-9b req/flux2-klein-9b-t2i.api.json`

Authoritative repo contract: [docs/worker-contract.md](/D:/echo/blush-space/blush-worker-prep/docs/worker-contract.md)
