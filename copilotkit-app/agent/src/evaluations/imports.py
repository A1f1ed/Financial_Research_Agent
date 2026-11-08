"""Import the prior source contract without silently claiming its complex rules were scored."""
import json
from pydantic import BaseModel, Field, StrictInt
from typing import Annotated, Literal
from uuid import UUID
from .contracts import DatasetInput


class ImportRequest(BaseModel):
    payload: dict
    source_documents: dict[str,UUID] = Field(default_factory=dict, max_length=50)
    name: str = Field(default="Imported evaluation contract",min_length=1,max_length=120)


class LegacyCase(BaseModel):
    id: str = Field(min_length=1,max_length=80,pattern=r"^[a-zA-Z0-9_-]+$")
    question: str = Field(min_length=2,max_length=500)
    category: Literal["financial","boundary","vision","wiki","relations"]
    split: Literal["development","acceptance"]
    evidence: dict[str,list[Annotated[StrictInt,Field(ge=1,le=2000)]]] = Field(default_factory=dict,max_length=50)
    expected: dict = Field(default_factory=dict)
    basis: object = None


class LegacyScope(BaseModel):
    as_of: str = Field(min_length=10,max_length=40)
    market: Literal["HK","US","SH","SZ","SG"] = "HK"


class LegacyContract(BaseModel):
    version: str = Field(min_length=1,max_length=100)
    split_policy: dict
    default_scope: LegacyScope
    cases: list[LegacyCase] = Field(min_length=1,max_length=100)


def import_dataset(request):
    data=request.payload
    if len(json.dumps(data,ensure_ascii=False).encode())>1024*1024:raise ValueError("Import is limited to 1 MB")
    if "split_policy" not in data:return DatasetInput.model_validate(data)
    contract=LegacyContract.model_validate(data)
    cutoff=contract.default_scope.as_of
    if not cutoff:raise ValueError("The source contract needs an explicit cutoff")
    cases=[]
    for item in contract.cases:
        source=item.model_dump()
        documents=[];pages=[]
        for label,numbers in source.get("evidence",{}).items():
            if label not in request.source_documents:raise ValueError(f"Map the original document for source label: {label}")
            key=str(request.source_documents[label]);documents.append(key)
            pages.extend({"document_id":key,"page_number":int(page)} for page in numbers)
        target={"vision":"vision","wiki":"wiki","relations":"manual_review"}.get(source["category"],"agent")
        if not documents:
            target="manual_review";scope=None
        else:scope={"document_ids":list(dict.fromkeys(documents)),"as_of_at" if "T" in cutoff else "as_of":cutoff,"market":contract.default_scope.market}
        cases.append({"id":source["id"],"name":source["question"][:160],"question":source["question"],"target":target,
            "partition":source["split"],"scope":scope,"expected":{"pages":pages[:20],"manual_review_required":True,
                "manual_reference":{"original_expected":source.get("expected",{}),"original_basis":source.get("basis"),"original_evidence":source.get("evidence",{})},
                "reference_note":"Imported source contract. Human must verify source mapping and adapt supported checks; original complex rules are not automatically scored."}})
    return DatasetInput(name=request.name,description="Imported contract draft; manual source/rule adaptation required. No automatic publication or run.",cases=cases)
