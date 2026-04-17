# blush-worker-__SLUG__

`blush-worker-__SLUG__` is a lightweight capability repo. Shared tooling lives in the `__PREP_SUBMODULE_PATH__` submodule.

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
└─ __PREP_SUBMODULE_PATH__/
```

## Local workflow

```bash
git submodule update --init --recursive
Copy-Item .env.local.example .env.local
uv --directory __PREP_SUBMODULE_PATH__ run worker-prep validate --repo .
uv --directory __PREP_SUBMODULE_PATH__ run worker-prep export-apollo --repo . --provider-mode local
docker compose --env-file .env.local -f docker-compose.yml up --build -d
```

## Common commands

```bash
uv --directory __PREP_SUBMODULE_PATH__ run worker-prep validate --repo .
uv --directory __PREP_SUBMODULE_PATH__ run worker-prep resolve-nodes --repo .
uv --directory __PREP_SUBMODULE_PATH__ run worker-prep smoke-local --repo . req/__SLUG__.api.json --dry-run
uv --directory __PREP_SUBMODULE_PATH__ run worker-prep smoke-remote --repo . --smoke-file req/__SLUG__.smoke.remote.json --dry-run --base-url __LOCAL_BASE_URL__
```
