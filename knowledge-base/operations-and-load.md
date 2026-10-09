# Operations, capacity, and growth

The concrete private-host deployment proposal and implementation acceptance checks are in [ADR 0001](adr/0001-private-homelab-runtime.md). It preserves the no-backup decision below.

Status: architecture sizing proposal using the 2026-10-06 homelab inventory. Provider behavior and actual service load remain to be measured.

## Measured homelab inventory

The read-only script was run over Tailscale on `thelab` as `cook` on 2026-10-06. It reported Ubuntu 24.04.5 LTS, Intel Core i5-10505 (6 cores / 12 logical CPUs), 15 GiB RAM (about 14 GiB available while idle), 4 GiB swap, and a 232 GB ext4 root filesystem on NVMe with about 214 GB free. A separate 3.6 TB ext4 HDD is mounted at `/srv/storage` with about 3.4 TB free. Docker, Compose, kubectl, and k3s were not installed; Tailscale was installed. These are observations, not resource reservations or a load test.

**Placement proposal:** keep PostgreSQL application and Temporal persistence, database WAL, and active query work on NVMe. The HDD is available but is not assigned a backup role in the first private deployment. Do not put Temporal persistence on the HDD merely because it has more space. Exact PostgreSQL/Temporal memory and worker concurrency should follow a deployed baseline measurement.

## Workload envelope

- Five years × roughly 252 sessions × about 500 tracked securities yields about **630,000 daily bars** plus comparison closes and revisions. The accepted backfill topology is one Temporal workflow with roughly 100 default five-stock/five-year activities, plus narrower repair activities when needed. Request `limit=10000`; actual page count, activity concurrency, and rate behavior require a probe.
- One cumulative current-day candle per stock, refreshed roughly hourly through regular trading hours, yields a few thousand upserts per session. Session timing and half days come from an exchange calendar.
- One initial user, later design partners. No latency or concurrency SLO has been accepted. Measure p50/p95 analytical latency, provider lag, workflow queue delay, DB CPU/IO, and memory before sizing workers.

## Load control

| Pressure | Control | Scale trigger |
| --- | --- | --- |
| Provider rate/latency | Shared token bucket, bounded fetch concurrency, priority refresh queue, 429 backoff | Persistent refresh lag or backfill timeline misses |
| PostgreSQL analytical reads | Set-based endpoint query, indexes, statement timeout, connection pool, query-plan inspection; optional cache by snapshot/window/basis/metric version | p95 latency or DB saturation under actual users |
| PostgreSQL writes | Batch upserts, idempotency keys, short transactions; revisions separate from current pointer | Write lag/IO pressure |
| Temporal histories | One backfill workflow with small group-activity inputs/results; keep provider pages out of history and use continue-as-new only if measured history growth requires it | History growth or workflow task latency |
| Agent work | Separate workers, concurrency/step/token/time limits, cancellation, read-only tools | Queue delay or model cost growth |
| Host | Container resource reservations/limits after inventory, disk alerts, restart policy | Sustained resource saturation |

For the first query engine, PostgreSQL handles both retained observations and grouped analytics. Trino, Spark, or a lakehouse become justified by measured large/federated datasets or materially heavier computations, not by the presence of an agent. Their eventual introduction sits behind the analytical query service and does not change the agent contract.

## Reliability and security

- API health, worker polling, Temporal service, PostgreSQL, storage, and schedule lag are monitored. Alert on missed refresh, missing-symbol coverage, stale provider timestamps, workflow failures, and disk exhaustion.
- No backup or restore process is planned for the first private deployment. This means a host or disk loss can lose catalog, research records, and Temporal history, even if market bars can later be fetched again. Before relying on the system for important retained work or opening it to traders, design backups for application and Temporal persistence, choose an off-host destination, and verify restoration in an isolated environment.
- Provider credentials and LLM keys live in secret files or a secret manager, not images, Git, logs, or Temporal payloads. Redact provider response bodies if they contain credentials.
- Initial access is through Tailscale. Temporal UI and PostgreSQL are internal only. Public rollout adds identity, authorization, HTTPS, rate limiting, and market-data redistribution rights.
- Workflows and schema changes require versioning and staged rollout; production Temporal requires a planned server/schema upgrade path. [Temporal self-hosted guide](https://docs.temporal.io/self-hosted-guide).

## Deployment choices

One homelab host can run the logical components in Docker Compose, each with distinct credentials and persistent volumes. The measured CPU/RAM/storage make this a reasonable first deployment hypothesis, subject to a Temporal/PostgreSQL baseline load test. Docker is not installed yet. A local Kubernetes deployment is viable, but would itself need installation and operational capacity. Neither option changes service/data boundaries. Public exposure and high availability are separate later design gates.
