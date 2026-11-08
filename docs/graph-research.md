# Evidence-reviewed GraphRAG

Current delivery is a **partial product implementation**, not completion of the full GraphRAG roadmap. The application has **GraphRAG → Graph management** and **GraphRAG → Relationships & paths** entries. Automatic extraction and explicit identity review now have implementations and focused integration tests; real-model browser acceptance remains pending. The [release plan](releases/knowledge-v0.2.md) places that acceptance in checkpoint 2 and defers advanced merge/split, conflict workqueues and bulk governance to a later release. Graph Agent integration and applicable first-release acceptance remain required.

## Automatic extraction checkpoint

In Graph management, **Extraction & identity review** provides source selection and a no-model budget preview, followed by an explicit start. Durable knowledge jobs retain per-segment request reservations, outcomes, reported usage and exact quoted evidence. Duplicate terminal delivery does not resend a provider request; an interrupted request with an unknown outcome requires an explicit new attempt. Bounded runs disclose deferred source coverage rather than claiming full-document extraction.

Model proposals do not create accepted graph facts. Resolve each endpoint explicitly to an existing reviewed identity or a new, separately typed identity; names alone do not merge records. The resulting relation remains a candidate for the normal accept/reject review. Rejected duplicates retain their review state. Scope changes, stale revisions or invalid evidence prevent publication.

Additive migration `bfceace8ff58` follows the authority/projection migration and stores extraction runs, units and proposals. The focused nine-case integration suite covers reservation/redelivery, budgets, partial failures, source changes, exact Unicode/newline evidence and identity review. These synthetic provider-free tests do not establish real-model extraction quality. The newly uploaded two-policy-stage documents still require the complete browser workflow in checkpoint 2.

## Web workflow

1. Create a knowledge collection and upload/import actual documents through the app. Confirm publication metadata and extracted pages.
2. In **Graph management**, create a research graph from one or more collections, a cutoff, market timezone and allowed relationship types. The graph pins exact document versions (at most 50); adding collection members later does not silently expand it. Explicit scope revisions retain an audit snapshot.
3. Add separate evidenced identities for companies, groups, brands, products, regions, policies or events. Select an exact original-page passage; the preview shows precisely what will be stored. Names never cause automatic identity merging. Aliases and symbols are editable. Revising an identity sends accepted relationships involving it back to candidate review.
4. Propose a relationship between two identities. Choose its type, disclosure/inference classification, applicability interval and supporting passage. Missing dates are allowed for candidates but block acceptance. Impact hypotheses remain inference after review; an existing inferred relation cannot be relabeled as a disclosure.
5. Accept or reject a candidate with a reason. Accepted relations can be revoked. All operations use an expected object revision to prevent stale decisions. An identical rejected candidate is retained rather than automatically re-proposed. Original quotes, hashes, offsets, pages, metadata versions and audit records persist.
6. Select **Synchronize**. A durable knowledge task goes through PostgreSQL outbox, RabbitMQ and Celery to create a complete Neo4j projection. Open its task details from the page or Task center. Repeated requests reuse the active task/current projection; **Rebuild projection** explicitly creates a replacement. Failed, cancelled or stale builds do not replace the prior published projection.
7. In **Relationships & paths**, choose a starting identity, knowledge cutoff, applicability day, relationship types and one or two hops. Inference is excluded by default. Both source publication dates and applicability intervals are enforced on the server. Current graph changes require synchronization before a new query; archived or changed source evidence is excluded immediately.
8. Drag nodes, zoom, fit the canvas, select a node/edge or use the keyboard-accessible node/path lists. The inspector opens the exact original PDF page and links back to object audit history in management. Arrows retain relationship direction even when a path traverses backwards.
9. Completed queries retain their inputs and result snapshots. Reopen them without a new Neo4j/model run. Historical results are clearly marked and remain readable after relation revocation or graph archival; rerunning still applies current authority and source rules.

The UI allows a collapsed query form so the graph can use the viewport. Light/dark themes and English/Chinese share the same managed records. Source text does not change when switching interface language.

## Authority and projection boundaries

- PostgreSQL owns `research_graphs`, `graph_entities`, `graph_relations`, `graph_audits`, `graph_projections` and `graph_queries`. Additive Alembic revision: `f2c5d83fbd0e` after `77ef61a711c0` (document chat).
- Neo4j stores version-namespaced identities and relationships. The browser receives neither credentials nor an arbitrary Cypher executor. Queries use fixed Cypher and bound parameters, one/two hops, transaction timeouts and current-authority edge allowlists.
- A complete projection is made visible only while the graph revision and job lease still match. Old projections and saved query evidence remain retained. Cleanup/compaction of superseded projection generations is a remaining lifecycle gate.
- Result limits: 100 nodes, 200 edges, 1,000 path records. Truncation is explicit. Graph scope supports at most 2,000 identities and 5,000 proposed relationship objects. Broader production sizing/latency gates remain unproven.
- Exact text selection maps browser-normalized CR/CRLF and UTF-16 selection positions back to original Unicode code-point offsets used by Python. The server independently checks page text and source state; text selection alone does not prove a relationship is supported, hence review is still required.
- The application currently serves a local single-user environment. Production multi-user authorization, tenant isolation and operational delivery remain required; loopback-origin checks do not substitute for them.

Implementation references: [Neo4j managed transactions](https://neo4j.com/docs/python-manual/current/transactions/), [bounded variable-length paths](https://neo4j.com/docs/cypher-manual/5/patterns/reference/node-and-relationship-patterns/), [Cytoscape.js documentation and MIT license](https://js.cytoscape.org/). Cytoscape.js is pinned to `3.34.4` in the npm lockfile, used directly with React effect cleanup rather than an additional React wrapper.

## Validation

### Read-only tools in document chat

Fixed-scope document conversations can use `find_research_graph_entities` and `read_research_graph_paths`. Discovery returns bounded identities from currently published graphs in the same market timezone with original evidence in the conversation's exact document versions. Traversal uses the existing Neo4j service, current accepted relationships, a two-hop limit and an additional server-side document allowlist. The model cannot submit Cypher, extract relationships, approve proposals or synchronize through these tools.

Knowledge cutoff is fixed by the conversation. An optional earlier applicability date does not pretend that later-published knowledge was available on that earlier day. Inferred influence is opt-in and remains distinct from disclosed relationships. Chat sends at most three paths and one bounded original excerpt per identity/relationship, with explicit truncation and saved query IDs. Full query evidence remains in GraphRAG history. Returned citations are saved as current-turn document evidence and open the original PDF page; they pass the same identity/scope checks as retrieved document citations. Graph service failure is reported as failure, not an empty economic relationship set.

The focused synthetic graph/document-chat suite passed 19 tests in 17.030 seconds against isolated PostgreSQL and real Neo4j, including a broader graph whose out-of-conversation identity/path is excluded. Actual policy-chat acceptance subsequently passed with fresh native tools and original-page citations: July 5 applicability returns the provisional announcement path; November 1 returns both separate provisional/definitive announcement paths. A real stream-delivery failure was fixed and retained in history before successful retry and production runs. See [checkpoint 2 acceptance](validation/checkpoint-2-rag-graph.md) for identifiers, aggregate checks and unproven broader quality/operational gates. The evaluation center and final release remain pending separate authorization.

```powershell
# copilotkit-app/agent, with the existing local services running
$env:APERTURE_RUN_INTEGRATION='1'
.venv/Scripts/python.exe -m unittest integration_tests.test_graphs -v

# copilotkit-app
npx tsx scripts/test-graph-evidence-selection.mts
```

Graph tests create/drop a uniquely named `aperture_test_*` PostgreSQL database, use synthetic text, and traverse the real local Neo4j service. Cleanup deletes only projection IDs created by that specific test. They do not call a model or claim real financial answer quality. The browser acceptance graph separately uses retained official disclosure originals and user-review operations through the web UI. See the [validation matrix](validation/research-knowledge-validation.md) for observed coverage and outstanding gates.
