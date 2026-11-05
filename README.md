# Aperture Financial Research

金融研究工作台，基于 CopilotKit、Next.js、LangGraph / FastAPI 和 Qwen。

当前发布版本为 **v0.1.0**，应用位于 [copilotkit-app](copilotkit-app/README.md)。仓库根目录同时保留早期工作台源码。

## 运行当前版本

需要 Node.js 20.19+、Python 3.12+、uv 和已授权的 Longbridge CLI。

```powershell
cd copilotkit-app
Copy-Item .env.example .env
# 在 .env 填写自己的模型和 CopilotKit Intelligence 配置
npm ci
npm run build
npm run start:all
```

打开 http://localhost:3000 。开发模式使用 `npm run dev`。

## 功能

- 原生 CopilotKit 聊天、工具过程、流式输出、Inspector 和报告问答。
- 多分析师单股研究、日期边界、来源证据和 MD / JSON / PDF 导出。
- 沪深收盘复盘、市场情绪、行业走势、候选池与观察历史、条件核对。
- 定时晨报、要闻、公告、自选监测和周复盘，支持开收盘时点及手动试跑。
- 报告库检索、同一标的的双报告对照、深浅主题和手机布局。

此版本面向单用户本机运行。模型和市场数据需要使用者自行配置授权。密钥、会话、研究数据库和本机缓存由各自环境保存。

完整配置与运行边界见 [应用说明](copilotkit-app/README.md)，验证记录见 [VALIDATION](copilotkit-app/VALIDATION.md)，迭代记录见 [研究路线图](copilotkit-app/RESEARCH-ROADMAP.md)。
