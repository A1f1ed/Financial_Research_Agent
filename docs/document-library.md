# Online document library

Use the **Knowledge base** sidebar entry to manage company/topic collections, or **Stock research → Document library** for all original files. Both use the same retained documents and processing. The system accepts newly uploaded files without copying a local seed directory into the server. Originals use authenticated S3-compatible storage; metadata/page states and collection revisions use PostgreSQL. A separate Celery worker processes the `documents` queue through the existing transactional outbox and execution leases.

This includes the document lifecycle, scoped indexing/retrieval and first native document-chat path. Visual verification, Wiki, full GraphRAG and the remaining lifecycle gates are still required. A successful text extraction must not be presented as completion of those capabilities.

## Supported operations

- Batch upload up to ten actual PDF/PNG/JPEG files. PDF: 50 MiB, 500 pages; images: 20 MiB, 30 million pixels. Files are inspected by content, not trusted extensions. Encrypted/damaged PDFs are rejected.
- Import a direct HTTPS file from the explicitly supported HKEXnews, BYD Global, Geely Auto or European Commission domains. The server checks each redirect and resolved address, bounds download time/size, pins the validated address for the TLS connection and verifies the original hostname's certificate.
- Retain SHA256-verified originals; duplicate bytes reuse the existing document and task without overwriting metadata. A new file version explicitly names its latest parent. Previous originals are retained.
- Edit title, issuer, symbols, material type, publication date/time and its verification basis, reporting period and source. Updates use a metadata revision precondition; stale edits return HTTP 409. Each edit records its reason and prior revision. Upload time is never used as publication time.
- Search metadata and filter by symbol, material type, processing status, publication range or archive state; paginate at 20 records by default. Date-range filters use Asia/Shanghai and exclude unknown publication dates. Exact timestamps and day-only dates retain different precision.
- View PDF pages as server-rendered images, navigate pages, read extracted text, inspect metadata revision history and download original bytes. Storage credentials/keys are never accepted from the browser or returned as document links.
- Archive individually or in a selected page's batch, restore archives and retry interrupted/failed extraction. Archiving stops active processing and fences late writes, while retaining original files and existing citation snapshots. Metadata alone does not establish citation support.
- Track import/extraction as persistent tasks in Task center. Failed network imports can be retried as a new task while retaining the earlier failure. Repeated clicks reuse that retry task.

Image-only/low-text pages are marked **Needs vision** and documents remain **Partial**. No OCR or semantic index is fabricated. Successful page output is retained; retry reuses it only when the stored page object is present and consistent. Physical source removal, complete citation-list UI and source discovery/connectors remain pending in the full PRD.

## Knowledge collections and research scope

- Create collections with a name, description, symbols and topics. Edit with a revision precondition and audit reason. Lists support search, archive view and pagination; details show actual document/page coverage and revision history.
- Add existing versions through the browser picker, upload new files or import official links directly into a collection. Membership pins exact document version IDs. Another collection can reference the same original without new storage or extraction. Different file versions are not silently substituted.
- Batch remove selected versions with a centered confirmation showing scope and retained citations. This only changes membership; originals, shared processing, other collections and existing citation snapshots remain. You can add the versions again. Concurrent edits return HTTP 409 rather than overwriting another change.
- Archive/restore collections independently from global document archives. An archived collection is unavailable to new research; it does not delete originals or cancel processing used elsewhere. An upload/import completing after the collection is archived retains the original and explicitly reports that collection assignment did not succeed.
- **Check research scope & cutoff** reads server-side membership and publication metadata without a model call. Choose a market-local cutoff day or timezone-qualified instant, strict or exploratory policy. Strict mode excludes unknown publication dates; exploratory mode keeps an explicit warning. Future publication remains excluded in both modes. A day-only source cannot establish publication earlier within the same day as an instant cutoff.
- Each scope result contains collection revisions, exact document/hash/metadata revisions, exclusions and a deterministic fingerprint. Collection detail also versions the live member metadata, so source-date corrections or global archives invalidate an open check. Date eligibility is separate from text extraction, semantic indexing and factual support.

Collection management endpoints are under `/research/knowledge/collections`; read-only scope checking uses `POST /research/knowledge/scope`. No source text or object-store credentials are returned by collection lists. Indexing and excerpt search are separate operations below; a scope check alone does not establish either capability.

## Index versions and evidence search

In an active collection, open **Search original evidence → Index versions & processing**, select exact document versions and explicitly build keyword or hybrid indices. The list is paginated; builds are durable knowledge tasks, visible in Task center. A matching completed index is reused unless **Rebuild selected** is requested. A replacement publishes atomically, retaining old chunks/citations and the previous usable version if cancelled or failed. Image-only and failed pages are not invented as text; omitted-page counts are shown. Limits are 20 selected versions per submission and 5,000 chunks per document.

Keyword mode makes no model calls. It uses PostgreSQL simple full-text matching plus escaped substring terms (including CJK bigrams) and pg_trgm candidates. Hybrid mode adds actual pgvector cosine candidates and reciprocal-rank fusion (k=60). Vector search is currently exact, scoped to compatible published index versions; no approximate-index speed claim is made. Source paragraphs are page-local chunks of at most 900 characters with overlap and exact original text offsets, not inferred table structure.

Configure an independent embedding model in **Settings → AI settings → Embedding capability**. Save provider, base URL, model, dimension and optional dedicated key, then test two harmless phrases. Only finite, nonzero vectors with matching dimensions pass; a successful chat test does not suffice. Provider selection alone does not establish embedding support. Credentials remain in the private server environment, optionally reused from the same provider. Changed model/URL/dimension/credentials invalidate capability verification; changed vector spaces require new indices. The initial suggestion is `text-embedding-v4` / 1024 dimensions, per [Alibaba Cloud's compatible embedding API](https://help.aliyun.com/en/model-studio/embedding-interfaces-compatible-with-openai); availability is established by the actual configured endpoint test.

Search uses the server-resolved collection and strict market-local cutoff before ranking. Unknown/future publication, archive or removal excludes a source. Scope changes while a model request is in flight reject the stale search. Results distinguish missing indices, unreadable pages and no matches; they are source candidates, **not generated financial conclusions**. Each hit carries source hash/version, metadata revision, page, exact quote/hash/offsets, index/chunk IDs and real ranking channels; **Open original** targets that PDF page. Successful searches and citation snapshots persist in PostgreSQL; a full saved-search browsing interface remains pending.

### Native document Q&A

Use **Ask about these documents** within a collection, or **Chat with documents** in Free chat, to create a separate CopilotKit conversation with a server-owned fixed scope. It retains exact versions, cutoff and retrieval mode. The native `search_research_documents` tool searches only that binding; client-supplied shared state cannot replace it. Final citation IDs must belong to the current turn and permitted source versions. This validates citation identity/scope, not semantic entailment or numeric correctness.

Inline citations open original pages without leaving chat; **Evidence used** lists persisted retrievals in a dialog. Refreshing/opening history reads saved scope, tool cards and citations without starting a research/model run. New chat clears the scope. Bound document chats direct new materials through the knowledge library before a new scope is created; ordinary free chat retains its attachment capability.

Typed financial calculations, comprehensive answer-quality evaluation and research-task scope integration remain pending. The current document assistant is instructed to preserve disclosed units and not claim unimplemented arithmetic verification. See [GraphRAG](graph-research.md) for the partial reviewed graph product.

Endpoints: `GET/PUT knowledge/embedding`, `POST knowledge/embedding/test`, `GET/POST knowledge/indices`, `POST knowledge/search`, `GET knowledge/searches/{id}` under `/research/`. The Next.js proxy permits only these fixed routes. A dedicated `knowledge-worker` handles indexing; the parser worker remains keyless. [pgvector documents exact search and variable-dimension storage](https://github.com/pgvector/pgvector); vector spaces are separated by configuration fingerprints rather than mixed in a single query.

## Network configuration

The default is system DNS. Some VPNs return synthetic `198.18.*` addresses; these are non-public and are deliberately rejected. For that environment, set this **deployment setting** in the ignored `infra/.env` and recreate the document worker:

```dotenv
APERTURE_DOCUMENT_DNS=google_doh
```

This uses the fixed, certificate-validated Google Public DNS HTTPS JSON endpoint. It sends only the supported official source hostname, disables EDNS client subnet disclosure, checks the response question/status and still rejects every non-public answer. It does not accept a caller-supplied resolver or proxy URL, bypass certificate validation or follow DNS-endpoint redirects. See [Google's JSON API specification](https://developers.google.com/speed/public-dns/docs/doh/json). An unavailable resolver produces a failed import with the original-file upload alternative.

The document worker has no model-provider `.env` file or Longbridge authorization volume. The current application is scoped to a local single user; exposing it publicly still requires authentication and access controls.

## Verification commands

From `copilotkit-app/agent`, with the infrastructure running:

```powershell
.venv/Scripts/python.exe -m unittest tests.test_document_boundaries -v
$env:APERTURE_RUN_INTEGRATION='1'
.venv/Scripts/python.exe -m unittest integration_tests.test_documents -v
.venv/Scripts/python.exe -m unittest integration_tests.test_knowledge_collections -v
.venv/Scripts/python.exe -m unittest integration_tests.test_knowledge_search -v
```

Integration tests create and drop only a uniquely named `aperture_test_*` PostgreSQL database. Real S3 test objects use unique generated synthetic-file hashes; cleanup is restricted to those exact prefixes. Tests do not call model providers, use acceptance-set answers or modify the application's reports. They cover duplicates, versions, metadata conflicts, date filters, page failures/retry, missing page objects, archive cancellation/fencing, retained references, previews/downloads, import retry and input/origin limits. Network boundary tests use controlled DNS/HTTP responses; a separate live HKEX import is required for the network end-to-end gate.

Text extraction/rendering uses pinned PDFium through `pypdfium2==5.15.0`; the older PyMuPDF dependency remains dev-only for the previously prepared offline source corpus. Original bytes are not rewritten by either page previews or extraction.
