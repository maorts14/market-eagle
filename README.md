# Market Eagle

This repository is the first implementation stage of Market Eagle. The
[knowledge base](knowledge-base/README.md) contains the accepted product and
architecture contracts; the committed `fixtures/synthetic-v1/` is fictional
test data.

## Local development

Install Python 3.12+ and Docker with Compose, then run:

```text
python dev.py up
```

This creates an ignored `infra/.env` from local development defaults, starts
PostgreSQL and Temporal, and checks both databases, Temporal's default
namespace, and the UI. The application database is at `localhost:55432`,
Temporal gRPC at `localhost:7233`, and the UI at
<http://localhost:8080>. Adjust the loopback ports in `infra/.env` if needed.

```text
python dev.py check        # repeat health checks
python dev.py verify       # fixture, formatting, and unit checks
python dev.py integration  # services, migrations, and synthetic API gate
python dev.py down         # stop without deleting data
```

The backend has not been merged yet, so `verify` currently validates the
fixture and `integration` currently validates the local services. Backend
checks activate with `backend/pyproject.toml`; see [the infrastructure
handoff](infra/README.md) for the required commands and test marker.

The local Compose stack is for development. It contains no provider or model
credentials and publishes services to host loopback. The first private
homelab deployment is a later reviewed stage after the application runtime
and measured capacity are available.
