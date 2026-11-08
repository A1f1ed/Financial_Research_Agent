"""Same-origin online evaluation management; no raw SQL or credential APIs."""
import csv
import io
import json
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from src.documents.api import authorize_write, run
from src.persistence.jobs import JobRepository
from src.persistence.database import transaction
from src.persistence.models import EvaluationVersion, Document
from src.persistence.jobs import StateConflict
from .contracts import DatasetInput, DatasetEdit, RevisionAction, RunOptions
from .repository import EvaluationRepository, required
from .imports import ImportRequest, import_dataset

router = APIRouter(prefix="/research/evaluations")


@router.post("/datasets/import",status_code=201)
def import_cases(inputs:ImportRequest,request:Request):
    from fastapi import HTTPException
    authorize_write(request)
    def save():
        draft=import_dataset(inputs)
        if "split_policy" in inputs.payload:
            with transaction() as db:
                originals={label:db.get(Document,str(key)) for label,key in inputs.source_documents.items()}
                for case in inputs.payload["cases"]:
                    for label,pages in case.get("evidence",{}).items():
                        original=originals.get(label)
                        if original is None or original.removed_at or original.archived:
                            raise StateConflict("Select an existing active original for every source label")
                        if any(page > original.page_count for page in pages):
                            raise StateConflict("A referenced PDF page does not exist in its mapped original")
        return EvaluationRepository().save(draft)
    try:return run(save)
    except ValueError as error:raise HTTPException(422,str(error)) from None


def protect(body, reveal=False):
    if reveal: return body
    return {**body, "cases": [c if c["partition"] == "development" else
        {"id": c["id"], "name": c["name"], "partition": c["partition"], "target": c["target"], "protected": True} for c in body.get("cases", [])]}


@router.get("/datasets")
def datasets(archived: bool=False, page:int=Query(1,ge=1,le=100000)):
    return EvaluationRepository().datasets(archived, page)


@router.post("/datasets", status_code=201)
def create_dataset(inputs:DatasetInput, request:Request):
    authorize_write(request)
    return run(lambda: EvaluationRepository().save(inputs))


@router.get("/datasets/{key}")
def dataset(key:UUID, reveal_frozen:bool=False):
    return run(lambda:protect(EvaluationRepository().dataset(str(key)), reveal_frozen))


@router.put("/datasets/{key}")
def edit_dataset(key:UUID, inputs:DatasetEdit, request:Request):
    authorize_write(request)
    return run(lambda:EvaluationRepository().save(inputs, str(key)))


@router.post("/datasets/{key}/publish")
def publish(key:UUID, inputs:RevisionAction, request:Request):
    authorize_write(request)
    return run(lambda:EvaluationRepository().publish(str(key), inputs.expected_revision))


@router.post("/datasets/{key}/archive")
def archive(key:UUID, inputs:RevisionAction, request:Request):
    authorize_write(request)
    return run(lambda:EvaluationRepository().archive(str(key), inputs.expected_revision, True))


@router.post("/datasets/{key}/restore")
def restore(key:UUID, inputs:RevisionAction, request:Request):
    authorize_write(request)
    return run(lambda:EvaluationRepository().archive(str(key), inputs.expected_revision, False))


@router.get("/datasets/{key}/export")
def export_dataset(key:UUID, include_frozen:bool=False):
    data = run(lambda:EvaluationRepository().dataset(str(key)))
    body = {k:data[k] for k in ("name", "description", "cases")}
    if not include_frozen: body["cases"] = [c for c in body["cases"] if c["partition"] == "development"]
    return Response(json.dumps(body, ensure_ascii=False, indent=2), media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="evaluation-dataset.json"'})


@router.get("/versions/{key}")
def version(key:UUID, reveal_frozen:bool=False):
    def read():
        with transaction() as db:
            row = required(db, EvaluationVersion, key)
            return {"id": row.id, "dataset_id": row.dataset_id, "number": row.number, "fingerprint": row.fingerprint, **protect(row.body, reveal_frozen)}
    return run(read)


@router.get("/runs")
def runs(dataset_id:UUID|None=None, page:int=Query(1,ge=1,le=100000)):
    return EvaluationRepository().runs(str(dataset_id) if dataset_id else None, page)


@router.post("/runs", status_code=202)
def start(inputs:RunOptions, request:Request):
    authorize_write(request)
    return run(lambda:EvaluationRepository().start(inputs))


@router.get("/compare")
def compare(left:UUID, right:UUID):
    return run(lambda:EvaluationRepository().compare(str(left), str(right)))


@router.get("/runs/{key}")
def detail(key:UUID, page:int=Query(1,ge=1,le=100000), status:str=Query("",max_length=32)):
    return run(lambda:EvaluationRepository().detail(str(key),page,status=status))


@router.post("/runs/{key}/cancel")
def cancel(key:UUID, request:Request):
    authorize_write(request)
    run(lambda:EvaluationRepository().detail(str(key)))
    run(lambda:JobRepository().cancel(str(key)))
    return run(lambda:EvaluationRepository().detail(str(key)))


@router.post("/runs/{key}/retry", status_code=202)
def retry(key:UUID, inputs:RunOptions, request:Request):
    authorize_write(request)
    return run(lambda:EvaluationRepository().start(inputs.model_copy(update={"parent_run_id":key})))


@router.get("/runs/{key}/attempts/{attempt_id}")
def attempt(key:UUID, attempt_id:UUID):
    return run(lambda:EvaluationRepository().attempt(str(key),str(attempt_id)))


@router.get("/runs/{key}/export")
def export_run(key:UUID, format:str=Query("json",pattern="^(json|csv)$")):
    data = run(lambda:EvaluationRepository().detail(str(key),page_size=500))
    # Export metrics/provenance only. Inspect generated answers explicitly in the app.
    for item in data["attempts"]:
        item.pop("answer", None); item.pop("artifact", None)
    if format == "json": body = json.dumps(data,ensure_ascii=False,default=str,indent=2); media = "application/json"
    else:
        stream=io.StringIO(); writer=csv.DictWriter(stream,fieldnames=["case_id","repetition","status","elapsed_ms","model_calls","error_type"])
        writer.writeheader()
        for item in data["attempts"]:writer.writerow({k:item.get(k,"") for k in writer.fieldnames})
        body=stream.getvalue();media="text/csv"
    return Response(body,media_type=media,headers={"Content-Disposition":f'attachment; filename="evaluation-{key}.{format}"'})
