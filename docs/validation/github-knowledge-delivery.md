# GitHub knowledge and evaluation delivery

Date: 2026-11-08. The user explicitly requested pushing the feature branch, merging into main and refreshing the bilingual README with feature-page previews. This supersedes the previous checkpoint-4 authorization gate. After the merge and remote verification, work pauses; deferred features are not started.

PR: [#2 — online research knowledge, reviewed GraphRAG and evaluation center](https://github.com/A1f1ed/Financial_Research_Agent/pull/2). Source branch: `codex/research-knowledge-v1`. Keep the branch after merge. No release tag or public deployment is requested.

## Delivered scope

- Existing CopilotKit native chat, AG-UI streaming/tool/reasoning cards, frontend/HITL tools, shared state, Inspector and configured Intelligence integration retained.
- Online collections/documents, exact versions, publication/date evidence, extraction coverage, archive/history, real keyword/pgvector indices, original-page citation and scoped native document Q&A; reviewed Decimal inputs/calculations and single-stock document binding.
- Real-document relationship extraction, explicit identity/evidence review, accept/reject/revoke, durable Neo4j publication, interactive Cytoscape graph, readable paths, historical snapshots and original-page links.
- Online versioned evaluation datasets, separate frozen/development partitions, immutable source/rule manifests, dedicated Celery execution, results and timings, error/unsupported/unknown/budget/cancel states, independent retries, comparison, CSV/JSON export and native Agent read/human-approved-start tools.
- English-default README with Chinese counterpart: feature summary, online workflows, supported AI, data coverage, setup/operations, architecture/technology and actual screenshots. New preview files are `knowledge-light.jpg`, `graph-dark.jpg`, `evaluation-light.jpg`; `chat-light.jpg` is refreshed. Prior research/report/settings screenshots are explicitly identified as earlier workbench views.

## Verification

Local production build and TypeScript passed after the final evidence-navigation changes. Final full local suites: 98 real-service integration tests / 69.675 s and 88 domain/business tests / 62.571 s; after the small evidence-link adjustment, the affected evaluation suite passed 15 tests / 12.892 s. Full tests run again on the final GitHub PR head.

Stream checks preserve canonical text/tool arguments/lifecycle and reasoning/retry order; Unicode original-offset selection and standalone build cleanup checks passed. Isolated real PostgreSQL migrations, schema drift and downgrade/re-upgrade are covered by integration tests. RabbitMQ/Redis/Neo4j/S3 tests use real disposable/local services; model-provider tests use controlled doubles unless the acceptance records explicitly state a real request.

Actual browser paths: EN/light and ZH/dark result views; online fresh PDF upload → collection/index → new dataset/import/publish → real run; native evaluation read → human review → approved no-model run → correct result; graph and calculation evaluation → exact original PDF; real CSV download; refreshed chat/knowledge/graph/evaluation previews. Original services and the production-mode local frontend remain running for user review; scheduler remains disabled. Mobile is intentionally deferred.

GitHub Actions `Verification` has two jobs: frontend production build/type/stream/evidence/cleanup checks, and Python domain plus real-service integration/migration tests. It generates disposable CI credentials, starts pinned infrastructure, uses no model vendor secrets and cleans up only its ephemeral runner's containers/volumes. The final exact PR-head check results must be successful before merge; missing checks are not treated as passed. PR #2 is the authoritative live check/merge record.

## Limits retained

This is a local single-user application. SaaS authentication/tenant isolation, billing/hosting, vision interpretation, Wiki/thesis lifecycle, incremental knowledge discovery and advanced graph governance remain future work. Local scheduling is paused; manual Run now remains available. A model connection greeting or deterministic source/number check is not financial accuracy, semantic entailment, trading performance or production readiness. Repeated benchmarks are performance samples, not independent quality cases; cold/warm caches are uncontrolled and there is no controlled before/after speedup claim.

Frozen acceptance references are hidden from evaluated prompts and Agent tools; explicit human UI reveal remains possible in this single-user app. The full frozen 24-case quality benchmark has not been passed or tuned for this release. Broader rapid-switch/archive/legacy-mapping/decline UI matrix, mobile, load/resource and multi-service outage/backup drills remain limited beyond the specifically exercised paths. See [checkpoint 2](checkpoint-2-rag-graph.md), [checkpoint 3 and release follow-up](checkpoint-3-evaluations.md), and the [broader roadmap matrix](research-knowledge-validation.md).

Rollback/recovery: back up PostgreSQL and named object/service volumes before upgrades; never `down -v` a user's environment. Use additive Alembic migrations and the existing documented offline legacy migration/recovery tools. Reverting UI/application code does not reverse retained user data. Do not downgrade a populated business database without a verified recovery plan. CI teardown is restricted to fresh hosted runners.

## Checkpoint 3 acceptance follow-up

The user requested completion of the remaining third-checkpoint work after PR #2 merged as `5b9d353010225922ab2ec7f66226075bcd7bbeab`. Follow-up branch: `codex/evaluation-acceptance`. [Final functional acceptance](checkpoint-3-completion.md) supersedes the legacy-mapping/decline/rapid-switch/archive/compare coverage limits above; mobile, broad load/outage and independent quality targets remain deferred.

This follow-up adds validated/paged source mapping, saved native approval/decline rendering, stale comparison/request isolation, stable filtered-run summaries, cancellation durations and regression coverage. Local integration/domain suites passed 100/88 tests, followed by 30 affected tests after the duration fix. Desktop four language/theme combinations and controlled delayed-response races were checked on the final production build. A new actual comparison screenshot accompanies the record. No schema migration or production deployment is introduced. Exact PR-head CI and merge confirmation are recorded below after verification.

Follow-up: [PR #3 — evaluation acceptance](https://github.com/A1f1ed/Financial_Research_Agent/pull/3), branch `codex/evaluation-acceptance`, initially submitted as `5da983423c9032f9a2de0eb2ef119d90679f7420`. Use the PR's final head, Checks and merge event as the authoritative delivery status; this document was prepared before CI/merge and does not treat pending checks as success. Preserve this branch after merge and pause further feature work. No release tag or public deployment is included.
