# Local services

`python dev.py up` starts application PostgreSQL, Temporal's separate PostgreSQL
server (with `temporal` and `temporal_visibility` databases), Temporal, and its UI.
Run `python dev.py check` for a database, namespace, and UI check. Use
`python dev.py down` to stop the stack without deleting the named data volumes.

The application connects to `localhost:55432` from the host or `app-db:5432`
from a Compose service. Temporal gRPC is `localhost:7233` from the host or
`temporal:7233` from Compose. The UI is at <http://localhost:8080>. Ports can
be changed in `infra/.env`; all published ports bind to host loopback.
`python dev.py tools operator namespace describe --namespace default` runs the
Temporal CLI within the Temporal container.

`infra/.env` is ignored and created from `.env.example` on the first `up`.
The example credentials are for local development only. Put provider/model
keys in separate ignored local configuration or a secret manager, never in
Compose, images, Git, or workflow payloads. This Compose file is a development
stack; Temporal's `auto-setup` is not a production upgrade plan. The first
private deployment needs a separate reviewed configuration and measured sizing.

`python dev.py verify` checks deterministic fixture regeneration, formatting,
lint, and tests. `python dev.py integration` also starts the stack, applies
numbered SQL migrations, loads the fixture, creates separate read-only market
and agent-table roles, and runs tests marked `synthetic_integration`.

- `backend/pyproject.toml` installs with `pip install -e './backend[dev]'`.
- `python -m market_eagle.ingestion.migrate` applies `database/migrations/*.sql`
  once with checksum verification using the application owner `DATABASE_URL`.
- The API and agent worker receive `DATABASE_URL` for read-only analytics and
  `AGENT_DATABASE_URL` for research state. The local agent role has no access to
  market tables. Production credentials must provide the same separation.
