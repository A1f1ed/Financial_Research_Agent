# Aperture · Finance Research Agent

[English documentation](../README.md) | [简体中文](../README_zh-CN.md)

The main application lives in this directory. See the repository README for interface previews, features, data sources, supported AI providers, architecture and setup details.

For a fresh clone, from this directory:

```powershell
Copy-Item .env.example .env
npm ci
npm run build
npm run start:all
```

Keep an existing `.env` intact. Open http://localhost:3000, then configure Qwen, DeepSeek or GLM under **Settings → AI settings**. Test a short greeting before saving and activating the provider. Primary market data requires your own authorized Longbridge CLI.

English is the default interface language; use **EN / 中文** beside the theme button to switch. Reports retain their original text.

[Validation notes](VALIDATION.md) · [Research roadmap](RESEARCH-ROADMAP.md) · [License](LICENSE)
