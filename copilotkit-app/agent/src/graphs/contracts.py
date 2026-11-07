from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from src.knowledge.contracts import CollectionInput, ScopeRequest

EntityKind = Literal["company", "group", "brand", "product", "region", "policy", "event", "industry"]
RelationKind = Literal["owns", "brand_of", "produces", "operates_in", "supplies", "customer_of", "applies_to", "announced", "supersedes", "may_affect"]
RELATION_TYPES = list(RelationKind.__args__)


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GraphInput(StrictInput):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    scope: ScopeRequest
    relation_types: list[RelationKind] = Field(default_factory=lambda: RELATION_TYPES.copy(), min_length=1, max_length=12)

    @field_validator("name", "description")
    @classmethod
    def readable(cls, value, info): return CollectionInput.text(value, info)


class RevisionInput(StrictInput):
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def reason_text(cls, value):
        if not value.strip() or "\x00" in value: raise ValueError("Provide a readable audit reason")
        return value.strip()


class GraphEdit(GraphInput, RevisionInput): pass


class EvidenceInput(StrictInput):
    document_id: UUID
    page_number: int = Field(ge=1, le=5000)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    quote: str = Field(min_length=2, max_length=4000)

    @model_validator(mode="after")
    def offsets(self):
        if self.end_offset <= self.start_offset: raise ValueError("Evidence needs a nonempty exact page span")
        return self


class EntityInput(StrictInput):
    name: str = Field(min_length=1, max_length=160)
    kind: EntityKind
    aliases: list[str] = Field(default_factory=list, max_length=30)
    symbols: list[str] = Field(default_factory=list, max_length=8)
    evidence: list[EvidenceInput] = Field(min_length=1, max_length=8)

    @field_validator("name")
    @classmethod
    def readable(cls, value):
        if not value.strip() or any(ord(c) < 32 for c in value): raise ValueError("Use a readable entity name")
        return value.strip()

    @field_validator("aliases")
    @classmethod
    def aliases_text(cls, values):
        if any(not v.strip() or len(v) > 160 or any(ord(c) < 32 for c in v) for v in values): raise ValueError("Invalid alias")
        return list(dict.fromkeys(v.strip() for v in values))

    @field_validator("symbols")
    @classmethod
    def symbols_text(cls, values): return CollectionInput.symbols_clean(values)


class EntityEdit(EntityInput, RevisionInput): pass


class RelationInput(StrictInput):
    source_id: UUID
    target_id: UUID
    relation_type: RelationKind
    assertion: Literal["disclosed", "inferred"]
    valid_from: date | None = None
    valid_until: date | None = None
    explanation: str = Field(min_length=1, max_length=2000)
    evidence: list[EvidenceInput] = Field(min_length=1, max_length=8)
    extraction_version: str = Field(default="manual-v1", min_length=1, max_length=80)

    @model_validator(mode="after")
    def semantics(self):
        if self.source_id == self.target_id: raise ValueError("A relationship needs two distinct entities")
        if self.valid_until and (not self.valid_from or self.valid_until < self.valid_from): raise ValueError("Invalid applicability interval")
        if self.relation_type == "may_affect" and self.assertion != "inferred": raise ValueError("Impact paths must remain marked as inference")
        if not self.explanation.strip(): raise ValueError("Explain the relationship and its evidence")
        return self


class RelationEdit(RelationInput, RevisionInput): pass


class ReviewInput(RevisionInput):
    action: Literal["accept", "reject", "revoke"]


class GraphQueryInput(StrictInput):
    entity_id: UUID
    as_of: date
    valid_on: date | None = None
    max_hops: int = Field(default=1, ge=1, le=2)
    relation_types: list[RelationKind] = Field(default_factory=list, max_length=12)
    include_inferred: bool = False
    name: str = Field(default="", max_length=120)

    @model_validator(mode="after")
    def date_order(self):
        if self.valid_on and self.valid_on > self.as_of: raise ValueError("Applicability cannot be later than the knowledge cutoff")
        return self


class ExtractionOptions(StrictInput):
    document_ids: list[UUID] = Field(default_factory=list, max_length=50)
    max_calls: int = Field(default=6, ge=1, le=20)
    characters_per_call: int = Field(default=8000, ge=1000, le=12000)
    timeout_seconds: int = Field(default=60, ge=10, le=90)
    max_output_tokens: int = Field(default=4000, ge=1000, le=6000)
    force: bool = False


class ExtractionStart(ExtractionOptions):
    plan_key: str = Field(pattern=r"^[a-f0-9]{64}$")


class ProposedEntity(StrictInput):
    name: str = Field(min_length=1, max_length=160)
    kind: EntityKind | None = None
    aliases: list[str] = Field(default_factory=list, max_length=12)
    symbols: list[str] = Field(default_factory=list, max_length=8)
    quote: str = Field(min_length=2, max_length=2000)
    identity_uncertain: bool = True

    @field_validator("name")
    @classmethod
    def name_text(cls,value): return EntityInput.readable(value)

    @field_validator("aliases")
    @classmethod
    def aliases_text(cls,value): return EntityInput.aliases_text(value)

    @field_validator("symbols")
    @classmethod
    def symbols_text(cls,value): return EntityInput.symbols_text(value)


class ProposedRelation(StrictInput):
    source: ProposedEntity
    target: ProposedEntity
    relation_type: RelationKind
    assertion: Literal["disclosed", "inferred"]
    valid_from: date | None = None
    valid_until: date | None = None
    explanation: str = Field(min_length=1, max_length=2000)
    quote: str = Field(min_length=2, max_length=4000)

    @model_validator(mode="after")
    def semantics(self):
        if self.valid_until and (not self.valid_from or self.valid_until < self.valid_from): raise ValueError("Invalid applicability interval")
        if self.relation_type == "may_affect" and self.assertion != "inferred": raise ValueError("Influence paths must be inference")
        return self


class ExtractionOutput(StrictInput):
    relations: list[ProposedRelation] = Field(default_factory=list, max_length=10)


class IdentityResolution(StrictInput):
    mode: Literal["existing", "new"]
    entity_id: UUID | None = None
    expected_revision: int | None = Field(default=None, ge=1)
    name: str = Field(default="", max_length=160)
    kind: EntityKind | None = None
    aliases: list[str] = Field(default_factory=list, max_length=30)
    symbols: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def explicit_choice(self):
        if self.mode == "existing" and (not self.entity_id or not self.expected_revision): raise ValueError("Choose an existing identity and its current revision")
        if self.mode == "new" and (not self.name.strip() or not self.kind or self.entity_id): raise ValueError("Name and classify a new separate identity")
        if self.mode == "new":
            self.name=EntityInput.readable(self.name)
            self.aliases=EntityInput.aliases_text(self.aliases)
            self.symbols=EntityInput.symbols_text(self.symbols)
        return self


class ResolveCandidate(RevisionInput):
    source: IdentityResolution
    target: IdentityResolution
    valid_from: date | None = None
    valid_until: date | None = None
    explanation: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def interval(self):
        if self.valid_until and (not self.valid_from or self.valid_until < self.valid_from): raise ValueError("Invalid applicability interval")
        if not self.explanation.strip(): raise ValueError("Provide a readable relationship explanation")
        return self
