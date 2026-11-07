from fastapi import APIRouter, Query, Request
from uuid import UUID
from src.documents.api import authorize_write, run
from .contracts import CollectionAction, CollectionEdit, CollectionInput, ConversationRequest, IndexRequest, MembershipChange, ScopeRequest, SearchRequest
from .repository import CollectionRepository

router = APIRouter(prefix="/research/knowledge")


@router.get("/collections")
def collections(q: str = Query(default="", max_length=200), archived: bool = False,
                page: int = Query(default=1, ge=1, le=100000), page_size: int = Query(default=20, ge=1, le=100)):
    return CollectionRepository().list(q, archived, page, page_size)


@router.post("/collections", status_code=201)
def create(inputs: CollectionInput, request: Request):
    authorize_write(request)
    return CollectionRepository().create(inputs)


@router.get("/collections/{key}")
def detail(key: str): return run(lambda: CollectionRepository().detail(key))


@router.put("/collections/{key}")
def edit(key: str, inputs: CollectionEdit, request: Request):
    authorize_write(request)
    return run(lambda: CollectionRepository().edit(key, inputs))


@router.post("/collections/{key}/members")
def members(key: str, inputs: MembershipChange, request: Request):
    authorize_write(request)
    return run(lambda: CollectionRepository().members(key, inputs))


@router.post("/collections/{key}/archive")
def archive(key: str, inputs: CollectionAction, request: Request):
    authorize_write(request)
    return run(lambda: CollectionRepository().archive(key, inputs.expected_revision))


@router.post("/collections/{key}/restore")
def restore(key: str, inputs: CollectionAction, request: Request):
    authorize_write(request)
    return run(lambda: CollectionRepository().archive(key, inputs.expected_revision, False))


@router.get("/collections/{key}/history")
def history(key: str, page: int = Query(default=1, ge=1, le=100000), page_size: int = Query(default=20, ge=1, le=100)):
    return run(lambda: CollectionRepository().history(key, page, page_size))


@router.post("/scope")
def scope(inputs: ScopeRequest): return run(lambda: CollectionRepository().scope(inputs))


@router.get("/embedding")
def embedding_settings():
    from .embeddings import public_settings
    return public_settings()


from .embeddings import EmbeddingSettings


@router.put("/embedding")
def save_embedding(inputs: EmbeddingSettings, request: Request):
    authorize_write(request)
    from .embeddings import save_settings
    return save_settings(inputs)


@router.post("/embedding/test")
async def test_embedding(request: Request):
    authorize_write(request)
    from .embeddings import test_settings
    return await test_settings()


@router.post("/indices")
def build_indices(inputs: IndexRequest, request: Request):
    authorize_write(request)
    from .indexing import IndexRepository
    return run(lambda: IndexRepository().create(inputs))


@router.get("/indices")
def indices(document_id: list[UUID] = Query(default=[], max_length=50)):
    from .indexing import IndexRepository
    return run(lambda: IndexRepository().list([str(key) for key in document_id]))


@router.post("/search")
async def search_documents(inputs: SearchRequest, request: Request):
    authorize_write(request)
    from .retrieval import search
    from fastapi import HTTPException
    from src.persistence.jobs import StateConflict
    try: return await search(inputs)
    except StateConflict as error: raise HTTPException(409, str(error)) from None
    except LookupError: raise HTTPException(404, "Selected research scope is unavailable") from None
    except Exception as error: raise HTTPException(502, f"Search could not complete ({type(error).__name__}); no answer was generated") from None


@router.get("/searches/{key}")
def saved_search(key: str):
    from .retrieval import search_detail
    return run(lambda: search_detail(key))


@router.post("/conversations", status_code=201)
def create_conversation(inputs: ConversationRequest, request: Request):
    authorize_write(request)
    from .conversations import ConversationRepository
    return run(lambda: ConversationRepository().create(inputs))


@router.get("/conversations/{key}")
def conversation(key: UUID, include_evidence: bool = False):
    from .conversations import ConversationRepository
    repository = ConversationRepository()
    return {"binding": repository.get(str(key)), "search_count": repository.search_count(str(key)),
            "searches": repository.searches(str(key)) if include_evidence else []}
