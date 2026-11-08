"""Typed legacy business contracts and durable dispatch records in PostgreSQL."""
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Identity, Index, Integer, MetaData, String, Text, UniqueConstraint, func, literal_column, text
from datetime import date
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from pgvector.sqlalchemy import Vector


class Base(DeclarativeBase):
    metadata = MetaData(schema="research", naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_name)s", "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s", "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    })


class Ordered:
    record_order: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True, nullable=False)


class Report(Ordered, Base):
    __tablename__ = "reports"
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    body: Mapped[dict] = mapped_column(JSONB, nullable=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))


class Cache(Base):
    __tablename__ = "cache"
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    body: Mapped[dict | list] = mapped_column(JSONB, nullable=False)
    fetched: Mapped[float] = mapped_column(Float, nullable=False)


class Preference(Base):
    __tablename__ = "preferences"
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    body: Mapped[dict] = mapped_column(JSONB, nullable=False)


class Schedule(Ordered, Base):
    __tablename__ = "schedules"
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    body: Mapped[dict] = mapped_column(JSONB, nullable=False)
    next_run: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    __table_args__ = (Index("ix_schedules_next_run", "next_run"),)


class Job(Ordered, Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    config: Mapped[dict] = mapped_column(JSONB)
    # Preserve historical plan IDs even if the old plan had already been deleted.
    schedule_id: Mapped[str | None] = mapped_column(String(160), index=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    lease_token: Mapped[str | None] = mapped_column(String(80))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    __table_args__ = (Index("uq_jobs_active_schedule", "schedule_id", unique=True,
                           postgresql_where=text("schedule_id IS NOT NULL AND status IN ('queued', 'running')")),)
    recovery_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    kind: Mapped[str] = mapped_column(String(30), default="research", server_default="research", index=True)
    progress: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    result: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    elapsed_seconds: Mapped[float] = mapped_column(Float, default=0, server_default=text("0"))


class Document(Ordered, Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    family_id: Mapped[str] = mapped_column(String(160), index=True)
    version: Mapped[int] = mapped_column(Integer)
    previous_version_id: Mapped[str | None] = mapped_column(ForeignKey("research.documents.id"))
    object_key: Mapped[str] = mapped_column(Text)
    media_type: Mapped[str] = mapped_column(String(100))
    byte_size: Mapped[int] = mapped_column(BigInteger)
    page_count: Mapped[int] = mapped_column(Integer)
    filename: Mapped[str] = mapped_column(String(250))
    title: Mapped[str] = mapped_column(String(250), index=True)
    issuer: Mapped[str] = mapped_column(String(200), default="", server_default="")
    symbols: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    kind: Mapped[str] = mapped_column(String(40), index=True)
    source_url: Mapped[str | None] = mapped_column(Text)
    published_on: Mapped[date | None] = mapped_column(Date)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publication_basis: Mapped[str] = mapped_column(Text, default="", server_default="")
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    metadata_revision: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    status: Mapped[str] = mapped_column(String(30), index=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active_job_id: Mapped[str | None] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("family_id", "version", name="uq_document_family_version"),)


class DocumentRevision(Base):
    __tablename__ = "document_revisions"
    document_id: Mapped[str] = mapped_column(ForeignKey("research.documents.id"), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    body: Mapped[dict] = mapped_column(JSONB)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DocumentPage(Base):
    __tablename__ = "document_pages"
    document_id: Mapped[str] = mapped_column(ForeignKey("research.documents.id"), primary_key=True)
    page_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    width: Mapped[float] = mapped_column(Float)
    height: Mapped[float] = mapped_column(Float)
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30))
    extraction_version: Mapped[str] = mapped_column(String(40))
    text_object_key: Mapped[str] = mapped_column(Text)
    error_type: Mapped[str | None] = mapped_column(String(100))


class DocumentReference(Base):
    __tablename__ = "document_references"
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("research.documents.id"), index=True)
    owner_type: Mapped[str] = mapped_column(String(40))
    owner_id: Mapped[str] = mapped_column(String(160), index=True)
    snapshot: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeCollection(Ordered, Base):
    __tablename__ = "knowledge_collections"
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    symbols: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    topics: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CollectionMember(Base):
    __tablename__ = "collection_members"
    collection_id: Mapped[str] = mapped_column(ForeignKey("research.knowledge_collections.id"), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("research.documents.id"), primary_key=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (Index("ix_collection_members_document_id", "document_id"),)


class CollectionRevision(Base):
    __tablename__ = "collection_revisions"
    collection_id: Mapped[str] = mapped_column(ForeignKey("research.knowledge_collections.id"), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    operation: Mapped[str] = mapped_column(String(40))
    body: Mapped[dict] = mapped_column(JSONB)
    reason: Mapped[str] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(40), default="local_user", server_default="local_user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeIndex(Ordered, Base):
    __tablename__ = "knowledge_indices"
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("research.documents.id"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("research.jobs.id"), unique=True)
    profile_key: Mapped[str] = mapped_column(String(64), index=True)
    profile: Mapped[dict] = mapped_column(JSONB)
    chunk_version: Mapped[str] = mapped_column(String(80))
    source_fingerprint: Mapped[str | None] = mapped_column(String(64))
    published: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    text_pages: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    omitted_pages: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (Index("uq_knowledge_index_published", "document_id", "profile_key", unique=True,
                           postgresql_where=text("published = true")),)


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    index_id: Mapped[str] = mapped_column(ForeignKey("research.knowledge_indices.id"), index=True)
    page_number: Mapped[int] = mapped_column(Integer)
    start_offset: Mapped[int] = mapped_column(Integer)
    end_offset: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    text_sha256: Mapped[str] = mapped_column(String(64))
    extraction_version: Mapped[str] = mapped_column(String(40))
    embedding: Mapped[list | None] = mapped_column(Vector())
    __table_args__ = (UniqueConstraint("index_id", "page_number", "start_offset", name="uq_chunk_position"),
        Index("ix_chunk_english_fts", literal_column("to_tsvector('simple'::regconfig, text)"), postgresql_using="gin"),
        Index("ix_chunk_trigram", "text", postgresql_using="gin", postgresql_ops={"text": "gin_trgm_ops"}))


class KnowledgeSearch(Ordered, Base):
    __tablename__ = "knowledge_searches"
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    query: Mapped[str] = mapped_column(Text)
    scope: Mapped[dict] = mapped_column(JSONB)
    result: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeConversation(Base):
    __tablename__ = "knowledge_conversations"
    thread_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    scope: Mapped[dict] = mapped_column(JSONB)
    snapshot: Mapped[dict] = mapped_column(JSONB)
    search_mode: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConversationSearch(Base):
    __tablename__ = "conversation_searches"
    thread_id: Mapped[str] = mapped_column(ForeignKey("research.knowledge_conversations.thread_id"), primary_key=True)
    search_id: Mapped[str] = mapped_column(ForeignKey("research.knowledge_searches.id"), primary_key=True)
    turn_id: Mapped[str] = mapped_column(String(160), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeFigure(Ordered, Base):
    __tablename__ = "knowledge_figures"
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    collection_id: Mapped[str] = mapped_column(ForeignKey("research.knowledge_collections.id"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("research.documents.id"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    body: Mapped[dict] = mapped_column(JSONB)
    audit: Mapped[list[dict]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("collection_id", "fingerprint", name="uq_knowledge_figures_collection_fingerprint"),)


class KnowledgeCalculation(Ordered, Base):
    __tablename__ = "knowledge_calculations"
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    collection_id: Mapped[str] = mapped_column(ForeignKey("research.knowledge_collections.id"), index=True)
    thread_id: Mapped[str | None] = mapped_column(String(160), index=True)
    turn_id: Mapped[str | None] = mapped_column(String(160), index=True)
    request: Mapped[dict] = mapped_column(JSONB)
    result: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class HiddenTask(Base):
    __tablename__ = "hidden_tasks"
    id: Mapped[str] = mapped_column(String(160), primary_key=True)


class ResearchGraph(Ordered, Base):
    __tablename__ = "research_graphs"
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    scope: Mapped[dict] = mapped_column(JSONB)
    snapshot: Mapped[dict] = mapped_column(JSONB)
    relation_types: Mapped[list] = mapped_column(JSONB)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    projection_id: Mapped[str | None] = mapped_column(String(160))
    projected_revision: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GraphEntity(Ordered, Base):
    __tablename__ = "graph_entities"
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    graph_id: Mapped[str] = mapped_column(ForeignKey("research.research_graphs.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    body: Mapped[dict] = mapped_column(JSONB)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class GraphRelation(Ordered, Base):
    __tablename__ = "graph_relations"
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    graph_id: Mapped[str] = mapped_column(ForeignKey("research.research_graphs.id"), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("research.graph_entities.id"))
    target_id: Mapped[str] = mapped_column(ForeignKey("research.graph_entities.id"))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="candidate", index=True)
    body: Mapped[dict] = mapped_column(JSONB)


class GraphAudit(Ordered, Base):
    __tablename__ = "graph_audits"
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    graph_id: Mapped[str] = mapped_column(ForeignKey("research.research_graphs.id"), index=True)
    graph_revision: Mapped[int] = mapped_column(Integer)
    object_type: Mapped[str] = mapped_column(String(20))
    object_id: Mapped[str] = mapped_column(String(160))
    object_revision: Mapped[int] = mapped_column(Integer)
    operation: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(Text)
    snapshot: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GraphProjection(Ordered, Base):
    __tablename__ = "graph_projections"
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    graph_id: Mapped[str] = mapped_column(ForeignKey("research.research_graphs.id"), index=True)
    graph_revision: Mapped[int] = mapped_column(Integer)
    job_id: Mapped[str] = mapped_column(ForeignKey("research.jobs.id"), unique=True)
    snapshot: Mapped[dict] = mapped_column(JSONB)
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GraphQuery(Ordered, Base):
    __tablename__ = "graph_queries"
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    graph_id: Mapped[str] = mapped_column(ForeignKey("research.research_graphs.id"), index=True)
    inputs: Mapped[dict] = mapped_column(JSONB)
    snapshot: Mapped[dict] = mapped_column(JSONB)
    name: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GraphExtraction(Ordered, Base):
    __tablename__ = "graph_extractions"
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    graph_id: Mapped[str] = mapped_column(ForeignKey("research.research_graphs.id"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("research.jobs.id"), unique=True)
    graph_revision: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    plan_key: Mapped[str] = mapped_column(String(64), index=True)
    plan: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GraphExtractionUnit(Ordered, Base):
    __tablename__ = "graph_extraction_units"
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    extraction_id: Mapped[str] = mapped_column(ForeignKey("research.graph_extractions.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    source: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    result: Mapped[dict] = mapped_column(JSONB, default=dict)
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("extraction_id", "position", name="uq_graph_extraction_unit_position"),)


class GraphExtractionCandidate(Ordered, Base):
    __tablename__ = "graph_extraction_candidates"
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    graph_id: Mapped[str] = mapped_column(ForeignKey("research.research_graphs.id"), index=True)
    extraction_id: Mapped[str] = mapped_column(ForeignKey("research.graph_extractions.id"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    body: Mapped[dict] = mapped_column(JSONB)
    resolution: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("graph_id", "fingerprint", name="uq_graph_candidate_fingerprint"),)


class EvaluationDataset(Ordered, Base):
    __tablename__ = "evaluation_datasets"
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    body: Mapped[dict] = mapped_column(JSONB)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvaluationVersion(Ordered, Base):
    __tablename__ = "evaluation_versions"
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("research.evaluation_datasets.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    body: Mapped[dict] = mapped_column(JSONB)
    fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("dataset_id", "number", name="uq_evaluation_version_number"),)


class EvaluationRun(Ordered, Base):
    __tablename__ = "evaluation_runs"
    id: Mapped[str] = mapped_column(ForeignKey("research.jobs.id"), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("research.evaluation_datasets.id"), index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("research.evaluation_versions.id"), index=True)
    parent_run_id: Mapped[str | None] = mapped_column(ForeignKey("research.evaluation_runs.id"))
    config: Mapped[dict] = mapped_column(JSONB)
    manifest: Mapped[dict] = mapped_column(JSONB)
    counters: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvaluationAttempt(Ordered, Base):
    __tablename__ = "evaluation_attempts"
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("research.evaluation_runs.id"), index=True)
    case_id: Mapped[str] = mapped_column(String(80))
    repetition: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    result: Mapped[dict] = mapped_column(JSONB, default=dict)
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("run_id", "case_id", "repetition", name="uq_evaluation_attempt_position"),)


class Followup(Base):
    __tablename__ = "followups"
    thread_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    message_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    report_id: Mapped[str] = mapped_column(String(160), primary_key=True, default="", server_default="")
    questions: Mapped[list] = mapped_column(JSONB)


class ReviewCheck(Ordered, Base):
    __tablename__ = "review_checks"
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    body: Mapped[dict] = mapped_column(JSONB)
    settled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))


class ReviewCandidate(Ordered, Base):
    __tablename__ = "review_candidates"
    symbol: Mapped[str] = mapped_column(String(30), primary_key=True)
    session: Mapped[str] = mapped_column(String(10))
    benchmark: Mapped[str] = mapped_column(String(30))
    note: Mapped[str] = mapped_column(Text, default="", server_default="")


class CandidateObservation(Ordered, Base):
    __tablename__ = "candidate_observations"
    symbol: Mapped[str] = mapped_column(String(30), primary_key=True)
    session: Mapped[str] = mapped_column(String(10), primary_key=True)
    benchmark: Mapped[str] = mapped_column(String(30), primary_key=True)
    origin: Mapped[str] = mapped_column(String(40), primary_key=True)
    report_id: Mapped[str] = mapped_column(String(160), primary_key=True, default="", server_default="")


class Outbox(Base):
    __tablename__ = "outbox"
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    topic: Mapped[str] = mapped_column(String(100))
    aggregate_id: Mapped[str] = mapped_column(String(160))
    payload: Mapped[dict] = mapped_column(JSONB)
    deduplication_key: Mapped[str] = mapped_column(String(250), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_type: Mapped[str | None] = mapped_column(String(100))
    __table_args__ = (Index("ix_outbox_pending", "available_at", postgresql_where=text("delivered_at IS NULL AND failed_at IS NULL")),)


class RunEvent(Base):
    __tablename__ = "run_events"
    sequence: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(160), index=True)
    event_id: Mapped[str] = mapped_column(String(160), unique=True)
    kind: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


LEGACY_MODELS = {model.__tablename__: model for model in (
    Report, Cache, Preference, Schedule, Job, HiddenTask, Followup, ReviewCheck, ReviewCandidate, CandidateObservation,
)}
