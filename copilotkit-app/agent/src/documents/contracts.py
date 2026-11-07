"""Document input contracts keep publication, reporting and upload times distinct."""
from datetime import date, datetime
from pathlib import PurePath
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator
from src.research_models import normalize_symbol

MAX_PDF_BYTES = 50 * 1024 * 1024
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_PAGES = 500
MAX_PIXELS = 30_000_000
EXTRACTION_VERSION = "pdfium2-5.15.0-text-v1"
DocumentKind = Literal["annual_report", "interim_report", "quarterly_report", "announcement", "results_presentation", "policy", "research_material", "image"]


class DocumentMetadata(BaseModel):
    title: str = Field(min_length=1, max_length=250)
    issuer: str = Field(default="", max_length=200)
    symbols: list[str] = Field(default_factory=list, max_length=8)
    kind: DocumentKind = "research_material"
    source_url: str | None = Field(default=None, max_length=1500)
    published_on: date | None = None
    published_at: datetime | None = None
    publication_basis: str = Field(default="", max_length=1000)
    period_start: date | None = None
    period_end: date | None = None

    @field_validator("title", "issuer", "publication_basis")
    @classmethod
    def clean_text(cls, value):
        value = value.strip()
        if any(ord(char) < 32 and char not in "\n\t" for char in value):
            raise ValueError("Metadata contains control characters")
        return value

    @field_validator("symbols")
    @classmethod
    def clean_symbols(cls, values):
        return list(dict.fromkeys(normalize_symbol(value) for value in values))

    @field_validator("source_url")
    @classmethod
    def valid_source(cls, value):
        if not value:
            return None
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError("Source must be an HTTPS URL without credentials or fragment")
        return value

    @field_validator("published_at")
    @classmethod
    def aware_timestamp(cls, value):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Publication timestamp requires an explicit timezone")
        return value

    @model_validator(mode="after")
    def dates(self):
        if self.published_at is not None:
            if self.published_on is not None and self.published_at.date() != self.published_on:
                raise ValueError("Publication day must match the stated publication timestamp")
            # Day-only dates and exact timestamps are alternative precision
            # modes. Do not retain a local calendar day beside a UTC-normalized
            # database timestamp and then accidentally compare the two dates.
            self.published_on = None
        if (self.published_on or self.published_at) and not self.publication_basis:
            raise ValueError("Provide the basis for the publication date; upload time is not publication time")
        if self.period_start and self.period_end and self.period_start > self.period_end:
            raise ValueError("Reporting period start must precede its end")
        if not self.title:
            raise ValueError("Title cannot be blank")
        return self


class UploadMetadata(DocumentMetadata):
    previous_version_id: str | None = Field(default=None, pattern=r"^[a-f0-9-]{36}$")
    collection_id: str | None = Field(default=None, pattern=r"^[a-f0-9-]{36}$")


class MetadataUpdate(DocumentMetadata):
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def valid_reason(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Provide a reason for this revision")
        return value


class URLImport(BaseModel):
    url: str = Field(min_length=1, max_length=1500)
    metadata: UploadMetadata


def safe_filename(name):
    # Browser filenames are labels, never paths in the object store/server.
    return re.sub(r"[\x00-\x1f\x7f]", "", PurePath(name.replace("\\", "/")).name)[:250] or "document"
