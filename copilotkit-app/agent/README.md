# 金融研究 Agent

Python 3.12+，LangGraph create_agent + CopilotKitMiddleware，FastAPI / AG-UI。

main.py 先读取应用根目录 .env，再在 FastAPI lifespan 中建立 AsyncSqliteSaver 与 graph。
从应用根目录运行 npm run dev:agent 。GET /health；GET /research/status。
POST / 为 AG-UI Agent 入口；/research/reports 提供本机报告库和 MD/JSON/PDF 导出。

src/research_models.py 定义配置与输出契约；research_data.py 负责只读CLI、时间过滤和指标；
research_workflow.py 负责实际专业分析、多空与风险工具；research_store.py 存储报告；research_exports.py 导出。

运行测试：.venv/Scripts/python.exe -m unittest discover -s tests -v
