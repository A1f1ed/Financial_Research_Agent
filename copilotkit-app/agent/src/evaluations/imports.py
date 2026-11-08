"""Import the prior source contract without silently claiming its complex rules were scored."""
import json
from pydantic import BaseModel, Field
from uuid import UUID
from .contracts import DatasetInput


class ImportRequest(BaseModel):
    payload: dict
    source_documents: dict[str,UUID] = Field(default_factory=dict, max_length=50)
    name: str = Field(default="Imported evaluation contract",min_length=1,max_length=120)


def import_dataset(request):
    data=request.payload
    if len(json.dumps(data,ensure_ascii=False).encode())>1024*1024:raise ValueError("Import is limited to 1 MB")
    if "split_policy" not in data:return DatasetInput.model_validate(data)
    if not isinstance(data.get("cases"),list) or not 1<=len(data["cases"])<=100:raise ValueError("Import 1 to 100 cases")
    cutoff=data.get("default_scope",{}).get("as_of")
    if not cutoff:raise ValueError("The source contract needs an explicit cutoff")
    cases=[]
    for source in data["cases"]:
        documents=[];pages=[]
        for label,numbers in source.get("evidence",{}).items():
            if label not in request.source_documents:raise ValueError(f"Map the original document for source label: {label}")
            key=str(request.source_documents[label]);documents.append(key)
            pages.extend({"document_id":key,"page_number":int(page)} for page in numbers)
        target={"vision":"vision","wiki":"wiki","relations":"manual_review"}.get(source["category"],"agent")
        if not documents:
            target="manual_review";scope=None
        else:scope={"document_ids":list(dict.fromkeys(documents)),"as_of_at" if "T" in cutoff else "as_of":cutoff,"market":"HK"}
        cases.append({"id":source["id"],"name":source["question"][:160],"question":source["question"],"target":target,
            "partition":source["split"],"scope":scope,"expected":{"pages":pages[:20],"manual_review_required":True,
                "manual_reference":{"original_expected":source.get("expected",{}),"original_basis":source.get("basis"),"original_evidence":source.get("evidence",{})},
                "reference_note":"Imported source contract. Human must verify source mapping and adapt supported checks; original complex rules are not automatically scored."}})
    return DatasetInput(name=request.name,description="Imported contract draft; manual source/rule adaptation required. No automatic publication or run.",cases=cases)
