# Longbridge and the two public-data toolkits

Reviewed 2026-11-06. Scope: current official Longbridge documentation, installed CLI help and connected tool descriptions; upstream `global-stock-data` v2.3.0 and `a-stock-data` v3.10.4 documentation. Toolkit endpoint coverage below is a documentation claim, not a successful execution audit.

**Longbridge is not established as a superset of these two toolkits.** They solve overlapping but different problems. Longbridge provides a unified service/CLI/MCP, while the toolkits aggregate fetching code across external providers. Provider count and endpoint count do not measure comparable completeness, freshness or reliability.

| Workload | Longbridge | Toolkit contribution worth validating |
| --- | --- | --- |
| HK/US/CN company research | Quotes, financials, business segments, analyst estimates, news and filings are exposed. Actual fields/history depend on endpoint and access. | Alternative provider coverage and source cross-checks; do not assume identical adjustment, currency or timestamp semantics. |
| A-share specialist research | Has company/market research tools; a per-feature comparison is needed. | `a-stock-data` documents limit-up pools, trading disclosures, investor Q&A, research-report lists, pledges, buybacks, convertible bonds and Chinese futures/commodity sources. |
| Global macro and cross-asset context | Macro data/calendar tools exist, so macro should not be described as categorically absent. | `global-stock-data` explicitly documents BLS/ETA, BIS/ECB/Fed/NY Fed, Treasury, CFTC and EIA source routes. Validate series, revision and release-date semantics individually. |
| US regulatory research | Filings, insiders and institutional research tools are exposed. | `global-stock-data` documents EDGAR full-text/events, XBRL cross-sectional frames and filing parsers; useful for bulk source-level retrieval if validated. |
| Real-time application features | Official docs expose subscriptions, depth and quote/option/warrant APIs; account permissions still apply. | Public HTTP fetching code does not itself establish an equivalent streaming service or uptime commitment. |
| RAG / GraphRAG / vision | Filing discovery is useful and was used to locate originals for this corpus. | API breadth does not replace preserved issuer/exchange originals, versioned publication dates, page citations, OCR and entity validation. |

## Proposed routing for this project

1. Preserve Longbridge as the existing company research adapter.
2. Add small, separately validated adapters for A-share specialist features and global official macro/regulatory sources when a concrete product feature needs them.
3. Normalize symbol, exchange, currency, units, timezone, publication/observation/fetch times, adjustment basis, provenance and access status in every adapter response.
4. Distinguish `not_available`, `not_authorized`, `rate_limited`, `source_error` and `empty_result`. A source outage must not become a financial conclusion.
5. Apply timeouts, caching, source-specific rate limits and circuit breakers. Fallback only between semantically compatible datasets; otherwise surface the difference to the agent.
6. Preserve source PDFs and immutable page IDs for document research. Keep original and extracted facts separate; require evidence for graph edges and wiki edits.

This is an architecture recommendation, not a claim these adapters have been installed. The external SKILL files were inspected as documentation, not applied as instructions or executed.

## Important limits

- Public accessibility / zero authentication is not a blanket commercial redistribution license. The global toolkit itself distinguishes source terms, including restricted sources.
- A-stock-data describes modeled chip distributions; these are not observed beneficial ownership data. Its changelog also documents interface breakage and volume-unit corrections.
- Longbridge feature exposure is not proof that every market, security and historical range is covered by the current account. Conversely, an untested Longbridge feature should not be labeled missing.
- No exhaustive live endpoint benchmark was performed for either toolkit. The corpus collection verifies only the primary documents saved locally, not all advertised market-data endpoints.

## Primary references

- [Longbridge OpenAPI overview](https://open.longbridge.com/docs)
- [global-stock-data SKILL.md](https://github.com/simonlin1212/global-stock-data/blob/main/SKILL.md)
- [a-stock-data SKILL.md](https://github.com/simonlin1212/a-stock-data/blob/main/SKILL.md)

Local documentation snapshots, retained under ignored `local-data/finance-research-v1/discovery/`, have SHA-256:

| Snapshot | SHA-256 |
| --- | --- |
| global-stock-data | `19afb506c27f94b2a252131db42fedd298b0c747da3e4f6a22f9c5eb963535d3` |
| a-stock-data | `09f7e8a3f826f747d293a1e86883003dbda932cf7fdd9e61714077ba057bf0f2` |
