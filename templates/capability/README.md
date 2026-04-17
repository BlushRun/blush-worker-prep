# blush-worker-__SLUG__

`blush-worker-__SLUG__` is a lightweight capability repo. It is intended to be managed from `blush-worker-prep`.

## Fixed values

- `provider_key = "__PROVIDER_KEY__"`
- `local_slot = __LOCAL_SLOT__`
- `local_base_url = __LOCAL_BASE_URL__`

## Layout

```text
.
├─ worker.toml
├─ Dockerfile
├─ docker-compose.yml
├─ config.yml
├─ workflows/
├─ req/
├─ docs/
└─ .worker-build/
```

## Managed workflow

```bash
cd ../blush-worker-prep
uv run worker-prep validate --repo submodules/__SLUG__
uv run worker-prep hydrate-build --repo submodules/__SLUG__ --force
uv run worker-prep export-apollo --repo submodules/__SLUG__ --provider-mode local
cd submodules/__SLUG__
Copy-Item .env.local.example .env.local
docker compose --env-file .env.local -f docker-compose.yml up --build -d
```

## Common commands

```bash
uv run worker-prep validate --repo submodules/__SLUG__
uv run worker-prep hydrate-build --repo submodules/__SLUG__ --force
uv run worker-prep resolve-nodes --repo submodules/__SLUG__
uv run worker-prep smoke-local --repo submodules/__SLUG__ submodules/__SLUG__/req/__SLUG__.api.json --dry-run
uv run worker-prep smoke-remote --repo submodules/__SLUG__ --smoke-file submodules/__SLUG__/req/__SLUG__.smoke.remote.json --dry-run --base-url __LOCAL_BASE_URL__
```
