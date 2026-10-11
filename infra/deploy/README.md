# Private homelab deployment assets

This implements the private runtime and reviewed bootstrap from [ADR 0001](../../knowledge-base/adr/0001-private-homelab-runtime.md). It does **not** register Temporal schedules, configure Tailscale, start live collection, or deploy to `thelab`. The existing `infra/compose.yaml` remains the local development stack.

## Images and services

`Dockerfile.backend` builds one backend image for API, collection worker, agent worker, and application migrations. `Dockerfile.web` runs `npm ci` from the committed lockfile and builds both explorer and agent in API mode; it serves the bundle through Nginx. Both Dockerfiles pin their base images by digest and label the `SOURCE_REVISION`. Set that to the reviewed Git commit, tag each built application image with the same revision, then record and deploy its immutable image digest. The backend Python dependencies are currently ranges in `backend/pyproject.toml`; a dependency lock or reviewed image digest is required for reproducible rebuilds.

`compose.yaml` defines PostgreSQL, a non-`auto-setup` Temporal server, API, agent worker, and web gateway. Only the gateway publishes a default host port, and it binds `127.0.0.1`. Temporal UI is an optional operator profile with a separate loopback port. Collection is behind the `collection` profile and does not start in a default `up`. **Do not activate collection simply to test Compose.** The current worker has a process-local provider rate limiter, so this stack allows only one collection process. Long-running containers use Docker's `json-file` driver with five 10 MiB files each; this bounds local container logs, but it is not a metrics or alerting system.

The `003` PostgreSQL-store migration uses a read-only market `DATABASE_URL` and a separate `AGENT_DATABASE_URL` for conversation writes. Both API and agent worker receive these URLs and their narrowly scoped password files. The old `AGENT_STORE_PATH` SQLite file is not mounted or configured. The `004` Alpaca preparation and `005` private sample tables are included in the ingestion grants.

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

## Reviewed bootstrap and operator order

The maintenance profile contains explicit, repeatable one-shot jobs. It creates `market_eagle`, `temporal`, and `temporal_visibility`, the corresponding login roles, the five application migrations, service-specific grants, both Temporal schemas, and the `market-eagle-private` namespace. Temporal schema tooling is pinned to the same server version (`1.27.2`). The namespace has seven-day closed-workflow retention. Re-running each job preserves existing application and workflow data; migrations verify checksums. A database with an unexpected owner stops bootstrap for operator review. Bootstrap does not register a schedule or call a market-data provider.

After reviewing the release images, credentials, NVMe mount, and the exact command arguments, run these commands **in order** with a private env file outside Git. From the repository root in a POSIX shell:

```sh
ENV_FILE=/path/to/private.env
compose() { docker compose --env-file "$ENV_FILE" -f infra/deploy/compose.yaml "$@"; }
compose up -d postgres
compose --profile maintenance run --rm bootstrap-db
compose --profile maintenance run --rm migrate-app
compose --profile maintenance run --rm bootstrap-grants
compose --profile maintenance run --rm bootstrap-temporal
compose up -d temporal
compose --profile maintenance run --rm bootstrap-namespace
compose up -d api agent web
compose --profile maintenance run --rm verify-pollers
```

`bootstrap-db` sets or rotates passwords from the mounted secret files, creates databases with `app_migrator` or `temporal_service` as owner, and removes public database access. `migrate-app` applies `001` through `005` as the application owner. `bootstrap-grants` resets runtime-role table and sequence privileges, then grants the reader only market projections, the agent only its conversation tables and identity sequences, and ingestion only market/catalog/preparation/sample tables plus the selected-bar view. Run `bootstrap-grants` after any future migration that adds runtime objects. The maintenance jobs must finish successfully before the runtime is started. They are not normal startup dependencies and never run automatically on container restart.

The API keeps `/api/v1/health` for process liveness. `/api/v1/ready` checks read access to the market view, agent-store access, and a Temporal namespace RPC. Compose uses readiness for its API healthcheck and waits for it before starting the web gateway. A failed check returns HTTP 503 without credentials or driver diagnostics. Temporal's own Compose healthcheck only checks its listener; API readiness provides the dependency check.

`verify-pollers` makes read-only Temporal RPCs. It waits up to one minute for recent (within 60 seconds) workflow and activity polls on `market-eagle-agent`, then fails with the missing queue names. It starts Temporal if necessary but does not start either worker. After collection has been deliberately enabled and its worker started, run `compose --profile maintenance run --rm -e CHECK_COLLECTION=1 verify-pollers` to include `market-backfill`, `market-session`, and `market-catalog`. A successful process start alone does not prove these queues are being polled. This check does not schedule a workflow or call a provider.

For a dependency-recovery drill on a disposable or approved private deployment, record the initial API readiness and `verify-pollers` result; stop Temporal, confirm `/api/v1/ready` returns 503 while `/api/v1/health` remains 200, restart Temporal, and rerun both checks. Also restart the API and agent containers and verify they return to healthy/polling states. Do not use this drill against an active collection run without a reviewed interruption plan. Record the result and any worker reconnection failure in the release log.

## Configuration and local dry-run

From the repository root, these commands validate the rendering and build images locally; they do not start services or call providers:

```sh
docker compose --env-file infra/deploy/.env.example -f infra/deploy/compose.yaml config --quiet
docker compose --env-file infra/deploy/.env.example -f infra/deploy/compose.yaml build api web
```

For a real host review, use the private env file instead of `.env.example`, then inspect `docker compose ... config --format json` without sharing its output. Confirm that PostgreSQL, Temporal gRPC, API, and workers have no published ports; only web (and opt-in Temporal UI) bind loopback. Confirm `postgres` resolves to the NVMe path and the generated frontend has `VITE_EXPLORER_MODE=api` and `VITE_AGENT_MODE=api`. `docker compose build` may fetch pinned base images and package dependencies; it does not deploy them.

Before an actual host deployment, the lead must approve a real source/feed/basis, model key, schedule setup, Tailscale Serve and owner ACL, and a failure/restart drill. The first private deployment deliberately has **no backup or restore process**. A host/disk loss can erase application, agent, and Temporal state; backups become a later gate before important retained research or trader access.
