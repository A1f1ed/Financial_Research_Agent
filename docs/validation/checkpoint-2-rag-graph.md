# Checkpoint 2 — RAG and GraphRAG acceptance

Accepted locally on **2026-11-08**, within the [approved release scope](../releases/knowledge-v0.2.md). This closes checkpoint 2; it does not certify the complete PRD, public SaaS readiness, quantitative model quality, or checkpoint 3. The evaluation center and final CI/PR/merge remain separate user-gated work.

## Delivered behavior

- Online document/collection/version/index management, source-date filtering, keyword/hybrid retrieval and native document Q&A retain original-page citations. Existing real-service lifecycle and hybrid-search evidence is recorded in the [validation matrix](research-knowledge-validation.md).
- Reviewed financial inputs now retain exact numeric/unit spans, explicit period and consolidation basis, source revisions and audit reasons. Decimal calculations retain immutable inputs/results; models can use valid reviewed inputs but cannot manufacture approvals. Original-page context and the selected-value preview support human checking.
- Single-stock submission atomically pins selected collections' exact versions, hashes, metadata revisions and cutoff with the job/outbox. Later additions cannot enter that task. Archive/metadata changes are rechecked before evidence is retained. Report/Q&A/export keep that scope and page provenance; unsupported or failed evidence is an explicit gap.
- Automatic relationship extraction proposes identities/relations without publishing them. Human identity resolution, acceptance/rejection, real worker synchronization, Neo4j traversal, Cytoscape visualization, saved paths and original evidence form an actual web workflow.
- Native document chat can discover published graph identities and traverse accepted paths within its fixed document allowlist. Knowledge cutoff and historical applicability are separate. Tools cannot write Cypher, approve, extract or synchronize; inferred influence stays distinct from disclosure.
- CopilotKit chat, provider reasoning, tool cards, streaming, history and Intelligence remain in use. An AG-UI middleware batches adjacent canonical deltas and removes redundant token-debug copies before durable delivery; lifecycle/tool/state boundaries and canonical text/arguments remain intact.

## Actual public-document workflows

| Path | Observed evidence |
| --- | --- |
| Fresh files → extraction → review → publication | Graph `d504f21f-2c58-4512-976a-57d457ac7d8e`, two freshly web-uploaded European Commission 2024 PDFs. Extraction `4ab2ad75-7d9e-4425-bdf7-5014b8baad3d`: 4/4 units, 15 proposals, about 18s, 8,841 reported tokens. Institution type corrected explicitly; two announcement relations accepted, one unsuitable proposal rejected, twelve left pending. No automatic publication or acceptance-rate score. |
| Distinct policy stages | Reviewed graph v8: Commission organization plus separate provisional/definitive announcement identities. Known by 2024-11-01 / applicable 2024-07-05 returned one provisional path; applicable 2024-11-01 returned both announcement paths. Dates do not establish entry into force, current law or financial impact. |
| Native graph conversation | Thread `fd0b2a56-7183-4704-83de-4edee3110be7`. First attempt hit durable event delivery failure; retry `495070b0-28de-49f9-bfe5-89019085f393` finished successfully with fresh tools and a July 4 original PDF citation. Production run `5bb6ce16-6b39-4ef2-b611-7e2691f41fc2` also has saved `RUN_FINISHED`; query `baebd5f9-5d72-410d-a22c-8b8ff43f672d` returned 3 nodes / 2 edges / 2 paths in 100.162ms. |
| Reviewed arithmetic | BYD impairment PDF page 2: 943,964 − 83,843 + 2,794,209 = 3,654,330 thousand CNY; scale conversion = 3654.33 million CNY. Web and native tool results agree. Thread `8b5a1153-a5d5-46f0-a094-5457734d085a` restores the native calculation cards and citations without another calculation. This verifies those reviewed inputs, not a full financial audit. |
| Review lifecycle | Correct inventory input archived with reason, then restored to revision 3 in the production UI. Original four calculations remained readable. A fresh conversion after restoration produced 2794.209 million CNY. Two earlier misselected QA inputs remain archived with correction reasons. Changing unit evidence reset confirmation; cancelling the preview created no input. |
| Research binding | Task/report `f251a41e-5dae-4e3e-b819-6f5f3c2f2213`, 11.1s observed: two versions pinned at 2026-10-31, October 29 impairment admitted, November 1 sales excluded. S16/S17/S18 target PDF pages 2/3/1. Native report Q&A used the exact report; retained PDF page 2 / file v1 / metadata revision 2 opened. Markdown export includes the source hash and original-page path. |

## Defects found and resolved

1. Institution taxonomy lacked an organization type; human review can now correct it without changing the stored model proposal.
2. Small graphs overlapped and Fit over-zoomed. Deterministic initial positions, a layered small-graph layout, readable zoom cap and separate node/edge selection styles now keep the three-node graph readable.
3. Chinese numeric questions could not find English reviewed metric labels. A clearly labeled, bounded same-scope recent-input fallback now allows selection while preserving source checks.
4. A real long-reasoning stream persisted 5,155 events before Intelligence delivery failed. The supported middleware retained native content while reducing the successful development retry from 4,309 incoming events to 235 delivered events; production run: 3,531 → 273, including removal of 1,703 redundant token-debug events. These are different runs, **not a controlled latency improvement or throughput claim**.
5. Recovered old assistant messages could be appended after a newer retry answer. Canonical backend snapshots now own message order while native reasoning/activity cards remain attached to their turn. Synthetic regression and real reopening confirm the latest answer stays last.
6. Document-dialog scrollbars were bright in dark mode; scoped theme styling now matches the surrounding controls.

## Verification

- Full isolated real-service integration suite: **87 passed / 58.311s**, `APERTURE_RUN_INTEGRATION=1` with `python -m unittest discover -s integration_tests -q`. PostgreSQL, Neo4j, Redis and object storage are real local services; test claims are synthetic and make no provider calls. Migration downgrade/re-upgrade and schema drift passed through revision `0a4590d5ae25`.
- Full domain/business suite: **84 passed / 60.702s**, `python -m unittest discover -s tests -q`. The two suites ran concurrently; elapsed times are not performance benchmarks.
- TypeScript strict checking and `npm run build` passed. Production frontend restarted on loopback localhost:3000; actual browser checks used the built application, not only HTTP readiness.
- `npx tsx scripts/test-agent-stream.mts` passed: 20,015 synthetic events → 13, preserving 10,000 text characters, tool JSON, lifecycle boundaries, timer/error/cancellation behavior, canonical retry ordering and reasoning cards.
- Desktop **1280×720**, English/light and Chinese/dark: native history, live graph tools and final answer ordering, context-varying follow-ups (click fills only), graph canvas/paths/scrolling, selected-value preview/confirmation reset/cancel, archive/restore/calculation history, single-stock task → report → original PDF page and theme/language switching. Screenshots were visually reviewed through the browser tool; no new durable screenshot artifact is claimed. Mobile intentionally deferred by the user.
- Real previous graph management acceptance exercised cancel/revoke, stale projection blocking, re-sync to an empty current path, saved historical paths, archive and retained originals. Isolated regression additionally covers temporal/document allowlists, graph service failure, stale/concurrent revisions, bounds and source changes. This is not a broad live chaos test of every service.

## Practical limits and next gate

The small public-source examples are attributable functional acceptance, not independent model-quality evaluation. The frozen 24-case contract has not been scored or tuned as part of these walkthroughs. Larger multilingual retrieval quality, load/resource tests, broad service-outage drills, object backup/cleanup, durable new screenshots and final CI remain unproven. Full Wiki, vision, advanced graph governance and public multi-tenant SaaS remain outside this checkpoint.

History still depends on upstream event reads: a final read-only event fetch took about 8.8 seconds locally. Local restored-history caching, timeout and retry exist, but no controlled history-latency improvement is claimed. Five-request metadata observations and earlier hybrid-search samples are recorded separately in the progress log; they are not an SLA.

Checkpoint 3 must provide the **in-app evaluation center** before this GitHub version can reach final delivery. Checkpoint 4 must validate the final head/CI and merge through a PR. Neither starts without the user's next explicit confirmation. The feature branch is preserved; `main` is unchanged.
