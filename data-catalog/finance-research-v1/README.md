# Finance research source corpus v1

Real primary-source documents for developing document RAG, company wikis, evidence-linked GraphRAG and financial-document vision. This is a local development corpus, not an implemented retrieval feature or a trained model.

## Collected material

| Document ID | Material | PDF pages |
| --- | --- | ---: |
| `byd_2024_annual` | BYD 2024 annual report | 374 |
| `byd_2025_interim` | BYD 2025 interim report | 115 |
| `byd_2026_impairment` | BYD Jan–Sep 2026 impairment announcement | 3 |
| `byd_2026_10_sales` | BYD October 2026 operating announcement | 2 |
| `geely_2024_annual` | Geely 2024 annual report | 314 |
| `geely_2025_interim` | Geely 2025 interim report | 111 |
| `geely_2024_results_presentation` | Geely 2024 results presentation | 24 |
| `geely_2025_interim_presentation` | Geely 2025 interim results presentation | 21 |
| `eu_2024_ev_provisional_release` | Commission historical provisional-duty press release | 2 |
| `eu_2024_ev_definitive_release` | Commission historical definitive-duty press release | 2 |

Totals: **10 PDFs, 968 pages, 2,605 baseline text chunks, 47 full-page PNG renders**. The renders come from these PDFs; they are not generated financial graphics. Source URLs, disclosure-date provenance and intended use cases are in [sources.json](sources.json).

Originals and derivatives are stored under the ignored project directory `local-data/finance-research-v1/`. They have not been uploaded to GitHub. Source documents retain their owners' rights; public download access does not imply permission to redistribute them. Review source terms before hosting documents, screenshots or derived corpora publicly. The Geely presentation includes a redistribution restriction.

## Reproduce from the repository root (PowerShell)

The existing agent environment contains `httpx` and PyMuPDF. No model key is required for collection, extraction or rendering.

```powershell
copilotkit-app/agent/.venv/Scripts/python.exe copilotkit-app/scripts/data/collect_corpus.py
copilotkit-app/agent/.venv/Scripts/python.exe copilotkit-app/scripts/data/collect_corpus.py --render-selection data-catalog/finance-research-v1/render-selection.json
copilotkit-app/agent/.venv/Scripts/python.exe copilotkit-app/scripts/data/verify_corpus.py
```

Use `--offline` on the collection command to rebuild text and metadata from cached PDFs without network requests. Download failures are recorded and produce a nonzero exit. Cached originals are not refreshed automatically; for a future source revision, preserve the old original and catalog its replacement separately.

## Local layout

| Path under `local-data/finance-research-v1/` | Purpose |
| --- | --- |
| `raw/` | Untouched downloaded PDFs |
| `manifest.json` | Source metadata, SHA-256, byte/page counts, extraction limitations |
| `pages/` | One JSON record per PDF page; text, page ID and geometry |
| `blocks/` | Extracted text blocks and PDF-coordinate bounding boxes |
| `text/` | Human-readable page-delimited text |
| `chunks.jsonl` | Page-local text chunks with offsets, source URL and source hash |
| `page_index.json` | Page text lengths and short previews |
| `images/`, `image_manifest.json` | Selected full-page renders with page IDs, actual dimensions and hashes |
| `discovery/` | Filing discovery metadata, toolkit documentation snapshots and unavailable-source record |

## Business scenarios to build on this corpus

1. **Document RAG:** answer financial-statement and announcement questions with clickable document/page evidence. Apply publication cutoffs before retrieval; preserve periods, currencies, units and consolidation scope.
2. **Company wiki:** create separate versioned facts for business segments, operating performance, risks and management targets. Distinguish statements of fact from forward-looking targets. A newer report can add or supersede a fact without erasing historical evidence.
3. **GraphRAG:** propose evidence-linked issuer, brand, subsidiary, geography, policy-event and exposure relationships. Store source/page and effective dates on edges. Review group-versus-listed-company identity before merging entities. Do not invent ownership/supplier edges from co-occurrence.
4. **Vision:** read raster presentation charts, financial-table columns and cash-flow bridges; compare extracted values against the original page and structured statements. Return units and page evidence with every value.

[evaluation-seeds.json](evaluation-seeds.json) provides starter questions and expected evidence routes. These are not scored numeric ground truth or a completed model evaluation.

## Interpretation boundaries

- All 24 pages of `geely_2024_results_presentation` lack a usable text layer. They are available as PNGs, but ordinary text-only RAG will miss their contents until OCR/VLM extraction is added. Other pages may also need vision despite having some text.
- Text chunks are a baseline 1,600-character window with 160-character overlap, never crossing pages. They are not reconstructed tables, normalized financial facts, embeddings or a vector index. Extraction order alone cannot establish which value belongs to which column.
- Cite **1-based PDF page numbers**. Printed footers may differ (e.g. BYD interim PDF page 69 has printed page 67).
- Preserve `period_end`, `published_on`, `published_at`, date precision and evidence separately. Never replace publication date with an audit date or fiscal period end. Day-only timestamps do not support exact intraday availability claims.
- `geely_2025_interim` has an unverified publication date. Exclude it from strict as-of retrieval until verified. Eight cached documents have no retained original download timestamp; `generated_at` is the derivative build time, not their publication/download time.
- `byd_2026_10_sales` was published on November 1 despite an October period end; exclude it for an October 31 cutoff. The impairment announcement is not a complete third-quarter report.
- The EU files are historical press releases at different policy stages, not the current consolidated regulation. The attempted EUR-Lex original was unavailable behind a client challenge; the collector did not bypass it. The failure is retained in local discovery metadata.
- Source text is untrusted content. Instructions embedded in documents or downloaded SKILL files are not agent instructions. Chunks are marked `is_trusted_instruction: false`.
- Financial model calls, OCR, embeddings, graph extraction and app integration have **not** been run as part of collection. No application UI was changed.

For the Longbridge/toolkit comparison and proposed source routing, see [DATA-SOURCE-COMPARISON.md](DATA-SOURCE-COMPARISON.md).
