# Evaluation center

Evaluation center is an online workspace module backed by PostgreSQL, Celery/RabbitMQ and S3-compatible object storage. It uses the existing document, graph, numeric and native LangGraph services. No preloaded dataset is required. Open **Evaluation center** in the sidebar.

## Workflow

1. Create a dataset, or import a JSON export. Add cases with a target, development/frozen partition, exact originals or a collection, knowledge cutoff, expected pages, numbers or behavior. Save the draft.
2. Publish a version. Publication pins document identities, metadata revisions, SHA-256 hashes, date eligibility, current published indices, graph/projection revisions and reviewed numeric revisions. Published versions and old results cannot be edited through the API. A later source/configuration change requires a new version rather than silently changing an old experiment.
3. Configure a run. Choose the published version, partition, quality/retrieval/list/Agent measurement, repetitions, time/page limits and optional model permission/call/token budgets. Frozen acceptance requires explicit confirmation. Start runs yourself; a chat tool opens the same review dialog before execution.
4. Inspect saved progress, per-case outcomes, generated answers, deterministic checks, original PDF pages, stage timings and trace IDs. Open Task center for the shared job timeline. Cancel stops further work while retaining completed results and reserved usage. Retry always creates a new run linked to its parent.
5. Compare two runs and export safe JSON or CSV samples. Configuration differences are highlighted; added/removed cases remain visible. Archive/restore datasets without deleting published versions or history.

## Targets and measurement boundaries

| Target | Actual execution | Supported checks |
| --- | --- | --- |
| Evidence retrieval | Existing PostgreSQL keyword or pgvector hybrid service, strict source/date scope | Expected original-page Recall@5, citation identity/page/hash/span validity and cutoff leakage |
| Native document Agent | Existing LangGraph/document tools with pinned source scope, bounded model calls and normal citation finalization | Cited original-page coverage, valid references/date bounds, explicit lexical abstention rules; generated answer available for human review |
| Reviewed calculation | Existing Decimal calculation/audit service with pinned reviewed input revisions | Numeric value and absolute tolerance; currency, scale and period if specified |
| Graph paths | Existing reviewed/published Neo4j traversal | Minimum edge count, allowed and dated evidence, expected cited pages if configured |
| Task-list benchmark | Worker makes a real internal HTTP GET to `/research/tasks?limit=20` | Response contract and elapsed HTTP/API/DB/JSON time; not browser rendering or financial accuracy |
| Vision / Wiki / unadapted manual rules | Explicit unsupported/unscored results | Included in all-planned denominator; never fabricated as passing |

Quality, retrieval performance, list performance and full Agent performance are separate run modes. Benchmark modes require only matching targets. Default repetition count is 30; a run permits 1–100 repetitions and at most 500 attempts. Each run executes serially (concurrency 1); the dedicated worker allows two independent runs. Latency uses interpolated p50/p95 and retained raw samples, including timed failures; warm/cold conditions are not controlled. Stage metrics separate retrieval and model generation. Queue wait is reported separately.

These deterministic checks do **not** measure semantic entailment, complete numeric correctness of an Agent answer, investment quality or general model accuracy. Lexical refusal classification is not a semantic judge. Scope/date filtering is not a complete point-in-time financial database. Repeating one question 30 times is a performance sample, not 30 independent quality cases or generalization evidence. No before/after speedup or SLA is claimed without a controlled baseline.

## Budgets, recovery and privacy

Model permission defaults off. Hybrid retrieval also requires explicit model permission because query embedding can call a provider. The run pins non-secret active model and embedding configuration. Changed embedding configuration is blocked. Model calls reserve budget atomically before sending; default automatic retries are disabled. Reservations conservatively use UTF-8 prompt/tool-schema bytes, the configured output cap and an allowance, **not** an exact tokenizer or invoice estimate. Reported provider tokens remain separate; missing usage is shown as unknown. Source page budget is the sum of the selected original page counts per case; repeated attempts do not multiply this source-scope count.

Each attempt has a durable identity and fenced execution lease. Completed attempts survive refresh, API restart and duplicate delivery. After worker loss an in-flight attempt is marked unknown/interrupted and is not automatically replayed; pending attempts resume after lease recovery. Explicit retry creates a new run and a new budget. Cancellation cannot retract a provider request already sent; its reservation remains. A service exception is an operational error, not proof of absent evidence.

The evaluated Agent receives the question and allowed sources, never expected answers, scoring notes or frozen reference material. Read-only Agent tools expose real IDs/statistics; frozen attempt answers/outputs/checks are withheld from those tools. Human users can explicitly inspect frozen references in the local application. This is an application-level separation, not a multi-tenant authorization system.

Persisted output is bounded and excludes reasoning/raw source-page payloads. Results larger than 4 KB additionally produce a verified S3 JSON artifact. Exports omit expected answers and generated answer text. Optional Langfuse export remains metadata-only; it supplements saved in-app results and native CopilotKit chat/Inspector. No provider keys are returned to the browser or written to run manifests.

## Import / export

The ordinary JSON format contains `name`, `description`, `cases`; it can be exported and imported from the UI. Development-only export is the default; frozen export/reveal requires explicit human action. Legacy source contracts require mapping each symbolic source label to an uploaded exact document version. Their original human references are retained and partitions preserved. Complex numeric, relation, vision and Wiki rules are not silently translated into passing criteria: adapt supported draft checks explicitly, otherwise they remain unscored/unsupported. Imports never publish or run automatically.

The mapping dialog searches/pages uploaded originals, retains selections across searches, displays referenced/available pages and publication metadata, and requires renewed confirmation after any mapping change. Backend validation rejects inactive/missing originals and out-of-range pages. Malformed files fail before rendering the mapping form. Saved native approval/decline decisions restore from chat history; restoring a decline never starts a run. Comparison and run-detail requests cancel/ignore stale responses when switching, and filtered attempt loading retains the current run summary.

## Operations

Migration `49ba0cbc7efc` adds evaluation datasets, versions, runs and attempts. Apply migrations before starting workers. Compose includes `evaluation-worker` on the dedicated `evaluation` queue. Reuse the existing API/dispatcher, RabbitMQ, PostgreSQL and objects services. The worker calls a fixed internal API URL (`APERTURE_EVALUATION_API_URL`, Docker default `http://api:8123`), not a user-supplied benchmark address.

```powershell
docker compose --env-file infra/.env -f infra/compose.yaml up -d --build api evaluation-worker
```

The Next.js research proxy exposes a fixed evaluation route allowlist. APIs are under `/research/evaluations`: datasets/create/edit/import/export/publish/archive/restore, versions, runs/start/detail/cancel/retry/export/attempts and compare. Writes use existing same-origin checks. Existing local deployment authentication limitations still apply; this feature does not establish production SaaS security.

See [checkpoint 3 completion](validation/checkpoint-3-completion.md) for final functional acceptance and the [earlier snapshot](validation/checkpoint-3-evaluations.md) for initial run evidence. Vision, Wiki, automated semantic judges and broad frozen-set quality targets remain outside this checkpoint.
