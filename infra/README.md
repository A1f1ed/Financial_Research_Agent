# Durable development services

The target service stack is PostgreSQL/pgvector, RabbitMQ, Redis, Neo4j and S3-compatible SeaweedFS. Images are pinned to the immutable digests actually pulled and tested. This is a single-node development environment; no HA or public-SaaS claim is made.

From the repository root, with Docker's Linux engine running:

```powershell
copilotkit-app/agent/.venv/Scripts/python.exe copilotkit-app/scripts/init_infra.py
docker compose --env-file infra/.env -f infra/compose.yaml up -d --wait
```

The initializer creates random service credentials once in ignored `infra/.env`, never prints them, and refuses to overwrite an existing file. Do not run `docker compose config` without `--quiet` in shared logs: rendered configuration contains credentials. All exposed ports bind to loopback.

From `copilotkit-app/agent`:

```powershell
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m alembic check
.venv/Scripts/python.exe -m src.infrastructure.probe --exercise
$env:APERTURE_RUN_INTEGRATION='1'
.venv/Scripts/python.exe -m unittest discover -s integration_tests -v
```

The probe performs authenticated, temporary Redis, RabbitMQ and S3 round-trips and a pgvector distance query. Probe records are removed. Diagnostic output contains status/types/latency, not keys or authenticated URLs. The integration suite creates and drops a uniquely named `aperture_test_*` database. It uses actual PostgreSQL for transactions and JSONB; SQLite fixtures are only legacy import input.

## Read-only migration rehearsal

```powershell
.venv/Scripts/python.exe -m src.persistence.migrate_legacy --database aperture_rehearsal_m0
```

This command reads the original `agent/data/*.sqlite3` databases through SQLite's backup API and writes snapshots plus a manifest under ignored `local-data/migrations/<UTC time>/`. It creates/uses only an explicitly named `aperture_rehearsal_*` PostgreSQL database. It imports typed business records and uses the official savers to decode/re-encode checkpoints and pending writes. It verifies source/target semantics and preserves IDs and insertion order. Existing differing business/checkpoint data is rejected. Repeating an unchanged import is supported.

It does **not** switch the application configuration, execute saved plans, send model requests or delete original databases. A separate controlled application cutover has now been executed locally; see the current evidence in `docs/validation/research-knowledge-validation.md`. Rehearsal alone never establishes cutover success.

## Rehearsal backup and recovery

The following names are reserved for this local rehearsal; do not substitute a user database without a separate cutover/recovery procedure. Run from the repository root, once the migration is verified:

```powershell
docker exec aperture-research-postgres-1 pg_dump -U aperture -Fc -f /tmp/aperture-m0.dump aperture_rehearsal_m0
docker cp aperture-research-postgres-1:/tmp/aperture-m0.dump local-data/migrations/aperture-rehearsal-m0.dump
docker exec aperture-research-postgres-1 createdb -U aperture aperture_recovery_m0
docker exec aperture-research-postgres-1 pg_restore -U aperture -d aperture_recovery_m0 --exit-on-error /tmp/aperture-m0.dump
```

Run `src.persistence.verify_recovery` from the agent directory with `--database aperture_recovery_m0 --snapshot-dir <verified snapshot directory>`. It verifies original snapshot hashes, all business rows, checkpoint payloads/parents/pending writes and source metadata through read-only database transactions. It writes only a local verification report. An existing recovery database is not dropped automatically; use a new isolated recovery name for another restore.

## Service boundaries

| Service | Host endpoint | State |
| --- | --- | --- |
| PostgreSQL | `127.0.0.1:15432` | Persistent volume; business schema `research`, saver schema `agent` |
| RabbitMQ AMQP | `127.0.0.1:15673` | Persistent broker volume; app vhost `aperture` |
| RabbitMQ console | `127.0.0.1:15672` | Local authenticated diagnostics |
| Redis | `127.0.0.1:16379` | TTL cache/coordination; no authoritative user state |
| Neo4j Bolt / browser | `127.0.0.1:17687` / `127.0.0.1:17474` | Persistent graph volume |
| S3 API | `127.0.0.1:18333` | Persistent object volume; bucket `aperture-research` |

Use `docker compose --env-file infra/.env -f infra/compose.yaml --profile application stop` to stop services while preserving data. Do not remove volumes or use `down -v` on user data. Full object/document recovery and fault validation remain required before M6 completion.

## Application services and first startup

From `copilotkit-app`, after preparing its `.env` and running the initializer:

```powershell
npm run services:up
docker compose --env-file ../infra/.env -f ../infra/compose.yaml --profile application exec api longbridge auth login
npm run build
npm run start
```

`services:up` builds the pinned Linux amd64 agent image. A one-shot `migrate` service applies Alembic and the official PostgreSQL saver setup, then the API (`8123`), research and maintenance workers, Beat and outbox dispatcher start independently. No request creates schemas. `npm run dev` starts these services plus the UI development server; `npm run start:all` starts services plus the built UI. `dev:agent` is an advanced native API-only command and must not compete with the container API on the same port. Python workers run in Linux containers on Windows.

The container includes checksum-verified official Longbridge CLI 0.31.1. Complete the device authorization flow for this container. Its own credentials live in named `agent-home`; **do not inspect or copy host token files**. Normal image recreation preserves this authorization volume. Model keys initially come from the app `.env` (not baked into the image). Settings replacements go to `/home/aperture/config/provider.env`, mode 0600, shared by API/workers; non-secret profiles live in PostgreSQL. A saved replacement overrides an old process environment key. Recreate services after manually changing app `.env` environment values.

Automatic saved plans and condition checks default to maintenance pause (`RESEARCH_SCHEDULER_ENABLED=false`); the schedules page displays this status. Manual run-now remains enabled. After verification, explicitly set that flag to true in `infra/.env` and recreate application services. Enabled plan flags are preserved during maintenance; they do not mean the global scheduler is running. API restart does not terminate submitted worker execution. Host sleep or stopped Docker does stop local automation.

Runtime market cache uses Redis with hashed keys, database-specific namespaces and at most 24-hour physical TTL; consumer-specific freshness still applies. Cache failures produce a miss, never an automatic fallback database or old data marked as fresh. Imported historical PostgreSQL cache rows remain for migration verification, but are no longer the runtime cache.

## Controlled legacy cutover and rollback boundary

Stop API, workers, Beat and dispatcher during the write maintenance window. Rehearse and restore a snapshot first, then from `agent` run:

```powershell
.venv/Scripts/python.exe -m src.persistence.cutover --snapshot-dir <verified-snapshot-with-recovery-report> --apply
```

This verifies source fingerprints, snapshot and recovery reports, imports the configured PostgreSQL target and checks all legacy semantics. It refuses an online API or unpaused scheduler. Source SQLite files remain unchanged and offline; they are not a runtime fallback. Retain the migration artifacts and backup securely.

After cutover, **new writes exist only in PostgreSQL**. Do not resume an old SQLite snapshot and lose those writes. To roll back application code, stop writers and back up the current PostgreSQL database; use a compatible code/schema version or restore into an isolated PostgreSQL database and verify it before changing connection configuration. Alembic downgrades are tested on a disposable database, never blindly applied to user state. This is a controlled single-user migration, not zero-downtime dual write.

## Metadata-only Langfuse tracing

Optional app `.env` fields: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`. Use the base URL for the project's region. `APERTURE_TRACING_ENABLED=false` disables this integration. The existing OpenTelemetry SDK uses a separate owned provider, sends OTLP/HTTP with the v4 ingestion header, and preserves native CopilotKit Inspector. Research runs, real tools and model generations share trace/run IDs; reports store the trace ID and indicate asynchronous export, not guaranteed remote acceptance.

The exporter explicitly selects model name, run/stage IDs, timings, numeric token usage and error **types**. It does not export prompts, document text, model outputs, reasoning, exception text or auth headers; token counts remain absent if unavailable. API keys stay server-side. An exporter failure does not change financial results. External traces supplement the planned in-app evaluation center, not replace it.

Explicit live checks from `agent` (these create clearly named temporary runs / a small greeting):

```powershell
.venv/Scripts/python.exe -m src.infrastructure.verify_execution --apply
.venv/Scripts/python.exe -m src.infrastructure.verify_execution --apply --stock --restart-api
.venv/Scripts/python.exe -m src.infrastructure.verify_telemetry --apply
```

Read-only checks and export behavior follow the [Langfuse OTEL reference](https://langfuse.com/integrations/native/opentelemetry) and [Public API](https://langfuse.com/docs/api-and-data-platform/features/public-api). Test evidence is written under ignored `local-data/validation/`. Never print rendered Compose config or secret-bearing environment files in reports.

SeaweedFS references: [S3 API](https://github.com/seaweedfs/seaweedfs/wiki/Amazon-S3-API), [Apache-2.0 license](https://github.com/seaweedfs/seaweedfs/blob/master/LICENSE). Pin: 4.52. It is accessed through the S3 API, not through direct filesystem access.
