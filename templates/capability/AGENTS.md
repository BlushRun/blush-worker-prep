# capability repo guide

## Repo role

- Keep this repo light
- Keep only capability assets and committed build files here
- Shared host scripts and runtime bootstrap are hydrated from `blush-worker-prep`

## Keep here

- `worker.toml`
- `config.yml`
- `workflows/`
- `req/`
- `docs/`
- `Dockerfile`
- `docker-compose.yml`
- `.github/workflows/ci.yml`

## Do not re-add

- a large `dev/` toolchain
- duplicated runtime scripts
- a prep submodule inside the capability repo
- a shared runtime image dependency
