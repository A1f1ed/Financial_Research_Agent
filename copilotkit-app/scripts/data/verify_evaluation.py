"""Validate/freeze the reviewed evaluation contract, not model answer scores."""
import argparse
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CATALOG = ROOT / "data-catalog/finance-research-v1"
CORPUS = ROOT / "local-data/finance-research-v1"


def sha(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def calculate(spec):
    values = list(map(lambda value: Decimal(str(value)), spec["inputs"]))
    if spec["operation"] == "sum":
        result = sum(values)
    elif spec["operation"] == "pct_change":
        result = (values[0] / values[1] - 1) * 100
    elif spec["operation"] == "ratio_percent":
        result = values[0] / values[1] * 100
    else:
        raise ValueError("Unknown calculation operation")
    if "result" in spec and result != Decimal(str(spec["result"])):
        raise ValueError("Frozen calculation does not reconcile")
    return str(result.quantize(Decimal("0.000001")))


def verify(freeze=False):
    path = CATALOG / "evaluation-v1.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    sources = {source["id"]: source for source in json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))["documents"]}
    cases = document["cases"]
    assert len({item["id"] for item in cases}) == len(cases) == 24
    assert Counter(item["category"] for item in cases) == {"financial": 6, "vision": 6, "relations": 4, "wiki": 4, "boundary": 4}
    assert Counter(item["split"] for item in cases) == {"development": 16, "acceptance": 8}
    results, hashes = {}, {}
    for item in cases:
        assert item["question"] and item["basis"] and item["expected"]["behavior"]
        scope = item.get("scope", document["default_scope"])
        assert scope["mode"] in {"strict_as_of", "document_reading"}
        assert (scope["as_of"] is not None) == (scope["mode"] == "strict_as_of")
        for source_id, pages in item["evidence"].items():
            source = sources[source_id]
            assert pages and all(isinstance(page, int) and 1 <= page <= source["page_count"] for page in pages)
            file = CORPUS / "raw" / (source_id + ".pdf")
            if source_id not in hashes:
                hashes[source_id] = sha(file)
                assert hashes[source_id] == source["sha256"], "Local source differs from reviewed manifest"
        results[item["id"]] = {key: calculate(item["expected"][key]) for key in ("formula", "secondary_formula") if key in item["expected"]}
    lock = {"contract_sha256": sha(path), "source_sha256": hashes,
            "acceptance_ids": [item["id"] for item in cases if item["split"] == "acceptance"]}
    lock_path = CATALOG / "evaluation-v1.freeze.json"
    if freeze:
        if lock_path.exists():
            raise FileExistsError("Frozen contract exists; create a reviewed new version rather than overwrite it")
        lock_path.write_text(json.dumps({"frozen_at": datetime.now(timezone.utc).isoformat(), **lock}, indent=2) + "\n", encoding="utf-8")
    frozen = json.loads(lock_path.read_text(encoding="utf-8"))
    assert all(frozen[key] == value for key, value in lock.items()), "Frozen contract/source drift"
    report = {"verified_at": datetime.now(timezone.utc).isoformat(), "case_count": 24, "acceptance_count": 8,
              "contract_and_sources_unchanged": True, "calculation_checks": results,
              "model_evaluation": "not_run", "independent_human_review": "not_claimed"}
    output = ROOT / "local-data/validation/evaluation-contract.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "calculation_checks"}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", action="store_true", help="One-time freeze, refuses overwrite")
    verify(parser.parse_args().freeze)
