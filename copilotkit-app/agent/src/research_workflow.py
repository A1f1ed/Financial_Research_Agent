"""Research execution stays inside LangGraph tools so AG-UI and Inspector see it."""
from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime, timezone
from uuid import uuid4

from copilotkit.langgraph import copilotkit_emit_state
from langchain.tools import ToolRuntime, tool
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
from langchain_core.exceptions import OutputParserException
from langgraph.types import Command

from .model import create_chat_model
from .research_data import collect_evidence
from .research_models import ResearchConfig, AnalystFinding, FinalAssessment, ROLES, DATA_INSTRUCTIONS
from .research_store import get_report, save_report


async def invoke_stage(stage_tool, arguments, config, name=None):
    # Tool-call envelopes make nested backend executions return ToolMessages.
    # The native AG-UI bridge can then emit paired START/ARGS/END/RESULT events.
    actual = stage_tool.model_copy(update={"name": name}) if name and hasattr(stage_tool, "model_copy") else stage_tool
    tool_name = getattr(actual, "name", name or "research_stage")
    result = await actual.ainvoke({"type": "tool_call", "id": str(uuid4()), "name": tool_name, "args": arguments}, config=config)
    return json.loads(result.content) if isinstance(result, ToolMessage) else result

ROLE_GUIDANCE = {
    "fundamentals": "分析已披露的营收、盈利、现金流、负债和商业模式。绝不将报告期末视为发布时间；没有三表时明确无法完整判断。",
    "technical": "只使用代码计算的MA、MACD、RSI、BOLL和收益/回撤。未复权价格存在公司行动影响，不虚构支撑阻力或预测价格。",
    "news": "分析截止日前的已发表新闻和公告，区分报道、公司声明与已核实事实，按时间串联催化剂。摘要型证据不能支持正文中未提供的数字。",
    "sentiment": "仅从已提供的社区样本讨论观点分歧。样本选择偏差不能代表全市场，不编造情绪分数、持仓或资金流。无样本则证据不足。",
    "index": "使用指定基准的同期实际数据。ETF仅为代理，不能把ETF数据说成恒生指数；没有宏观数据就明确未知，不编造利率/VIX。",
    "sector": "仅对用户选择的同业及已提供行业信息分析。两家公司不等于整个板块，不编造行业排名、资金流和市场份额。",
    "bull": "担任多头研究员：提出最有证据支持的乐观论点、成立条件，并逐项回应其他分析师的风险和证据不足。",
    "bear": "担任空头研究员：质疑乐观论点、数据可比性与遗漏风险。每条反驳引用证据或标注为待验证假设。",
    "risk": "担任风险审查员：评估证据质量、基本面/技术面冲突、流动性、公司行动和历史时点泄漏。不执行交易，不随意给仓位。",
}


def validate_citations(result, source_ids):
    data = result.model_dump() if hasattr(result, "model_dump") else dict(result)
    invalid = sorted(set(data.get("source_ids", [])) - set(source_ids))
    data["source_ids"] = [s for s in data.get("source_ids", []) if s in source_ids]
    def clean(value):
        if isinstance(value, str):
            return re.sub(r"\[(S\d+)\]", lambda m: m[0] if m[1] in source_ids else "[未核验证据]", value)
        if isinstance(value, list):
            return [clean(v) for v in value]
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()}
        return value
    data = clean(data)
    if invalid:
        data.setdefault("missing", []).append("模型使用了不存在的证据编号，已移除：" + ", ".join(invalid))
    if not data["source_ids"]:
        data["stance"] = "证据不足"
    return data


@tool
async def retrieve_market_evidence(configuration: dict) -> dict:
    """从 Longbridge 获取只读证据，执行发布时间过滤及技术指标计算；返回缺失项而非补造数据。"""
    return await collect_evidence(ResearchConfig.model_validate(configuration))


@tool
async def analyst_research(role: str, configuration: dict, evidence: dict, prior_findings: dict) -> dict:
    """运行一个专业分析师或多空/风险审查员，返回结论、论据、风险、缺口和可核验引用。"""
    if role not in ROLE_GUIDANCE:
        raise ValueError("Unknown analyst role")
    relevant = {
        "technical": {"prices"}, "index": {"prices", "index", "news"},
        "sector": {"prices", "sector", "news", "filings"},
        "fundamentals": {"fundamentals", "filings", "news", "unlock", "holder_change"},
        "news": {"news", "filings", "billboard", "unlock", "holder_change"}, "sentiment": {"sentiment", "billboard"},
    }.get(role)
    sources = [s for s in evidence["sources"] if relevant is None or s["kind"] in relevant]
    if not sources:
        return {"summary": "所选截止日前没有可用证据，无法完成该项判断。", "stance": "证据不足",
                "findings": [], "risks": [], "missing": ["缺少可验证且带日期的数据"], "source_ids": []}
    model = create_chat_model("openai:qwen3.8-max", max_tokens=3200, timeout=100, max_retries=1, enable_thinking=False)
    structured = model.with_structured_output(AnalystFinding, method="json_mode").with_retry(
        retry_if_exception_type=(OutputParserException,), wait_exponential_jitter=False, stop_after_attempt=2)
    result = await structured.ainvoke([
        SystemMessage(content=f"你是金融研究团队的{ROLES.get(role, role)}。用简体中文。{ROLE_GUIDANCE[role]}\n"
            f"{DATA_INSTRUCTIONS}\n只能使用下方证据；常识可以解释概念，不能充当新的市场事实。每项事实应标注[S编号]。"
            "最多5项主要发现，每项不超过100字。不给胜率、模型置信概率或未经估值的目标价。"
            "龙虎榜同日多个上榜原因可能重叠，不能合计，也不能据此推断全市场资金方向。解禁表示可流通，不等于减持；待发生与历史事件分开。"
            "股东增减持仅为查询窗口内最多8条披露样本。只逐条或按样本描述，不宣称连续、仅有、完整覆盖或计划全部完成。区分公告日和变动区间，勿将多条披露的股数加总。"
            "只输出符合此JSON Schema的JSON对象：" + json.dumps(AnalystFinding.model_json_schema(), ensure_ascii=False)),
        HumanMessage(content=json.dumps({"configuration": configuration, "evidence": sources,
            "data_gaps": evidence["gaps"], "prior_findings": prior_findings}, ensure_ascii=False)),
    ], config={"metadata": {"copilotkit:emit-messages": False}})
    return validate_citations(result, {s["id"] for s in sources})


@tool
async def synthesize_research(configuration: dict, evidence: dict, findings: dict) -> dict:
    """交叉核验分析师、多空辩论及风险意见，生成有条件结论；证据不足时不给虚假精确目标价。"""
    if not evidence["sources"]:
        return {"summary": "在所选信息截止日前没有取得可验证证据，本次无法形成投资研究结论。请查看数据缺口并调整数据授权或研究范围。",
                "stance": "证据不足", "key_points": [], "risks": evidence["gaps"], "catalysts": [],
                "risk_level": "无法判断", "valuation_scenarios": [], "invalidation_conditions": ["取得覆盖所选截止日的有效证据后重新研究"], "source_ids": []}
    model = create_chat_model("openai:qwen3.8-max", max_tokens=6000, timeout=100, max_retries=1, enable_thinking=False)
    structured = model.with_structured_output(FinalAssessment, method="json_mode").with_retry(
        retry_if_exception_type=(OutputParserException,), wait_exponential_jitter=False, stop_after_attempt=2)
    result = await structured.ainvoke([
        SystemMessage(content="你是金融研究负责人。生成中文研究结论而非交易指令。" + DATA_INSTRUCTIONS +
            "仅根据已提供的发现和证据；解释多空分歧，保留不确定性。引用[S编号]。"
            "缺少估值输入/公式则valuation_scenarios留空；无完整风险数据则风险级别无法判断。"
            "不输出模型概率，不声称预测已经验证。主要来源缺失时stance必须证据不足。"
            "对股东增减持只描述已取得的披露样本，不用‘仅有’或‘持续’等表述推断窗口内的完整交易历史。"
            "摘要最多500字；各列表最多5项，每项最多100字；source_ids只列实际引用的来源。保持JSON精简且完整。"
            "只输出符合此JSON Schema的JSON对象：" + json.dumps(FinalAssessment.model_json_schema(), ensure_ascii=False)),
        HumanMessage(content=json.dumps({"configuration": configuration, "findings": findings,
            "sources": [{k:s.get(k) for k in ("id", "title", "kind", "published_at", "event_date")} for s in evidence["sources"]],
            "gaps": evidence["gaps"]}, ensure_ascii=False)),
    ], config={"metadata": {"copilotkit:emit-messages": False}})
    data = validate_citations(result, {s["id"] for s in evidence["sources"]})
    data.pop("missing", None)
    if not any(f.get("source_ids") for f in findings.values()):
        data["stance"], data["risk_level"], data["valuation_scenarios"] = "证据不足", "无法判断", []
    if not configuration["include_risk"]:
        data["risk_level"] = "无法判断"
    return data


@tool
def read_current_research(runtime: ToolRuntime) -> dict:
    """读取当前共享状态里的研究结果与来源，用于报告追问；不发起新的研究或市场查询。"""
    report_id = runtime.state.get("research_qa_report_id")
    report = get_report(report_id) if report_id else runtime.state.get("research")
    if not report:
        return {"message": "当前会话没有研究报告，请先运行研究或从报告库打开一份报告。"}
    return {"id": report["id"], "symbol": report["symbol"], "as_of": report["as_of"],
            "assessment": report.get("assessment"), "findings": report.get("findings"),
            "gaps": report.get("evidence", {}).get("gaps", []),
            "sources": report.get("evidence", {}).get("sources", [])}


@tool
async def run_financial_research(runtime: ToolRuntime, configuration: dict | None = None) -> Command:
    """按用户工作台配置完成金融研究：数据、所选分析师、多空辩论、风险审查、报告入库。没有配置时先向用户确认。"""
    if runtime.state.get("research_qa_report_id"):
        return Command(update={"messages": [ToolMessage(content="请就当前报告提问。如需重新研究，请从单股分析创建任务。", tool_call_id=runtime.tool_call_id)]})
    raw_config = configuration or runtime.state.get("research_config")
    if not raw_config:
        return Command(update={"messages": [ToolMessage(content="请先在研究配置中选择证券、日期和分析师，或在对话里提供配置。", tool_call_id=runtime.tool_call_id)]})
    config = ResearchConfig.model_validate(raw_config)
    report = await execute_research(config, tool_config=runtime.config)
    serialized = report["config"]
    return Command(update={"research": report, "research_config": serialized,
        "messages": [ToolMessage(content=json.dumps({"report_id": report["id"], "status": report["status"],
            "assessment": report["assessment"], "findings": report["findings"], "gaps": report["evidence"]["gaps"]}, ensure_ascii=False),
            tool_call_id=runtime.tool_call_id)]})


async def execute_research(config: ResearchConfig, *, report_id=None, tool_config=None):
    """Run the same evidence pipeline for chat, manual jobs and scheduled jobs."""
    serialized = config.model_dump(mode="json")
    started = time.monotonic()
    stages = ["data", *config.analysts]
    if config.depth != "quick":
        stages += ["bull", "bear"]
    if config.include_risk:
        stages += ["risk"]
    stages += ["synthesis"]
    report = {"schema_version": 1, "id": report_id or str(uuid4()), "symbol": config.symbol, "as_of": str(config.as_of),
        "created_at": datetime.now(timezone.utc).isoformat(), "config": serialized, "status": "running",
        "stages": [{"id": s, "status": "pending"} for s in stages], "findings": {}, "assessment": None,
        "evidence": {"sources": [], "gaps": [], "bars": [], "metrics": {}}, "elapsed_seconds": 0}
    async def update(stage, status, detail=None):
        row = next(s for s in report["stages"] if s["id"] == stage)
        row.update(status=status, updated_at=datetime.now(timezone.utc).isoformat())
        if detail:
            row["detail"] = detail
        report["elapsed_seconds"] = round(time.monotonic() - started, 1)
        save_report(report)
        if tool_config is not None:
            await copilotkit_emit_state(tool_config, {"research": report, "research_config": serialized})
    current = "data"
    try:
        await update("data", "running", "获取带日期的行情、新闻和公告；排除未来及无日期记录")
        report["evidence"] = await invoke_stage(retrieve_market_evidence, {"configuration": serialized}, tool_config)
        await update("data", "complete", f"{len(report['evidence']['sources'])} 条证据；{report['evidence']['excluded_after_cutoff_or_undated']} 条未来/无日期记录已排除")
        for role in stages[1:-1]:
            current = role
            await update(role, "running", ROLE_GUIDANCE[role])
            try:
                finding = await invoke_stage(analyst_research, {"role": role, "configuration": serialized,
                    "evidence": report["evidence"], "prior_findings": report["findings"] if role in ("bull", "bear", "risk") else {}}, tool_config, name=f"analyze_{role}")
                report["findings"][role] = finding
                await update(role, "complete", finding["summary"])
            except asyncio.CancelledError:
                raise
            except Exception as error:
                report["findings"][role] = {"summary": "本阶段模型调用失败，其余阶段继续。", "stance": "证据不足",
                    "findings": [], "risks": [], "missing": [f"阶段错误：{type(error).__name__}"], "source_ids": []}
                await update(role, "failed", f"{type(error).__name__}；未生成替代结论")
        current = "synthesis"
        await update(current, "running", "交叉审查来源、分歧与失效条件")
        report["assessment"] = await invoke_stage(synthesize_research, {"configuration": serialized,
            "evidence": report["evidence"], "findings": report["findings"]}, tool_config)
        covered = sum(bool(report["findings"].get(r, {}).get("source_ids")) for r in config.analysts)
        report["evidence_coverage"] = round(covered / len(config.analysts) * 100)
        report["coverage_definition"] = "所选分析师中产生至少一条有来源发现的比例，不是预测胜率或模型准确率。"
        report["status"] = "partial" if covered < len(config.analysts) or any(s["status"] == "failed" for s in report["stages"]) else "complete"
        await update(current, "complete", report["assessment"]["summary"])
    except asyncio.CancelledError:
        report["status"] = "cancelled"
        await update(current, "cancelled", "用户停止运行，已完成部分已保存在报告库")
        raise
    except Exception as error:
        report["status"] = "failed"
        await update(current, "failed", f"运行失败：{type(error).__name__}；已保留已完成部分")
        raise
    return report
