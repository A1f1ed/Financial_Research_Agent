"""Check corpus provenance, page references, chunk offsets and rendered-image integrity."""
import hashlib
import json
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "local-data/finance-research-v1"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main():
    manifest = read_json(OUTPUT / "manifest.json")
    assert not manifest["failures"], manifest["failures"]
    documents = {row["id"]: row for row in manifest["documents"]}
    sources = {row["id"]: row for row in read_json(ROOT / "data-catalog/finance-research-v1/sources.json")}
    assert set(documents) == set(sources), "Missing or unexpected originals"
    pages = {}
    for document_id, row in documents.items():
        original = OUTPUT / row["raw_path"]
        assert hashlib.sha256(original.read_bytes()).hexdigest() == row["sha256"], document_id
        assert original.stat().st_size == row["bytes"], document_id
        with fitz.open(original) as doc:
            assert doc.page_count == row["page_count"], document_id
        records = [json.loads(line) for line in (OUTPUT / row["pages_path"]).read_text(encoding="utf-8").splitlines()]
        assert [p["pdf_page"] for p in records] == list(range(1, row["page_count"] + 1)), document_id
        for page in records:
            assert page["document_id"] == document_id
            pages[page["page_id"]] = page
    chunk_count = 0
    seen_chunks = set()
    for line in (OUTPUT / "chunks.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        page = pages[row["page_id"]]
        document = documents[row["document_id"]]
        assert row["chunk_id"] not in seen_chunks
        seen_chunks.add(row["chunk_id"])
        assert row["document_id"] == page["document_id"]
        assert row["pdf_page"] == page["pdf_page"]
        assert 0 <= row["start_char"] < row["end_char"] <= len(page["text"])
        assert row["text"] == page["text"][row["start_char"]:row["end_char"]]
        assert row["source_sha256"] == document["sha256"]
        assert row["source_url"] == document["url"]
        assert row["published_on"] == document.get("published_on")
        assert row["is_trusted_instruction"] is False
        chunk_count += 1
    images = read_json(OUTPUT / "image_manifest.json")
    selected = read_json(ROOT / "data-catalog/finance-research-v1/render-selection.json")
    assert {(row["document_id"], row["pdf_page"]) for row in images} == {
        (document_id, number) for document_id, numbers in selected.items() for number in numbers}
    for row in images:
        image_path = OUTPUT / row["path"]
        pixmap = fitz.Pixmap(image_path)
        assert (pixmap.width, pixmap.height) == (row["width"], row["height"])
        assert hashlib.sha256(image_path.read_bytes()).hexdigest() == row["sha256"]
        assert row["source_sha256"] == documents[row["document_id"]]["sha256"]
        assert 1 <= row["pdf_page"] <= documents[row["document_id"]]["page_count"]
    for case in read_json(ROOT / "data-catalog/finance-research-v1/evaluation-seeds.json")["cases"]:
        for evidence in case.get("evidence_routes", []):
            assert evidence["document_id"] in documents
            for number in evidence.get("pdf_pages", []):
                assert 1 <= number <= documents[evidence["document_id"]]["page_count"]
    print(json.dumps({"documents": len(documents), "pages": len(pages), "chunks": chunk_count,
                      "images": len(images), "status": "passed"}))


if __name__ == "__main__":
    main()
