"""Download public source PDFs and derive local, page-addressable research fixtures.

Run with the agent Python environment. No LLM, embedding API or account data is used.
The original PDFs, extracted content and rendered pages stay under ignored local-data/.
"""
import argparse
import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import fitz
import httpx

ROOT = Path(__file__).resolve().parents[3]
CATALOG = ROOT / "data-catalog/finance-research-v1/sources.json"
OUTPUT = ROOT / "local-data/finance-research-v1"
HOSTS = {"www.hkexnews.hk", "www1.hkexnews.hk", "www.geelyauto.com.hk", "geelyauto.com.hk", "eur-lex.europa.eu", "ec.europa.eu"}
MAX_BYTES = 100 * 1024 * 1024


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def download(source, offline):
    document_id = source["id"]
    if not re.fullmatch(r"[a-z0-9_]+", document_id):
        raise ValueError("Unsafe document identifier")
    url = source["url"]
    if urlsplit(url).scheme != "https" or urlsplit(url).hostname not in HOSTS:
        raise ValueError("Source URL is outside the primary-source allowlist")
    target = OUTPUT / "raw" / f"{document_id}.pdf"
    if target.exists():
        with fitz.open(target) as doc:
            if not doc.is_pdf or doc.page_count == 0:
                raise ValueError("Existing PDF is invalid")
        previous_path = OUTPUT / "manifest.json"
        previous = {}
        if previous_path.exists():
            previous = next((row for row in json.loads(previous_path.read_text(encoding="utf-8"))["documents"]
                             if row["id"] == document_id), {})
        provenance = {key: previous[key] for key in
                      ("downloaded_at", "resolved_url", "http_last_modified", "http_content_type") if key in previous}
        return {**source, **provenance, "download_status": "cached"}
    if offline:
        raise FileNotFoundError(target.name)
    last_error = None
    for attempt in range(2):
        try:
            headers = {"User-Agent": "ApertureResearchCorpus/1.0 (public issuer documents; local development)", "Accept": "application/pdf"}
            with httpx.stream("GET", url, headers=headers, follow_redirects=True, timeout=90) as response:
                response.raise_for_status()
                if urlsplit(str(response.url)).hostname not in HOSTS:
                    raise ValueError("Unexpected source redirect host")
                count = 0
                temporary = target.with_suffix(".part")
                with temporary.open("wb") as stream:
                    for block in response.iter_bytes():
                        count += len(block)
                        if count > MAX_BYTES:
                            raise ValueError("PDF exceeds 100 MB download limit")
                        stream.write(block)
                with fitz.open(temporary) as doc:
                    if not doc.is_pdf or not doc.page_count:
                        raise ValueError("Response is not a readable PDF")
                temporary.replace(target)
                return {**source, "download_status": "downloaded", "resolved_url": str(response.url),
                        "downloaded_at": datetime.now(timezone.utc).isoformat(),
                        "http_last_modified": response.headers.get("last-modified"),
                        "http_content_type": response.headers.get("content-type")}
        except Exception as error:
            last_error = error
            if attempt == 0:
                time.sleep(1)
    raise RuntimeError(f"{document_id}: {type(last_error).__name__}: {last_error}") from None


def derive(source):
    document_id = source["id"]
    pdf = OUTPUT / "raw" / f"{document_id}.pdf"
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
    page_path = OUTPUT / "pages" / f"{document_id}.jsonl"
    block_path = OUTPUT / "blocks" / f"{document_id}.jsonl"
    text_path = OUTPUT / "text" / f"{document_id}.txt"
    chunks = []
    page_summaries = []
    with fitz.open(pdf) as doc, page_path.open("w", encoding="utf-8") as pages, block_path.open("w", encoding="utf-8") as blocks, text_path.open("w", encoding="utf-8") as text_file:
        for index, page in enumerate(doc):
            text = page.get_text(sort=True)
            page_id = f"{document_id}:p{index + 1:04}"
            record = {"document_id": document_id, "page_id": page_id, "pdf_page": index + 1,
                      "pdf_label": page.get_label(), "width": page.rect.width, "height": page.rect.height,
                      "text": text}
            pages.write(json.dumps(record, ensure_ascii=False) + "\n")
            text_file.write(f"\n\n===== PDF PAGE {index + 1} | {page_id} =====\n\n{text}")
            for number, block in enumerate(page.get_text("blocks", sort=True)):
                if len(block) >= 7 and block[6] == 0 and str(block[4]).strip():
                    blocks.write(json.dumps({"document_id": document_id, "page_id": page_id, "pdf_page": index + 1,
                                             "block_id": f"{page_id}:b{number:04}", "bbox": list(block[:4]),
                                             "text": block[4]}, ensure_ascii=False) + "\n")
            if text.strip():
                # Baseline chunks never cross pages. These are not table-normalized facts.
                start = 0
                while start < len(text):
                    end = min(len(text), start + 1600)
                    chunks.append({"chunk_id": f"{page_id}:c{start:06}", "document_id": document_id,
                                   "pdf_page": index + 1, "page_id": page_id, "start_char": start, "end_char": end,
                                   "text": text[start:end], "source_sha256": digest,
                                   "published_on": source.get("published_on"), "symbols": source["symbols"],
                                   "source_url": source["url"], "is_trusted_instruction": False})
                    if end == len(text):
                        break
                    start = end - 160
            page_summaries.append({"pdf_page": index + 1, "characters": len(text), "preview": " ".join(text.split())[:150]})
        return {**source, "sha256": digest, "bytes": pdf.stat().st_size, "page_count": doc.page_count,
                "pdf_metadata": doc.metadata, "raw_path": pdf.relative_to(OUTPUT).as_posix(),
                "pages_path": page_path.relative_to(OUTPUT).as_posix(), "blocks_path": block_path.relative_to(OUTPUT).as_posix(),
                "text_path": text_path.relative_to(OUTPUT).as_posix(), "extraction": "PyMuPDF text/blocks; no OCR; layout and tables require source-page verification",
                "pages_without_extracted_text": [row["pdf_page"] for row in page_summaries if row["characters"] < 20]}, chunks, page_summaries


def render_pages(selections):
    rendered = []
    for document_id, page_numbers in selections.items():
        if not re.fullmatch(r"[a-z0-9_]+", document_id):
            raise ValueError("Unsafe document identifier")
        with fitz.open(OUTPUT / "raw" / f"{document_id}.pdf") as doc:
            source_digest = hashlib.sha256(Path(doc.name).read_bytes()).hexdigest()
            for number in page_numbers:
                if not 1 <= number <= doc.page_count:
                    raise ValueError(f"Invalid page {document_id}:{number}")
                page = doc[number - 1]
                output = OUTPUT / "images" / f"{document_id}__p{number:04}.png"
                pixmap = page.get_pixmap(matrix=fitz.Matrix(1.75, 1.75), alpha=False)
                pixmap.save(output)
                rendered.append({"document_id": document_id, "pdf_page": number, "path": output.relative_to(OUTPUT).as_posix(),
                                 "width": pixmap.width, "height": pixmap.height,
                                 "sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "source_sha256": source_digest,
                                 "kind": "unaltered_full_pdf_page_render", "source_path": f"raw/{document_id}.pdf"})
    write_json(OUTPUT / "image_manifest.json", rendered)
    print(f"Rendered {len(rendered)} full source pages.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--render-selection", type=Path)
    args = parser.parse_args()
    for directory in ["raw", "pages", "blocks", "text", "images", "discovery"]:
        (OUTPUT / directory).mkdir(parents=True, exist_ok=True)
    if args.render_selection:
        render_pages(json.loads(args.render_selection.read_text(encoding="utf-8-sig")))
        return
    sources = json.loads(CATALOG.read_text(encoding="utf-8-sig"))
    successes = {}
    failures = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        pending = {executor.submit(download, source, args.offline): source for source in sources}
        for future in as_completed(pending):
            source = pending[future]
            try:
                successes[source["id"]] = future.result()
                print(f"Ready: {source['id']}", flush=True)
            except Exception as error:
                failures.append({"id": source["id"], "url": source["url"], "error": str(error)})
                print(f"Failed: {source['id']} ({error})", flush=True)
    manifest = []
    all_chunks = []
    summaries = {}
    for source in sources:
        if source["id"] not in successes:
            continue
        item, chunks, summary = derive(successes[source["id"]])
        manifest.append(item)
        all_chunks.extend(chunks)
        summaries[source["id"]] = summary
    with (OUTPUT / "chunks.jsonl").open("w", encoding="utf-8") as stream:
        for row in all_chunks:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_json(OUTPUT / "manifest.json", {"corpus": "finance-research-v1", "generated_at": datetime.now(timezone.utc).isoformat(),
                                          "license": "No blanket redistribution license. Original source rights and notices apply.",
                                          "documents": manifest, "failures": failures})
    write_json(OUTPUT / "page_index.json", summaries)
    print(json.dumps({"documents": len(manifest), "pages": sum(row["page_count"] for row in manifest),
                      "chunks": len(all_chunks), "failures": len(failures)}, ensure_ascii=True), flush=True)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
