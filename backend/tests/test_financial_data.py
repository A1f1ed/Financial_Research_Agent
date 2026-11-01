import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import backend.financial_data as module
from backend.financial_data import FinancialData


def connected_data(content=None, is_error=False):
    data = FinancialData()
    result = SimpleNamespace(structuredContent=content, content=[], isError=is_error)
    data.session = SimpleNamespace(call_tool=AsyncMock(return_value=result))
    return data


@pytest.mark.parametrize("arguments", [None, [], "AAPL.US", 7])
def test_non_object_arguments_never_reach_mcp(arguments):
    data = connected_data()
    result = asyncio.run(data.call("get_stock_profile", arguments))
    assert result["status"] == "error"
    data.session.call_tool.assert_not_called()


@pytest.mark.parametrize("codes", [None, [], "AAPL.US", [None], [" "], ["X" * 129], ["AAPL.US"] * 6])
def test_invalid_symbols_never_reach_mcp(codes):
    data = connected_data()
    result = asyncio.run(data.call("get_market_data", {"codes": codes}))
    assert result["status"] == "error"
    data.session.call_tool.assert_not_called()


@pytest.mark.parametrize("field, value", [("max_rows", "10"), ("max_rows", True), ("max_rows", None), ("max_rows", 1.5), ("limit", "10"), ("limit", False)])
def test_row_and_limit_types_are_strict(field, value):
    data = connected_data()
    name = "get_market_data" if field == "max_rows" else "get_stock_news"
    arguments = {"codes": ["AAPL.US"], field: value} if field == "max_rows" else {field: value}
    result = asyncio.run(data.call(name, arguments))
    assert result["status"] == "error"
    data.session.call_tool.assert_not_called()


def test_query_caps_do_not_mutate_caller_arguments():
    async def run():
        data = connected_data({"rows": []})
        arguments = {"codes": ["AAPL.US"], "max_rows": 10000}
        await data.call("get_market_data", arguments)
        assert data.session.call_tool.call_args.args[1]["max_rows"] == 100
        assert arguments["max_rows"] == 10000
        await data.call("get_stock_news", {"limit": 10000})
        assert data.session.call_tool.call_args.args[1]["limit"] == 20
    asyncio.run(run())


def test_discovered_schema_rejects_missing_fields():
    data = connected_data()
    spec = SimpleNamespace(name="get_stock_profile", description="Read company profile", inputSchema={"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"], "additionalProperties": False})
    tool = data.make_tool(spec)
    result = asyncio.run(tool.ainvoke({}))
    assert result["status"] == "error"
    data.session.call_tool.assert_not_called()


@pytest.mark.parametrize("content", [{}, [], {"price": None}])
def test_structured_content_is_preserved_even_when_empty(content):
    data = connected_data(content)
    result = asyncio.run(data.call("get_stock_profile", {}))
    assert result["data"] == content
    assert result["status"] == "received"


def test_provider_error_is_not_reported_as_data_success():
    data = connected_data({"error": "upstream unavailable"}, is_error=True)
    result = asyncio.run(data.call("get_stock_profile", {}))
    assert result["status"] == "error"
    assert result["data"]["error"] == "upstream unavailable"


def test_large_output_is_rejected_without_truncation():
    data = connected_data({"text": "X" * 100001})
    result = asyncio.run(data.call("get_stock_profile", {}))
    assert result["status"] == "error"
    assert "data" not in result


def test_transport_exception_does_not_leak_details():
    data = connected_data()
    data.session.call_tool.side_effect = RuntimeError("private upstream diagnostic")
    result = asyncio.run(data.call("get_stock_profile", {}))
    assert result["status"] == "error"
    assert "private upstream diagnostic" not in str(result)


def test_timeout_includes_waiting_for_shared_lock(monkeypatch):
    monkeypatch.setattr(module, "QUERY_TIMEOUT_SECONDS", 0.01)

    async def run():
        data = connected_data()
        async with data.lock:
            result = await data.call("get_stock_profile", {})
        assert result["status"] == "error"
        data.session.call_tool.assert_not_called()
    asyncio.run(run())


def test_inflight_timeout_releases_lock(monkeypatch):
    monkeypatch.setattr(module, "QUERY_TIMEOUT_SECONDS", 0.01)

    async def run():
        data = connected_data()

        async def stalled(*args):
            await asyncio.Future()

        data.session.call_tool.side_effect = stalled
        result = await data.call("get_stock_profile", {})
        assert result["status"] == "error"
        assert not data.lock.locked()
    asyncio.run(run())


def fake_connection(monkeypatch, *, initialization_error=None, initialization_wait=False):
    closed = []
    environment = {}
    spec = SimpleNamespace(name="get_stock_profile", description="Public company profile", inputSchema={"type": "object", "properties": {}})

    async def initialize():
        if initialization_error:
            raise initialization_error
        if initialization_wait:
            await asyncio.Future()

    session = SimpleNamespace(initialize=initialize, list_tools=AsyncMock(return_value=SimpleNamespace(tools=[spec, SimpleNamespace(name="trading_place_order")])) )

    @asynccontextmanager
    async def transport(parameters):
        environment.update(parameters.env)
        try:
            yield object(), object()
        finally:
            closed.append("transport")

    @asynccontextmanager
    async def client(*args):
        try:
            yield session
        finally:
            closed.append("session")

    monkeypatch.setattr(module, "stdio_client", transport)
    monkeypatch.setattr(module, "ClientSession", client)
    return closed, environment


def test_connection_filters_tools_and_cleans_up(monkeypatch):
    closed, environment = fake_connection(monkeypatch)
    monkeypatch.setenv("FOLIO_INTERNAL_SECRET", "never-forward-this")

    async def run():
        data = FinancialData()
        async with data.connect():
            assert data.status == "connected"
            assert [tool.name for tool in data.tools] == ["get_stock_profile"]
            assert "FOLIO_INTERNAL_SECRET" not in environment
            assert environment["VIBE_TRADING_ENABLE_SHELL_TOOLS"] == "0"
        assert data.status == "disconnected"
        assert data.session is None and not data.tools and not data.validators
        assert closed == ["session", "transport"]
    asyncio.run(run())


def test_initialization_failure_keeps_agent_available(monkeypatch):
    closed, _ = fake_connection(monkeypatch, initialization_error=RuntimeError("MCP unavailable"))

    async def run():
        data = FinancialData()
        async with data.connect():
            assert data.status == "unavailable"
            assert data.session is None and not data.tools
            assert closed == ["session", "transport"]
            assert (await data.call("get_stock_profile", {}))["status"] == "error"
        assert data.status == "disconnected"
    asyncio.run(run())


def test_initialization_timeout_keeps_agent_available(monkeypatch):
    closed, _ = fake_connection(monkeypatch, initialization_wait=True)
    monkeypatch.setattr(module, "CONNECT_TIMEOUT_SECONDS", 0.01)

    async def run():
        data = FinancialData()
        async with data.connect():
            assert data.status == "unavailable"
            assert closed == ["session", "transport"]
    asyncio.run(run())


def test_missing_executable_keeps_agent_available(monkeypatch):
    @asynccontextmanager
    async def missing(*args):
        raise FileNotFoundError("missing MCP executable")
        yield

    monkeypatch.setattr(module, "stdio_client", missing)

    async def run():
        data = FinancialData()
        async with data.connect():
            assert data.status == "unavailable"
            assert not data.tools
    asyncio.run(run())


def test_agent_health_survives_missing_mcp(monkeypatch):
    from fastapi.testclient import TestClient
    from backend.server import app

    @asynccontextmanager
    async def missing(*args):
        raise FileNotFoundError("missing MCP executable")
        yield

    monkeypatch.setattr(module, "stdio_client", missing)
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["agent"] == "folio_research"
        assert response.json()["financialData"] is False
        assert response.json()["financialTools"] == []
        assert client.post("/agent", json={}).status_code == 401


def test_application_errors_are_not_swallowed_by_mcp_fallback(monkeypatch):
    fake_connection(monkeypatch)

    async def run():
        data = FinancialData()
        with pytest.raises(RuntimeError, match="application error"):
            async with data.connect():
                raise RuntimeError("application error")
        assert data.status == "disconnected"
    asyncio.run(run())
