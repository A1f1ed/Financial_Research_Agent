from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator
from src.documents.contracts import DocumentMetadata


def clean_ids(values):
    return list(dict.fromkeys(str(UUID(value)) for value in values))


class CollectionInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    symbols: list[str] = Field(default_factory=list, max_length=8)
    topics: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("name", "description")
    @classmethod
    def text(cls, value, info):
        value = value.strip()
        if info.field_name == "name" and not value or any(ord(char) < 32 and char not in "\n\t" for char in value):
            raise ValueError("Provide valid collection text")
        return value

    @field_validator("symbols")
    @classmethod
    def symbols_clean(cls, value):
        return DocumentMetadata.clean_symbols(value)

    @field_validator("topics")
    @classmethod
    def topics_clean(cls, values):
        if any(not value.strip() or len(value.strip()) > 40 or any(ord(char) < 32 for char in value) for value in values):
            raise ValueError("Topics must contain 1 to 40 readable characters")
        return list(dict.fromkeys(value.strip() for value in values))


class CollectionEdit(CollectionInput):
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def reason_clean(cls, value):
        if not value.strip(): raise ValueError("Provide an audit reason")
        return value.strip()


class CollectionAction(BaseModel):
    expected_revision: int = Field(ge=1)


class MembershipChange(CollectionAction):
    action: Literal["add", "remove"]
    document_ids: list[str] = Field(min_length=1, max_length=100)

    @field_validator("document_ids")
    @classmethod
    def ids(cls, values): return clean_ids(values)


class ScopeRequest(BaseModel):
    collection_ids: list[str] = Field(default_factory=list, max_length=8)
    document_ids: list[str] = Field(default_factory=list, max_length=50)
    as_of: date | None = None
    as_of_at: datetime | None = None
    market: Literal["HK", "US", "SH", "SZ", "SG"] = "HK"
    mode: Literal["strict", "explore"] = "strict"

    @field_validator("collection_ids", "document_ids")
    @classmethod
    def ids(cls, values): return clean_ids(values)

    @model_validator(mode="after")
    def scope(self):
        if not self.collection_ids and not self.document_ids:
            raise ValueError("Select a collection or explicit documents")
        if bool(self.as_of) == bool(self.as_of_at):
            raise ValueError("Select exactly one cutoff date or explicit instant")
        if self.as_of_at and (self.as_of_at.tzinfo is None or self.as_of_at.utcoffset() is None):
            raise ValueError("The cutoff instant requires a timezone")
        return self


class IndexRequest(BaseModel):
    document_ids: list[str] = Field(min_length=1, max_length=20)
    mode: Literal["keyword", "hybrid"] = "keyword"
    force: bool = False

    @field_validator("document_ids")
    @classmethod
    def ids(cls, values): return clean_ids(values)


class SearchRequest(ScopeRequest):
    query: str = Field(min_length=2, max_length=500)
    search_mode: Literal["keyword", "hybrid"] = "keyword"
    limit: int = Field(default=5, ge=1, le=10)

    @field_validator("query")
    @classmethod
    def query_clean(cls, value):
        if len(value.strip()) < 2 or "\x00" in value: raise ValueError("Enter a readable search query")
        return value.strip()


class ConversationRequest(ScopeRequest):
    thread_id: UUID
    search_mode: Literal["keyword", "hybrid"] = "keyword"
