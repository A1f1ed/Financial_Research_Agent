# 金融研究 Agent

Python 3.12+，LangGraph create_agent + CopilotKitMiddleware，FastAPI / AG-UI。

main.py 先读取服务端环境，再在 FastAPI lifespan 中建立 AsyncPostgresSaver 与 graph。
业务数据使用 SQLAlchemy/PostgreSQL；缓存使用 Redis；任务通过 outbox、RabbitMQ/Celery 独立执行。没有 SQLite 运行回退。
正常开发从应用目录运行 npm run services:up，再运行 npm run dev:ui。GET /health；GET /research/status。
初始化服务显式运行 Alembic 与官方 checkpoint setup，HTTP 请求不自动建表。
POST / 为 AG-UI Agent 入口；/research/reports 提供本机报告库和 MD/JSON/PDF 导出。

src/research_models.py 定义配置与输出契约；research_data.py 负责只读CLI、时间过滤和指标；
research_workflow.py 负责实际专业分析、多空与风险工具；research_store.py 存储报告；research_exports.py 导出。

运行测试：.venv/Scripts/python.exe -m unittest discover -s tests -v。需要真实 PostgreSQL、Redis；测试使用独立 aperture_test_* 库和缓存前缀。
SQLite 依赖仅在 dev 组提供离线迁移及恢复核对。参见 ../../infra/README.md 和 ../../docs/validation/。

在线研究资料库：`/research/documents`，支持网页上传、官方链接导入、原页预览、元数据审计、文件版本及归档恢复。
独立 `documents-worker` 处理文字页；图片页标记需要视觉识别，不假装已建语义索引。参见 [资料库说明](../../docs/document-library.md)。
