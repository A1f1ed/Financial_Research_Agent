from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict, model_validator
from src.knowledge.contracts import ScopeRequest
from src.knowledge.calculations import CalculationInput
from src.graphs.contracts import GraphQueryInput

SCORER_VERSION = "deterministic-evidence-v1"


class PageExpectation(BaseModel):
    document_id: UUID
    page_number: int = Field(ge=1, le=2000)


class NumberExpectation(BaseModel):
    value: Decimal
    tolerance: Decimal = Field(default=Decimal("0"), ge=0)
    currency: str = Field(default="", max_length=12)
    unit: str = Field(default="", max_length=40)
    period_start: str = Field(default="", max_length=10)
    period_end: str = Field(default="", max_length=10)


class Expectations(BaseModel):
    pages: list[PageExpectation] = Field(default_factory=list, max_length=20)
    number: NumberExpectation | None = None
    minimum_edges: int | None = Field(default=None, ge=0, le=200)
    refusal: Literal["not_scored", "must_abstain", "must_answer"] = "not_scored"
    reference_note: str = Field(default="", max_length=1000)
    manual_reference: dict = Field(default_factory=dict)
    manual_review_required: bool = False

    @model_validator(mode="after")
    def bounded_reference(self):
        import json
        if len(json.dumps(self.manual_reference,ensure_ascii=False).encode()) > 12000:
            raise ValueError("Manual reference is limited to 12 KB per case")
        return self


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=160)
    partition: Literal["development", "acceptance"] = "development"
    target: Literal["retrieval", "agent", "graph", "calculation", "task_list", "vision", "wiki", "manual_review"] = "retrieval"
    question: str = Field(default="", max_length=500)
    scope: ScopeRequest | None = None
    graph_id: UUID | None = None
    graph_query: GraphQueryInput | None = None
    collection_id: UUID | None = None
    calculation: CalculationInput | None = None
    expected: Expectations = Field(default_factory=Expectations)

    @model_validator(mode="after")
    def valid_target(self):
        if self.target in {"retrieval", "agent", "graph", "calculation"} and (not self.scope or self.scope.mode != "strict"):
            raise ValueError("Evidence evaluations require an explicit strict source cutoff")
        if self.target in {"retrieval", "agent"} and len(self.question.strip()) < 2:
            raise ValueError("Provide a question of at least two characters")
        if self.target == "graph" and (not self.graph_id or not self.graph_query):
            raise ValueError("Select an actual graph and starting identity")
        if self.target == "calculation" and (not self.collection_id or not self.calculation):
            raise ValueError("Select reviewed calculation inputs")
        return self


class DatasetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    cases: list[EvaluationCase] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_cases(self):
        if not self.name.strip(): raise ValueError("Provide a dataset name")
        if len({case.id for case in self.cases}) != len(self.cases): raise ValueError("Case IDs must be unique")
        return self


class DatasetEdit(DatasetInput):
    expected_revision: int = Field(ge=1)


class RevisionAction(BaseModel):
    expected_revision: int = Field(ge=1)


class RunOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version_id: UUID
    partition: Literal["development", "acceptance"] = "development"
    acceptance_confirmed: bool = False
    mode: Literal["quality", "retrieval_benchmark", "list_benchmark", "agent_performance"] = "quality"
    repetitions: int = Field(default=1, ge=1, le=100)
    concurrency: Literal[1] = 1
    search_mode: Literal["keyword", "hybrid"] = "keyword"
    allow_model: bool = False
    max_calls: int = Field(default=0, ge=0, le=100)
    max_tokens: int = Field(default=0, ge=0, le=2000000)
    max_output_tokens: int = Field(default=1024, ge=256, le=4096)
    max_pages: int = Field(default=100, ge=1, le=2000)
    timeout_seconds: int = Field(default=60, ge=5, le=120)
    parent_run_id: UUID | None = None

    @model_validator(mode="after")
    def confirmations(self):
        if self.partition == "acceptance" and not self.acceptance_confirmed:
            raise ValueError("Explicitly confirm a frozen acceptance run")
        if self.allow_model and (not self.max_calls or not self.max_tokens):
            raise ValueError("Model-enabled runs need positive call and token budgets")
        if self.search_mode == "hybrid" and not self.allow_model:
            raise ValueError("Hybrid retrieval sends a query to an embedding model; explicitly enable model calls")
        return self
