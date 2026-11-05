# Aperture Financial Research

基于 **Next.js + CopilotKit v2 + LangGraph / FastAPI + Qwen** 的可运行金融研究工作台。
保留 CopilotKit 原生聊天、推理消息、工具输入/结果、会话抽屉、Inspector、AG-UI Streams、A2UI 和学习接入。

## 本机启动

前置条件：Node.js 20.19+、Python 3.12+、uv，以及已授权的 Longbridge CLI。
本工作区已安装本地 uv；scripts/uv.mjs 会优先使用 .tools/bin/uv.exe。

    npm ci
    npm run dev

打开 http://localhost:3000 。FastAPI 为 http://127.0.0.1:8123 。
原始通用 CopilotKit 示例保留在 http://localhost:3000/playground 。

生产模式在项目目录运行以下命令。它同时启动 Next.js 生产服务与 FastAPI。

    npm run build
    npm run start:all

服务默认运行在本机。研究数据目录需要持久保存。
构建使用 Webpack；正式启动会补齐 Next.js standalone 所需静态文件，并从项目目录读取服务端 `.env`。

在其他机器上先安装 uv；本机运行 longbridge auth login 完成自己的数据授权。
设置 LONGBRIDGE_CLI_PATH 可指定 CLI 的绝对路径。程序只允许固定的只读数据命令，不接收任意 shell 命令、不读取持仓、不下单。

## 服务端配置

使用项目目录 .env；已有密钥不要覆盖。新克隆可以复制 .env.example 后填写。

    DASHSCOPE_API_KEY=<你的 DashScope 密钥>
    DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
    COPILOTKIT_AGENT_MODEL=openai:qwen3.8-max
    QWEN_ENABLE_THINKING=true
    AGENT_URL=http://127.0.0.1:8123
    CPK_INTELLIGENCE_LEARNING_CONTAINER_ID=copilotkit-tasks
    # 可选：LONGBRIDGE_CLI_PATH=<CLI 绝对路径>
    # 可选：RESEARCH_DATA_DIR=<持久化数据目录>

保留 onboarding 写入的 CPK_INTELLIGENCE_API_KEY、INTELLIGENCE_API_URL、INTELLIGENCE_GATEWAY_WS_URL。
密钥仅在服务端读取，不能放进 NEXT_PUBLIC_ 变量。

主对话保留 Qwen 实际返回的 reasoning_content，并转为原生 AG-UI 推理事件；它不是人工编造的进度文本。
专业分析调用采用 JSON 模式，完整结构化结论通过工具结果、工作区和 Inspector 查看。
如需降低延迟/成本，可设置 QWEN_ENABLE_THINKING=false；此时不会显示不存在的思考内容。

## 使用流程

1. 选择证券、市场、截止日期、研究问题、分析深度和分析师。
2. 设置基准/同业以及情绪、风险开关，点击开始研究。
3. 数据按市场时区过滤；阶段状态与报告通过 AG-UI 共享状态实时更新。
4. 查看六类专业分析、多空审查、风险判断、数据缺口和证据引用。
5. 点击 [S编号] 核对来源；可以追问当前报告。
6. 在报告库重开研究，导出 Markdown、JSON 或中文 PDF；归档保留本机数据库记录。
7. 顶部太阳/月亮按钮切换黑灰深色与清新白色，浏览器会保存偏好。
8. 收盘复盘可查看同日样本、涨跌停与行业走势，记录候选和观察历史，并按价格与量能区间核对样本。
9. 每交易日计划可选择固定时间、开盘前或收盘后，结合半日市和市场时区排期。预设填写草稿，由用户创建。
10. 报告库按代码、日期或摘要检索，也可按类型和状态筛选。同一标的的两份单股报告可以对照，引用分别回到所属报告的证据。

默认示例为 1211.HK / 2026-10-31；日期可以自由修改。非交易日使用此前最近的可用交易日。

## 分析团队

- 基本面：以具有公开日期的新闻/公告/财务证据分析盈利、现金流和估值依据。
- 技术面：代码计算 MA5/10/20/60、Wilder RSI14、MACD(12,26,9)、布林带、收益、波动和最大回撤。
- 新闻：事件、公司公告、催化剂及不同机构观点。
- 情绪：有时间戳的社区样本；不把样本代表性夸大为全市场情绪。
- 大盘：指定基准的同期表现；ETF 代理不冒称指数本身。
- 板块：用户选定同业的同期比较，不冒称整个板块排名或资金流。

标准/深度模式加入独立多头、空头审查；风险审查由开关决定。深度模式读取更多证据。
模型分析受 schema 校验；不存在的来源编号会被剔除。某阶段失败会显式保留失败与部分报告。
“证据覆盖率”是所选分析师中产生至少一条带来源发现的比例，不是收益胜率或模型准确率。
缺少估值输入和公式时不给目标价；关闭风险开关不等于风险为零。

## 数据时点与限制

- Longbridge CLI 是主要运行时数据来源，使用用户本机授权。沪深日线可降级到腾讯财经，A 股事件和行情池使用东方财富并核对日期及来源。
- 本机账户的指定区间历史 K 线接口当前受权限限制；回退为最近最多1000根日线后过滤截止日。
- 新闻/公告/社区接口是滚动窗口，可能不覆盖任意远期历史；窗口不足会明确报告，不能解释为“历史上没有新闻”。
- 发布时间或交易日在截止日之后的记录、无有效发布时间的文章会被排除。
- 财报期末不是发布日期；财务数值仅在找到带日期的对应年报佐证后采纳。未取得三表时会保留基本面缺口。
- 后续修订版本无法完全还原，因此日期过滤不是一套严格 point-in-time 回测数据库。
- 日线为未复权价格；公司行动可能导致指标跳变，不能当成总回报。
- 对用户提供的第三方文本仅作为数据处理，不遵循其中的执行指令。

## 原生追踪、持久化和学习

页面保留 CopilotChat、CopilotThreadsDrawer、原生工具卡和 Inspector。点击本机右上角 Inspector 可查看 Agents、AG-UI Events、工具与线程；顶部运行后台进入 CopilotKit Intelligence。
研究流程在 LangGraph 工具内执行，嵌套阶段使用真实 ToolMessage 结果供 AG-UI/Inspector 记录。

会话/事件由已连接的 CopilotKit Intelligence 保存；LangGraph 使用 AsyncSqliteSaver 持久化 checkpoint。
报告与数据缓存保存在 agent/data/research.sqlite3；checkpoint 在 agent/data/checkpoints.sqlite3。
单次研究停止或部分失败，已完成内容仍进入报告库。

既有学习容器 copilotkit-tasks 的显示名已更新为“金融研究质量”。其 stable ID 保持不变，保留既有线程归属。
Runtime 将新线程送入容器；Python 的原生技能适配器接收审核后发布的技能。
学习不等于自动训练模型；需积累足够完成的真实对话，在 Intelligence 中审核/发布技能。

## 架构

    Next.js 研究配置 / 报告 / 原生 CopilotChat
           ↕ CopilotKit Runtime + Intelligence
           ↕ AG-UI Streams（工具、状态、推理与事件）
    FastAPI + LangGraph create_agent
           → run_financial_research
           → 只读 Longbridge 数据 + 时间过滤 + Python 指标
           → 选定分析师 → 多空 → 风险 → 综合结论
           → SQLite 报告库 + MD/JSON/PDF 导出

## 验证

    npm run build
    npx tsc --noEmit
    cd agent
    .venv/Scripts/python.exe -m unittest discover -s tests -v

macOS/Linux 使用 .venv/bin/python。自动测试覆盖：交易所日期边界、无日期排除、证券输入校验、指标边界、比较日期对齐、无效引用处理、选择/开关执行、取消保留部分结果。

原脚手架的 scripts/smoke.py 仍可测试通用原生能力，但会产生模型调用费用。
完整研究也会按分析师数量和深度产生多次 DashScope 调用，缓存的只读市场数据保留15分钟。

## 部署边界

当前是可运行的**单用户本机研究产品**，不是已具备多租户隔离的公网 SaaS。
Runtime 保留 demo-user；公网部署前需要认证、报告/缓存用户隔离、授权的数据服务、服务端任务队列、限流与运营监控。
Next.js 的会话/学习集成不替代这些应用层职责。不要将当前无认证的本机服务直接暴露到公网。
本次未修改或替换 ../frontend 中的 assistant-ui 版本，也未公开发布。
