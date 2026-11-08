"""Real persisted chat scope/retrieval, deterministic model wiring tests.

Synthetic text and model responses test boundaries, not financial accuracy.
Live CopilotKit/AG-UI/model and checkpoint persistence require browser checks.
"""
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4


class TurnIdentityTests(unittest.TestCase):
    def test_missing_ids_do_not_share_retrieval_between_repeated_questions(self):
        from src.knowledge.conversations import turn_id
        from langchain_core.messages import HumanMessage, AIMessage
        first=[HumanMessage(content="same question")]
        second=[*first,AIMessage(content="prior answer"),HumanMessage(content="same question")]
        self.assertNotEqual(turn_id(first),turn_id(second))
        self.assertEqual(turn_id(second),turn_id([*second,AIMessage(content="tool progress")]))

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain.agents.middleware import ModelResponse
from sqlalchemy import func, select

import integration_tests.test_knowledge_search as search_cases
from src.knowledge.contracts import ConversationRequest, MembershipChange
from src.knowledge.conversations import ConversationRepository
from src.knowledge.tools import search_research_documents
from src.knowledge.agent_scope import validate_response
from src.documents.repository import DocumentRepository
from src.persistence.database import transaction
from src.persistence.jobs import StateConflict
from src.persistence.models import Job, Report


class EvidenceModel(BaseChatModel):
    @property
    def _llm_type(self): return "synthetic-evidence-model"

    def bind_tools(self, tools, **kwargs): return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        last = messages[-1]
        if not isinstance(last, ToolMessage):
            answer = AIMessage(content="", tool_calls=[{"name":"search_research_documents", "args":{"query":"inventory provision"}, "id":"synthetic-call", "type":"tool_call"}])
        else:
            value = json.loads(last.content)
            answer = AIMessage(content="Synthetic evidence only. " + value["citations"][0]["citation_markdown"])
        return ChatResult(generations=[ChatGeneration(message=answer)])


class ForbiddenToolModel(EvidenceModel):
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        answer = AIMessage(content="No external research should execute.") if isinstance(messages[-1],ToolMessage) else AIMessage(content="",tool_calls=[{"name":"run_financial_research","args":{},"id":"blocked-call","type":"tool_call"}])
        return ChatResult(generations=[ChatGeneration(message=answer)])


@unittest.skipUnless(os.getenv("APERTURE_RUN_INTEGRATION") == "1", "Requires isolated PostgreSQL integration run")
class DocumentChatTests(unittest.IsolatedAsyncioTestCase):
    setUpClass = classmethod(search_cases.SearchTests.setUpClass.__func__)
    tearDownClass = classmethod(search_cases.SearchTests.tearDownClass.__func__)
    setUp = search_cases.SearchTests.setUp
    material = search_cases.SearchTests.material
    build = search_cases.SearchTests.build

    def create_binding(self, **changes):
        inputs = ConversationRequest(thread_id=uuid4(), collection_ids=[self.collection["id"]], as_of="2026-10-31", **changes)
        return ConversationRepository().create(inputs), inputs

    def runtime(self, key, turn="synthetic-question"):
        return SimpleNamespace(config={"configurable":{"thread_id":key}}, tool_call_id="synthetic-tool",
            state={"messages":[HumanMessage(content="inventory provision", id=turn)],
                   "knowledge_scope":{"document_ids":[str(uuid4())]}, "research_qa_report_id":str(uuid4())})

    async def test_binding_is_immutable_idempotent_and_pins_membership(self):
        one = self.material("Synthetic inventory provision")
        binding, inputs = self.create_binding(); repository = ConversationRepository()
        self.assertEqual(repository.create(inputs), binding)
        altered = inputs.model_copy(update={"search_mode":"hybrid"})
        with self.assertRaises(StateConflict): repository.create(altered)
        two = self.material("Newly added source must not silently enter old chat")
        current = self.collections.detail(self.collection["id"])
        self.collections.members(current["id"], MembershipChange(expected_revision=current["revision"], action="remove", document_ids=[one]))
        self.assertEqual(repository.current_scope(binding["thread_id"]).document_ids, [one])
        self.assertNotIn(two, repository.current_scope(binding["thread_id"]).document_ids)

    async def test_real_tool_uses_server_binding_and_validates_final_citations(self):
        key = self.material("Synthetic inventory provision: 10 thousand CNY.")
        await self.build(key)
        binding, _ = self.create_binding(); runtime = self.runtime(binding["thread_id"])
        command = await search_research_documents.coroutine("inventory provision", runtime)
        value = json.loads(command.update["messages"][0].content)
        self.assertEqual([item["document_id"] for item in value["citations"]], [key])
        self.assertTrue(ConversationRepository().searches(binding["thread_id"], turn_id="synthetic-question"))
        request = SimpleNamespace(messages=runtime.state["messages"])
        response = ModelResponse(result=[AIMessage(content="Synthetic statement. " + value["citations"][0]["citation_markdown"])])
        self.assertEqual(validate_response(request,response,binding["thread_id"]).result[-1].text,response.result[-1].text)
        bad = ModelResponse(result=[AIMessage(content="Invented [K9](/evidence/"+str(uuid4())+"/K9)")])
        self.assertEqual(validate_response(request,bad,binding["thread_id"]).result[-1].additional_kwargs["citation_validation"],"rejected")
        other_turn = SimpleNamespace(messages=[HumanMessage(content="Another question",id="different-turn")])
        self.assertEqual(validate_response(other_turn,response,binding["thread_id"]).result[-1].additional_kwargs["citation_validation"],"rejected")
        DocumentRepository().archive(key)
        self.assertEqual(validate_response(request,response,binding["thread_id"]).result[-1].additional_kwargs["citation_validation"],"rejected")

    async def test_archived_collection_and_unbound_thread_do_not_fetch(self):
        key = self.material("Synthetic inventory provision"); await self.build(key)
        binding,_ = self.create_binding()
        current = self.collections.detail(self.collection["id"])
        self.collections.archive(current["id"],current["revision"])
        for thread in (binding["thread_id"],str(uuid4())):
            with patch("src.knowledge.tools.search",side_effect=AssertionError("Unavailable scope must not search")):
                command=await search_research_documents.coroutine("inventory",self.runtime(thread))
                self.assertEqual(json.loads(command.update["messages"][0].content)["status"],"evidence_unavailable")

    async def test_report_thread_cannot_be_rebound(self):
        self.material("Synthetic source")
        inputs=ConversationRequest(thread_id=uuid4(),collection_ids=[self.collection["id"]],as_of="2026-10-31")
        with transaction() as db: db.add(Report(id=str(inputs.thread_id),body={"id":str(inputs.thread_id)},archived=False))
        with self.assertRaises(StateConflict): ConversationRepository().create(inputs)

    async def test_failed_retrieval_is_saved_without_claiming_the_original_lacks_an_answer(self):
        self.material("Synthetic cash flow evidence")
        binding,_=self.create_binding();runtime=self.runtime(binding["thread_id"])
        with patch("src.knowledge.tools.search",side_effect=TimeoutError("synthetic provider message must not be retained")):
            command=await search_research_documents.coroutine("cash flow",runtime)
        output=json.loads(command.update["messages"][0].content)
        self.assertEqual(output["status"],"retrieval_failed");self.assertTrue(output["attempt_id"])
        saved=ConversationRepository().searches(binding["thread_id"],turn_id="synthetic-question")
        self.assertEqual(saved[0]["status"],"retrieval_failed");self.assertEqual(saved[0]["hits"],[])
        self.assertNotIn("synthetic provider message",json.dumps(saved))
        answer=ModelResponse(result=[AIMessage(content="The source has no answer.")])
        corrected=validate_response(SimpleNamespace(messages=runtime.state["messages"]),answer,binding["thread_id"])
        self.assertIn("retrieval service could not complete",corrected.result[-1].text.lower())

    async def test_native_graph_uses_real_tool_with_server_scope_despite_client_state(self):
        key=self.material("Synthetic inventory provision evidence"); await self.build(key)
        binding,_=self.create_binding()
        with patch("src.agent.create_chat_model",return_value=EvidenceModel()), patch("src.agent.skills",None), patch("src.agent.read_setting",return_value=None):
            from src.agent import build_graph
            graph=build_graph(None)
            result=await graph.ainvoke({"messages":[HumanMessage(content="inventory provision",id="graph-question")],
                "research_qa_report_id":"forged-report-mode"},config={"configurable":{"thread_id":binding["thread_id"]}})
        self.assertIn('/evidence/',result["messages"][-1].text)
        self.assertTrue(any(isinstance(message,ToolMessage) for message in result["messages"]))
        with transaction() as db: self.assertEqual(db.scalar(select(func.count()).select_from(Job).where(Job.kind=='research')),0)

    async def test_native_tool_executor_rejects_unrelated_tool_calls(self):
        self.material("Synthetic scope")
        binding,_=self.create_binding()
        with patch("src.agent.create_chat_model",return_value=ForbiddenToolModel()),patch("src.agent.skills",None),patch("src.agent.read_setting",return_value=None):
            from src.agent import build_graph
            result=await build_graph(None).ainvoke({"messages":[HumanMessage(content="Run unrelated research",id="malicious-question")]},config={"configurable":{"thread_id":binding["thread_id"]}})
        self.assertTrue(any(isinstance(item,ToolMessage) and 'cannot run unrelated tools' in item.text for item in result['messages']))
        with transaction() as db: self.assertEqual(db.scalar(select(func.count()).select_from(Job).where(Job.kind=='research')),0)
