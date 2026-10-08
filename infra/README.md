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

`python dev.py verify` checks deterministic fixture regeneration and, once the
backend exists, runs its formatting, lint, and tests. `python dev.py integration`
also starts the stack, applies Alembic migrations, and runs tests marked
`synthetic_integration`. The backend handoff contract is:

- `backend/pyproject.toml` installs with `pip install -e './backend[dev]'` and
  provides `ruff`, `pytest`, and `alembic`.
- `backend/alembic.ini` accepts `DATABASE_URL` for migration configuration.
- Backend synthetic tests use `@pytest.mark.synthetic_integration` and load
  the committed fixture into the application database. They must exercise the
  explorer windows and typed gain-plus-volume request in the v1 contract.

CI runs the service and fixture checks now. The backend steps activate when
`backend/pyproject.toml` is added; until then the synthetic API gate cannot run.
