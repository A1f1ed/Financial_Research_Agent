# Aperture · Finance Research Agent

[English documentation](../README.md) | [简体中文](../README_zh-CN.md)

The main application lives in this directory. See the repository README for interface previews, features, data sources, supported AI providers, architecture and setup details.

For a fresh clone, from this directory:

```powershell
Copy-Item .env.example .env
npm ci
npm run infra:init
npm run services:up
docker compose --env-file ../infra/.env -f ../infra/compose.yaml --profile application exec api longbridge auth login
npm run build
npm run start:all
```

Keep an existing `.env` intact. Docker's Linux engine must be running. Open http://localhost:3000, then configure Qwen, DeepSeek or GLM under **Settings → AI settings**. Authorize Longbridge in the container, not by copying host tokens. Existing installations must follow the verified migration/cutover procedure in [infra/README](../infra/README.md). Automatic schedules start paused; manual runs remain available.

English is the default interface language; use **EN / 中文** beside the theme button to switch. Reports retain their original text.

The online **Stock research → Document library** accepts new PDFs/images and supported official file links, with independent processing tasks, original-page previews, metadata revisions, file versions and archive/restore. See [Document library](../docs/document-library.md) for limits, native document Q&A and VPN DNS configuration. Visual verification remains work in progress.

**Knowledge base** provides persistent company/topic collections with exact-version membership, shared original reuse, metadata and membership audits, batch removal, archive/restore, actual extraction coverage and market/date-bounded scope checks. These checks do not call a model or imply a completed semantic index.

Within a collection, **Search original evidence** supports explicit durable index builds, keyword search without model calls, and pgvector hybrid retrieval after an independent embedding capability test under AI settings. Results retain exact document/page/quote references and open the cited page. **Ask about these documents** creates native CopilotKit Q&A with a server-owned scope. Full answer quality, typed calculations and broader research integration remain pending.

**GraphRAG → Graph management / Relationships & paths** now provides the first reviewed graph workflow: pinned sources, evidenced identities/candidates, versioned review, durable Neo4j synchronization, bounded traversal, Cytoscape interaction and saved historical paths. Automatic extraction and explicit identity review are implemented with focused tests; their real-model browser acceptance is pending. See [Graph research](../docs/graph-research.md) and the [four-checkpoint delivery plan](../docs/releases/knowledge-v0.2.md). Full graph acceptance and in-app evaluation remain unfinished; advanced identity merge/split is deferred to a later release.

[Validation notes](VALIDATION.md) · [Research roadmap](RESEARCH-ROADMAP.md) · [License](LICENSE)
