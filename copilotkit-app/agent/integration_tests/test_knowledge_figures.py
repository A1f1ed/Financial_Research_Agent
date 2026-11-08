"""Synthetic reviewed figures on real isolated PostgreSQL; no model requests."""
import json
import os
import unittest
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage
from langchain.agents.middleware import ModelResponse
from sqlalchemy import func, select
import integration_tests.test_knowledge_search as search_cases
from src.knowledge.api import router
from src.knowledge.calculations import CalculationInput, FigureAction, FigureInput
from src.knowledge.contracts import ConversationRequest, MembershipChange, SearchRequest
from src.knowledge.conversations import ConversationRepository
from src.knowledge.figures import FigureRepository
from src.knowledge.retrieval import search
from src.knowledge.tools import calculate_reviewed_research_figures, list_reviewed_research_figures, read_research_document_context, search_research_documents
from src.knowledge.agent_scope import validate_response
from src.persistence.database import transaction
from src.persistence.jobs import StateConflict
from src.persistence.models import Document, DocumentPage, KnowledgeCalculation, KnowledgeFigure

TEXT="Synthetic Company\n人民币千元\nOperating cash flow\n100\nNet profit\n40\n"


@unittest.skipUnless(os.getenv("APERTURE_RUN_INTEGRATION")=="1","Requires isolated PostgreSQL")
class FigureTests(unittest.IsolatedAsyncioTestCase):
    setUpClass=classmethod(search_cases.SearchTests.setUpClass.__func__)
    tearDownClass=classmethod(search_cases.SearchTests.tearDownClass.__func__)
    material=search_cases.SearchTests.material
    build=search_cases.SearchTests.build

    def setUp(self):
        search_cases.SearchTests.setUp(self)
        self.figures=FigureRepository()

    async def source(self,content=TEXT):
        self.document=self.material(content)
        with transaction() as db:db.get(Document,self.document).issuer="Synthetic Company"
        await self.build(self.document)
        self.search=await search(SearchRequest(collection_ids=[self.collection["id"]],as_of="2026-10-31",query="cash flow"))
        return self.figures.context(self.collection["id"],self.search["id"],"K1")

    def inputs(self,value="100",metric="Operating cash flow",**changes):
        quote=self.search["hits"][0]["quote"]
        return FigureInput(search_id=self.search["id"],citation_id="K1",value_start=quote.index(value),value_text=value,
            metric=metric,unit="thousands",currency="CNY",unit_page_number=2,unit_start=TEXT.index("人民币千元"),unit_quote="人民币千元",
            period_type="duration",period_start="2026-01-01",period_end="2026-06-30",basis="Consolidated",
            confirmation="source_and_column_checked",reason="Synthetic explicit source/column review",**changes)

    async def test_context_review_retains_exact_value_unit_and_audit(self):
        context=await self.source()
        self.assertIn({"start":self.inputs().value_start,"text":"100"},context["numbers"])
        self.assertTrue(any(u["quote"]=="人民币千元" for u in context["unit_candidates"]))
        row=self.figures.create(self.collection["id"],self.inputs())
        self.assertEqual((row["value"],row["subject"],row["review"]),("100","Synthetic Company","user_confirmed_column_period_basis"))
        self.assertEqual(row["unit_source"]["quote"],"人民币千元")
        self.assertEqual(row["source"]["search_id"],self.search["id"])
        self.assertEqual(self.figures.list(self.collection["id"])["total"],1)
        duplicate=self.figures.create(self.collection["id"],self.inputs())
        self.assertEqual(duplicate["id"],row["id"]);self.assertTrue(duplicate["duplicate"])
        self.assertEqual(self.figures.list(self.collection["id"])["total"],1)

    async def test_source_and_unit_forgery_never_creates_a_reviewed_figure(self):
        await self.source()
        for fields in ({"value_text":"10"},{"value_start":0},{"unit":"millions"},{"unit_quote":"RMB million"},{"unit_page_number":1}):
            with self.subTest(fields=fields),self.assertRaises((StateConflict,ValueError)):
                self.figures.create(self.collection["id"],self.inputs().model_copy(update=fields))
        self.assertEqual(self.figures.list(self.collection["id"])["total"],0)

    async def test_reversed_chinese_unit_phrase_and_explicit_subtraction_keep_original_value(self):
        context=await self.source(TEXT.replace("人民币千元","千元人民币"))
        self.assertTrue(any(unit["quote"]=="千元人民币" for unit in context["unit_candidates"]))
        self.assertFalse(any(unit["quote"]=="元人民币" for unit in context["unit_candidates"]))
        with self.assertRaises(StateConflict):self.figures.create(self.collection["id"],self.inputs().model_copy(update={"unit_quote":"元人民币","unit":"ones","unit_start":TEXT.index("人民币千元")+1}))
        one=self.figures.create(self.collection["id"],self.inputs().model_copy(update={"unit_quote":"千元人民币"}))
        two=self.figures.create(self.collection["id"],self.inputs("40","Reversal").model_copy(update={"unit_quote":"千元人民币"}))
        result=self.figures.calculate(self.collection["id"],CalculationInput(operation="sum",figure_ids=[one["id"],two["id"]],signs=[1,-1]))
        self.assertEqual(result["value"],"60");self.assertEqual(result["inputs"][1]["value"],"40")
        self.assertEqual(result["request"]["signs"],[1,-1])

    async def test_calculation_snapshot_survives_figure_archive_and_blocks_reuse(self):
        await self.source();one=self.figures.create(self.collection["id"],self.inputs());two=self.figures.create(self.collection["id"],self.inputs("40","Net profit"))
        inputs=CalculationInput(operation="ratio_percent",figure_ids=[one["id"],two["id"]])
        result=self.figures.calculate(self.collection["id"],inputs)
        self.assertEqual(result["value"],"250");self.assertEqual(len(result["references"]),2)
        changed=self.figures.archive(self.collection["id"],one["id"],FigureAction(expected_revision=1,reason="Synthetic archive"))
        with self.assertRaises(StateConflict):self.figures.calculate(self.collection["id"],inputs)
        self.assertEqual(self.figures.calculations(self.collection["id"])["calculations"][0],result)
        with self.assertRaises(StateConflict):self.figures.archive(self.collection["id"],one["id"],FigureAction(expected_revision=1,reason="Stale restore"),False)
        self.figures.archive(self.collection["id"],one["id"],FigureAction(expected_revision=changed["revision"],reason="Synthetic restore"),False)
        self.assertEqual(self.figures.calculate(self.collection["id"],inputs)["value"],"250")

    async def test_changed_source_or_removed_membership_blocks_new_calculations(self):
        await self.source();one=self.figures.create(self.collection["id"],self.inputs())
        inputs=CalculationInput(operation="convert",figure_ids=[one["id"]],target_unit="millions")
        before=self.figures.calculate(self.collection["id"],inputs)
        with transaction() as db:db.get(Document,self.document).metadata_revision+=1
        with self.assertRaises(StateConflict):self.figures.calculate(self.collection["id"],inputs)
        with self.assertRaises(StateConflict):self.figures.create(self.collection["id"],self.inputs())
        self.assertEqual(self.figures.calculations(self.collection["id"])["calculations"][0],before)
        self.assertEqual(self.figures.in_scope({self.document})["stale_excluded"],1)

    async def test_scope_membership_and_archive_are_enforced(self):
        await self.source();one=self.figures.create(self.collection["id"],self.inputs())
        inputs=CalculationInput(operation="convert",figure_ids=[one["id"]],target_unit="millions")
        with self.assertRaises(StateConflict):self.figures.calculate(self.collection["id"],inputs,eligible=set())
        current=self.collections.detail(self.collection["id"])
        self.collections.members(current["id"],MembershipChange(expected_revision=current["revision"],action="remove",document_ids=[self.document]))
        with self.assertRaises(StateConflict):self.figures.calculate(self.collection["id"],inputs)
        self.assertEqual(self.figures.in_scope({self.document})["figures"],[])

    async def test_native_tools_only_use_current_bound_sources_and_reviewed_inputs(self):
        await self.source();one=self.figures.create(self.collection["id"],self.inputs())
        binding=ConversationRepository().create(ConversationRequest(thread_id=uuid4(),collection_ids=[self.collection["id"]],as_of="2026-10-31"))
        runtime=SimpleNamespace(config={"configurable":{"thread_id":binding["thread_id"]}},tool_call_id="synthetic",state={"messages":[HumanMessage(content="cash flow",id="calculation-turn")]})
        command=await search_research_documents.coroutine("cash flow",runtime);found=json.loads(command.update["messages"][0].content)
        context=await read_research_document_context.coroutine(found["search_id"],"K1",runtime)
        self.assertIn("context",json.loads(context.update["messages"][0].content))
        listed=await list_reviewed_research_figures.coroutine("cash",runtime)
        self.assertEqual(json.loads(listed.update["messages"][0].content)["figures"][0]["id"],one["id"])
        fallback=await list_reviewed_research_figures.coroutine("经营现金流",runtime)
        self.assertEqual(fallback.update["messages"][0].name,"list_reviewed_research_figures")
        fallback_data=json.loads(fallback.update["messages"][0].content)
        self.assertEqual(fallback_data["match_status"],"recent_in_scope_fallback")
        self.assertEqual([item["id"] for item in fallback_data["figures"]],[one["id"]])
        calculated=await calculate_reviewed_research_figures.coroutine("convert",[one["id"]],runtime,"millions")
        actual=json.loads(calculated.update["messages"][0].content)
        self.assertEqual((actual["status"],actual["value"]),("calculated","0.1"))
        answer=ModelResponse(result=[AIMessage(content="Synthetic code result. "+one["source"]["citation_markdown"])])
        self.assertEqual(validate_response(SimpleNamespace(messages=runtime.state["messages"]),answer,binding["thread_id"]).result[-1].text,answer.result[-1].text)
        runtime.state["messages"]=[HumanMessage(content="another question",id="new-turn")]
        denied=await read_research_document_context.coroutine(found["search_id"],"K1",runtime)
        self.assertEqual(json.loads(denied.update["messages"][0].content)["status"],"evidence_unavailable")

    async def test_http_origin_validation_and_persisted_history(self):
        await self.source();app=FastAPI();app.include_router(router);path=f"/research/knowledge/collections/{self.collection['id']}"
        with TestClient(app) as client:
            body=self.inputs().model_dump(mode="json")
            self.assertEqual(client.post(path+"/figures",json=body,headers={"Origin":"https://example.invalid"}).status_code,403)
            self.assertEqual(client.post(path+"/figures",json={**body,"confirmation":"unchecked"}).status_code,422)
            accepted=client.post(path+"/figures",json=body);self.assertEqual(accepted.status_code,201)
            query={"operation":"convert","figure_ids":[accepted.json()["id"]],"target_unit":"millions"}
            self.assertEqual(client.post(path+"/calculations",json=query).json()["value"],"0.1")
            self.assertEqual(client.get(path+"/calculations").json()["total"],1)
            self.assertEqual(client.get(path+f"/figure-context/{self.search['id']}/K1").status_code,200)
