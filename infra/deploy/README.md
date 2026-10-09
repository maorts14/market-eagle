# Private homelab deployment assets

This is the first implementation slice of [ADR 0001](../../knowledge-base/adr/0001-private-homelab-runtime.md). It provides image builds and Compose wiring for a single-host deployment. It does **not** initialize production databases, register Temporal schedules, configure Tailscale, start live collection, or deploy to `thelab`. The existing `infra/compose.yaml` remains the local development stack.

## Images and services

`Dockerfile.backend` builds one backend image for API, collection worker, agent worker, and application migrations. `Dockerfile.web` runs `npm ci` from the committed lockfile and builds both explorer and agent in API mode; it serves the bundle through Nginx. Both Dockerfiles pin their base images by digest and label the `SOURCE_REVISION`. Set that to the reviewed Git commit, tag each built application image with the same revision, then record and deploy its immutable image digest. The backend Python dependencies are currently ranges in `backend/pyproject.toml`; a dependency lock or reviewed image digest is required for reproducible rebuilds.

`compose.yaml` defines PostgreSQL, a non-`auto-setup` Temporal server, API, agent worker, and web gateway. Only the gateway publishes a default host port, and it binds `127.0.0.1`. Temporal UI is an optional operator profile with a separate loopback port. Collection is behind the `collection` profile and does not start in a default `up`. **Do not activate collection simply to test Compose.** The current worker has a process-local provider rate limiter, so this stack allows only one collection process.

The merged `003` PostgreSQL-store migration uses a read-only market `DATABASE_URL` and a separate `AGENT_DATABASE_URL` for conversation writes. Both API and agent worker receive these URLs and their narrowly scoped password files. The old `AGENT_STORE_PATH` SQLite file is not mounted or configured. The application migration and role grants must run before the API and agent start. This slice leaves application and worker code untouched.

## Host inputs and secret files

Copy `.env.example` to an **untracked file outside the repository** and replace every `reviewed-*` value. `NVME_DATA_DIR` must be an absolute path on the NVMe filesystem, with a pre-created `postgres/` subdirectory writable by the image's PostgreSQL UID. Check its resolved mount with `findmnt --target /var/lib/market-eagle` (or your selected path) before any `up`. Compose uses `create_host_path: false` so a missing directory fails rather than silently creating storage elsewhere. The HDD at `/srv/storage` is not used for active database files.

`SECRETS_DIR` is an absolute host directory outside Git. The expected files are:

| File | Format | Mounted into |
| --- | --- | --- |
| `postgres_admin_password` | PostgreSQL bootstrap password, one line | PostgreSQL |
| `temporal_db_password` | Password for `temporal_service`, one line | Temporal |
| `market_reader.pgpass` | `postgres:5432:market_eagle:market_eagle_reader:<password>` | API and agent |
| `app_ingest.pgpass` | `postgres:5432:market_eagle:app_ingest:<password>` | Collection |
| `agent_store.pgpass` | `postgres:5432:market_eagle:market_eagle_agent:<password>` | API and agent |
| `app_migrator.pgpass` | `postgres:5432:market_eagle:app_migrator:<password>` | Migration profile |
| `alpaca_key_id`, `alpaca_secret_key`, `fmp_key` | Provider keys, one value per file | Collection only |
| `openrouter_key` | Model key, one line | Agent only |

The backend entrypoint copies its mounted `.pgpass` lines into one private `0600` file before starting Python because libpq rejects a broadly readable password file. It also bridges mounted provider/model keys into the environment expected by the current worker code. Temporal 1.27 likewise requires `POSTGRES_PWD` in its environment; `temporal-entrypoint.sh` reads its isolated secret mount. These are compatibility bridges, not a claim that the running processes never hold secrets in memory or environment. Do not print resolved secrets with `docker compose config`, `docker inspect`, shell tracing, or logs. File ownership must let the intended container user read its own mount.

The database roles and three databases (`market_eagle`, `temporal`, `temporal_visibility`) are **prerequisites**. This slice does not create them. The Temporal schemas must be installed by a version-matched, reviewed bootstrap before the server can start. `migrate-app` is an explicit one-shot application migration service after the database/role bootstrap. There is no automatic `auto-setup` or implicit schema migration on container restart. Temporal namespace and schedule bootstrap remain separate implementation handoffs in ADR 0001.

## Configuration and local dry-run

From the repository root, these commands validate the rendering and build images locally; they do not start services or call providers:

```sh
docker compose --env-file infra/deploy/.env.example -f infra/deploy/compose.yaml config --quiet
docker compose --env-file infra/deploy/.env.example -f infra/deploy/compose.yaml build api web
```

For a real host review, use the private env file instead of `.env.example`, then inspect `docker compose ... config --format json` without sharing its output. Confirm that PostgreSQL, Temporal gRPC, API, and workers have no published ports; only web (and opt-in Temporal UI) bind loopback. Confirm `postgres` resolves to the NVMe path and the generated frontend has `VITE_EXPLORER_MODE=api` and `VITE_AGENT_MODE=api`. `docker compose build` may fetch pinned base images and package dependencies; it does not deploy them.

Before an actual `up`, the lead must approve the database/Temporal schema bootstrap, service-specific grants for migration `003`, a real source/feed/basis, a model key, namespace/schedule setup, Tailscale Serve and owner ACL, readiness checks beyond the current API liveness endpoint, and a failure/restart drill. The first private deployment deliberately has **no backup or restore process**. A host/disk loss can erase application, agent, and Temporal state; backups become a later gate before important retained research or trader access.
