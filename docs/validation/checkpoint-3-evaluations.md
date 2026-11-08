# Checkpoint 3 — evaluation center early-review snapshot

Date: 2026-11-08. Branch: `codex/research-knowledge-v1`. The user authorized checkpoint 3 and then requested early branch acceptance. **This is a reviewable implementation snapshot, not checkpoint-3 completion or permission to start checkpoint 4.** Main has not been merged. No production deployment, final CI/PR or whole-PRD quality pass is claimed.

## Implemented and exercised

Online dataset creation/editing, explicit JSON import, immutable publication with source/index/graph/figure pins, dedicated durable Celery execution, per-case results, stage/sample metrics, cancellation, independent parent-linked retries, frozen partition confirmation, safe exports, run comparison and task integration are implemented. The product does not require repository datasets; its forms use uploaded documents and reviewed service records.

Actual browser paths used: sidebar → Evaluation center → New dataset → add case → save → publish → configure → start → saved results → attempt details → original PDF; edit/publish a second version; retry with model calls disabled; compare different configurations. A second dataset was created in the browser for a real internal HTTP list benchmark. A third was imported through the browser after uploading a new public PDF, creating its collection and building its index. Frozen start without the required checkbox was prevented by form validation, then explicitly confirmed.

Desktop 1280×720 English/light and Chinese/dark were visually inspected, including result tables and retained original PDF pages. Latest spacing/readable-value adjustments were rebuilt and visually rechecked on the running production UI; the English/light run list and Chinese/dark calculation detail were inspected. Mobile is deferred at the user's request.

## Real run evidence

These IDs identify retained local PostgreSQL/S3/service records, not portable seeded data or public production URLs. A fresh checkout must upload its own originals and create/import datasets. Raw PDFs, databases, run answers, credentials and local validation logs are not committed.

| Run | Actual result and boundary |
| --- | --- |
| `380c8c41-bd02-460b-a2f3-244085e2a529` | Browser-created retrieval benchmark: 30/30 deterministic passes for one disclosed-page case; page Recall@5=1 for those repeated samples, no date leak, zero provider calls. Attempt p50 51.753 ms, p95 91.668 ms. Retained original page 2 opened from attempt details. This is not 30 independent quality cases. |
| `2702449e-0b7c-4c19-8e58-d37e12353f50` | Two development cases, including actual native LangGraph document Agent. Both configured checks passed. Agent made 2 provider calls and reported 7,164 tokens; 34,054 tokens conservatively reserved. Native Agent attempt 5,081.218 ms, model stage 2,865.494 ms. Its cited impairment value/unit was manually inspected; semantic accuracy and an unscored 80-word formatting request are not inferred from the pass badge. |
| `f2130f00-52d2-4ddf-8fd3-57891f6bf3d5` | Explicit parent-linked retry with model permission off: one retrieval pass, one budget-exceeded result, zero provider calls. Both remain in the denominator. Original run unchanged. |
| `18f00c98-37cf-4cc7-a381-169fc3c35bb4` | Browser-created task-list HTTP benchmark: 30/30 contract checks, zero model calls; p50 71.826 ms, p95 86.695 ms. Includes worker HTTP client/network/API/DB/JSON, excludes browser and financial accuracy. |
| `2eeb69ea-3c41-40c1-9c52-870be970dfa8` | 100-sample list retry completed before the browser cancellation confirmation. Server correctly preserved completion rather than relabeling it cancelled. UI now explains this completion race. This is not counted as a successful cancellation test. |
| `f607da4d-d488-4904-ad1c-59cc4abd38b2` | Actual API cancellation during a 100-sample list run: 4 completed results retained, 96 cancelled, zero provider calls. |
| `81966d64-7fdd-44cb-9fe8-bb8278faed1f` | Dedicated evaluation worker killed and restarted after 4 completed list requests, with one in flight. Recovered after its lease: 99 passed, 1 interrupted/unknown, 0 reserved calls. All four prior IDs, statuses, completion timestamps and elapsed values unchanged. Unknown attempt not replayed. |
| `9768c282-a7e1-43d4-b025-19ad4a122bba` | New-source/graph/arithmetic browser run exposed Python date JSONB serialization failure. Original failed run retained; no result overwritten. Normalization now preserves exact Decimal strings and dates before scoring/persistence; real reviewed-calculation regression added. |
| `46edf6e1-7539-456e-8e55-15bbeae9ccfe` | Repaired browser retry: 3/3 configured checks passed, 0 model calls. Newly uploaded presentation retrieved expected PDF page 3; reviewed impairment total converted exactly to `3654.33 CNY millions` with Jan–Sep 2026 period; real Neo4j query retained two reviewed EC announcement edges. These three different timings are not a homogeneous performance benchmark. |
| `0ef7e02b-1960-4091-a626-e95bf96695b6` | Explicit frozen-partition UI probe: one unsupported vision case, 0 passes, zero calls. This tests partition/unsupported behavior, not the independent 24-case financial quality benchmark. |

Fresh-source document `d80afd05-faa1-4111-b52b-43f3607da1c4` was uploaded through the App, not preinserted by a script. It is a public issuer presentation (publication day 2025-08-14, issuer archive/cover basis), 21 PDF pages; extraction accurately reports 20 readable pages and 1 needing vision. Original PDF page 3 was visually checked against the retained uploaded original. Its 32-chunk keyword index was built using the online collection controls. No visual understanding pass is claimed.

## Automated checks

- Full real-service integration suite: **96 tests passed / 69.824 s**, including additive schema check and isolated downgrade/re-upgrade; this preceded the two additional focused comparison/calculation regressions.
- Full domain/business suite: **88 tests passed / 61.966 s**.
- Latest evaluation-focused suite: **15 tests passed / 12.852 s**, including real PostgreSQL/LangGraph deterministic-provider execution, 30 retrieval repetitions, no paid replay, frozen answer isolation and same-origin protection, atomic budgets, unknown-outcome recovery, cancellation fencing, source changes, concurrent independent runs, all-planned failure denominator, added/removed comparison cases and actual reviewed Decimal/date persistence.
- TypeScript and production build passed during browser acceptance. The final snapshot production build also passed after the presentation fixes; generated environment copies were removed by build finalization.
- Snapshot preflight checked 304 tracked/new nonignored files against 14 configured secret values and common credential patterns: no matches or prohibited local artifacts. This is not a full security audit. Staged whitespace checks passed.
- Migration `49ba0cbc7efc` applied locally; schema drift check reported no new upgrade operations.

## Still to finish within checkpoint 3

- Real native chat acceptance of evaluation read tools and human-approved start/decline card; tools are wired and frozen read isolation has automated coverage, but the full live chat path is not yet signed off.
- Finish dedicated graph/calculation evidence navigation from evaluation details. Calculation IDs/formula/period and graph query IDs are retained; graph evidence with no search citation currently cannot use the retrieval citation viewer. Existing GraphRAG original-page navigation remains available.
- Complete legacy-contract source-mapping UI, archive/restore, same-configuration comparison, download and rapid-switch/cancel-race UI matrix on the final snapshot. Backend/import tests and several real paths already pass; they do not replace these remaining UI checks.
- Final checkpoint-3 aggregate regression/desktop EN/ZH light/dark review, documentation and exact-secret/artifact preflight before declaring this checkpoint complete. Full frozen-set financial/vision/Wiki quality targets remain future work, not an acceptance badge for this feature.

The user may review the feature branch now. Checkpoint 4 (final release checks, actual CI, PR, main merge and pause) still requires separate authorization.

## Release follow-up, 2026-11-08

After the early snapshot, the user explicitly requested README updates and a PR merge into main. This authorizes checkpoint 4; the earlier gate statements above describe the historical snapshot and are superseded by this instruction. The broader M0–M6 roadmap and independent frozen quality targets remain unfinished.

- Live native CopilotChat called `read_evaluation_run` and returned real saved results, then `list_evaluation_records` and frontend `startEvaluationRun`. The human review card appeared before execution. Explicitly approving one development/no-model repetition created run `7c85d954-8326-46f5-a59b-15b3d6ad1f1a`; its Open evaluation run button opened the correct persisted result, 1/1 contract pass, zero provider calls in that evaluation. Chat itself uses the configured provider; this is not a zero-cost chat claim. Some natural-language metric wording was imprecise, so the read tool now explicitly distinguishes pinned scope pages, heterogeneous attempt timing and reservations.
- Final mixed run `23fb77ff-2b95-416f-8c7e-f1ee6c793361` passed its 3 configured retrieval/calculation/graph cases, zero provider calls. Original PDF links opened the numeric input at PDF page 2 / metadata revision 2 and the reviewed EC graph source at PDF page 1 / revision 1. Bounded source excerpts/provenance are retained; past results are not backfilled.
- Actual browser CSV export downloaded three result rows with IDs, status and timings, without expected answers or generated answer text.
- New durable README screenshots show the running knowledge library, graph, evaluation center and refreshed chat. No original PDF pages are included in these added preview images.
- Final local suites before the evidence-link adjustment: 98 integration tests / 69.675 s, 88 domain tests / 62.571 s. The adjusted evaluation suite passed 15 tests / 12.892 s; final production build, stream/lifecycle/order, Unicode evidence-selection and standalone cleanup checks passed. Actual GitHub CI repeats the final build and whole backend suites on the PR head before merge.

The outstanding legacy source-mapping UI, decline-card branch, broader rapid-switch/archive/compare matrix, mobile and broad load/fault work remain coverage limits; automated tests and the exercised paths above do not silently certify them. User-requested delivery merges this documented local single-user feature scope, not a production SaaS or full financial-quality benchmark. See [GitHub delivery](github-knowledge-delivery.md) for the PR/check status and pause boundary.
