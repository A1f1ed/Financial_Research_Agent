"""Deterministic page-local chunks with exact source-text offsets."""
import hashlib

CHUNK_VERSION = "page-offset-v1-900-100"
MAX_CHUNKS = 5000


def page_chunks(pages):
    result = []
    for page in pages:
        if page.status != "text_ready" or not page.text.strip(): continue
        start = 0
        while start < len(page.text):
            end = min(len(page.text), start + 900)
            # Prefer a paragraph/sentence boundary without dropping characters.
            if end < len(page.text):
                boundary = max(page.text.rfind("\n", start+600, end), page.text.rfind("。", start+600, end), page.text.rfind(". ", start+600, end))
                if boundary >= start+600: end = boundary+1
            quote = page.text[start:end]
            if quote.strip():
                result.append({"page_number": page.page_number, "start_offset": start, "end_offset": end,
                    "text": quote, "text_sha256": hashlib.sha256(quote.encode()).hexdigest(),
                    "extraction_version": page.extraction_version})
                if len(result) > MAX_CHUNKS: raise ValueError("Document exceeds the 5000-chunk indexing limit")
            if end == len(page.text): break
            start = end-100
    return result


def pages_fingerprint(pages):
    digest = hashlib.sha256()
    for page in pages:
        digest.update(f"{page.page_number}:{page.status}:{page.extraction_version}:".encode())
        digest.update(hashlib.sha256(page.text.encode()).digest())
    return digest.hexdigest()
