import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from backend.agent import calculate_financial_metrics, choose_start, graph
from backend.financial_data import ALLOWED_TOOLS, FinancialData
from backend.gateway_model import to_model_messages


def test_deep_research_requires_approval():
    assert choose_start({"messages": [HumanMessage(content="研究")], "mode": "深度研究"}) == "plan"


def test_quick_research_skips_approval():
    assert choose_start({"messages": [HumanMessage(content="概览")], "mode": "快速概览"}) == "research"


@pytest.mark.parametrize("value, expected", [(True, "research"), (False, "cancel"), ("yes", "cancel")])
def test_only_explicit_approval_continues(value, expected):
    message = ToolMessage(content=json.dumps({"approved": value}), name="approve_research_plan", tool_call_id="approval")
    assert choose_start({"messages": [message]}) == expected


def test_ag_ui_approval_without_tool_name():
    proposal = AIMessage(content="确认计划", tool_calls=[{"id": "approval", "name": "approve_research_plan", "args": {}}])
    declined = ToolMessage(content='{"approved": false}', tool_call_id="approval")
    assert choose_start({"messages": [proposal, declined]}) == "cancel"


def test_ag_ui_decline_never_invokes_model():
    async def run():
        config = {"configurable": {"thread_id": "test-decline-checkpoint"}}
        messages = [AIMessage(content="确认", tool_calls=[{"id": "approval", "name": "approve_research_plan", "args": {}}]), ToolMessage(content='{"approved": false}', tool_call_id="approval")]
        result = await graph.ainvoke({"messages": messages}, config)
        assert result["stage"] == "cancelled"
        assert "不会继续调用模型" in result["messages"][-1].content
    asyncio.run(run())


def test_tool_message_bridge():
    messages = [SystemMessage(content="研究"), HumanMessage(content="计算"), AIMessage(content="", tool_calls=[{"id": "call1", "name": "calculate_financial_metrics", "args": {}}]), ToolMessage(content='{"value": 0.2}', tool_call_id="call1")]
    result = to_model_messages(messages)
    assert result[2]["content"][0]["type"] == "tool-call"
    assert result[3]["content"][0]["output"] == {"type": "json", "value": {"value": 0.2}}
    assert result[3]["content"][0]["toolName"] == "calculate_financial_metrics"


def test_financial_calculation():
    result = asyncio.run(calculate_financial_metrics.ainvoke({"previous_revenue": 100, "current_revenue": 120, "cost_of_revenue": 60}))
    assert result["revenue_growth"] == pytest.approx(0.2)
    assert result["gross_margin"] == pytest.approx(0.5)


def test_no_execution_tools_exposed():
    assert not ALLOWED_TOOLS & {"bash", "write_file", "trading_place_order", "run_swarm", "backtest"}


def test_mcp_unavailable_is_explicit():
    result = asyncio.run(FinancialData().call("get_market_data", {}))
    assert result["status"] == "error"


def test_market_data_bounds_and_provenance():
    async def run():
        data = FinancialData()
        data.session = SimpleNamespace(call_tool=AsyncMock(return_value=SimpleNamespace(structuredContent={"price": None}, content=[], isError=False)))
        result = await data.call("get_market_data", {"codes": ["AAPL.US"], "max_rows": 0})
        assert data.session.call_tool.call_args.args[1]["max_rows"] == 1
        assert result["provider"] == "Vibe-Trading MCP"
        assert result["data"]["price"] is None
        assert "retrievedAt" in result
    asyncio.run(run())


def test_approval_stream_has_checkpoint():
    async def run():
        config = {"configurable": {"thread_id": "test-approval-checkpoint"}}
        result = await graph.ainvoke({"messages": [HumanMessage(content="研究问题")], "mode": "深度研究", "tools": [{"name": "approve_research_plan"}]}, config)
        assert result["stage"] == "awaiting_approval"
        assert result["messages"][-1].tool_calls[0]["name"] == "approve_research_plan"
        assert (await graph.aget_state(config)).values["stage"] == "awaiting_approval"
    asyncio.run(run())
