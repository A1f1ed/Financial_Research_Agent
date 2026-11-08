"""Malformed inputs and network boundaries; no model or public network calls."""
import io
import json
import unittest
from unittest.mock import patch

from PIL import Image
from pydantic import ValidationError
from pypdf import PdfWriter
from src.documents.contracts import DocumentMetadata, MetadataUpdate, safe_filename
from src.documents.network import SourceRejected, download, public_addresses, validate_url
from src.documents.parser import InvalidDocument, inspect_document


class DocumentBoundaryTests(unittest.TestCase):
    def test_real_file_types_empty_encrypted_and_page_count(self):
        for body in (b"", b"report.pdf", b"%PDF-fake"):
            with self.subTest(body=body), self.assertRaises(InvalidDocument):
                inspect_document(body)
        writer = PdfWriter(); writer.add_blank_page(612, 792); writer.encrypt("not-public")
        stream = io.BytesIO(); writer.write(stream)
        with self.assertRaises(InvalidDocument):
            inspect_document(stream.getvalue())
        writer = PdfWriter()
        for _ in range(501):
            writer.add_blank_page(10, 10)
        stream = io.BytesIO(); writer.write(stream)
        with self.assertRaisesRegex(InvalidDocument, "500"):
            inspect_document(stream.getvalue())
        stream = io.BytesIO(); Image.new("RGB", (10, 10)).save(stream, "PNG")
        self.assertEqual(inspect_document(stream.getvalue())["media_type"], "image/png")

    def test_metadata_dates_have_explicit_precision_and_audit_reason(self):
        value = DocumentMetadata(title="Report", published_at="2026-10-31T18:00:00+08:00", publication_basis="Exchange timestamp")
        self.assertIsNone(value.published_on)
        for extra in ({"published_at": "2026-10-31T18:00:00"}, {"published_on": "2026-10-31"}):
            with self.assertRaises(ValidationError):
                DocumentMetadata(title="Report", **extra)
        with self.assertRaises(ValidationError):
            MetadataUpdate(title="Report", expected_revision=1, reason="   ")
        self.assertEqual(safe_filename("C:\\private\\bad\nname.pdf"), "badname.pdf")

    def test_domain_schemes_ports_credentials_and_private_dns_rejected(self):
        for url in ("http://www.hkexnews.hk/a.pdf", "https://hkexnews.hk.evil.com/a.pdf",
                    "https://localhost/a.pdf", "https://169.254.169.254/a.pdf", "https://www.hkexnews.hk:8443/a",
                    "https://user@www.hkexnews.hk/a", "https://www.hkexnews.hk/a?redirect=x", "https://www.hkexnews.hk/a#x"):
            with self.subTest(url=url), self.assertRaises(SourceRejected):
                validate_url(url)
        self.assertEqual(validate_url("https://www.hkexnews.hk/a.pdf"), ("www.hkexnews.hk", "/a.pdf"))
        for addresses in (["127.0.0.1"], ["8.8.8.8", "10.0.0.1"], ["::1"], ["169.254.169.254"]):
            with patch("src.documents.network.socket.getaddrinfo", return_value=[(None, None, None, None, (ip, 443)) for ip in addresses]):
                with self.assertRaises(SourceRejected):
                    public_addresses("www.hkexnews.hk")

    def test_redirect_revalidated_and_response_size_and_encoding_bounded(self):
        class Response:
            status = 302
            headers = {"Location": "https://localhost/private"}
            def getheader(self, name, default=None): return self.headers.get(name, default)
            def read(self, size): return b""
        class Connection:
            response = Response()
            def __init__(self, *args): pass
            def request(self, *args, **kwargs): pass
            def getresponse(self): return self.response
            def close(self): pass
        with patch("src.documents.network.public_addresses", return_value=["8.8.8.8"]), patch("src.documents.network.PinnedHTTPSConnection", Connection):
            with self.assertRaises(SourceRejected): download("https://www.hkexnews.hk/a.pdf")
            Connection.response.status = 200
            Connection.response.headers = {"Content-Length": str(51 * 1024 * 1024)}
            with self.assertRaisesRegex(SourceRejected, "50 MB"): download("https://www.hkexnews.hk/a.pdf")
            Connection.response.headers = {"Content-Encoding": "gzip"}
            with self.assertRaisesRegex(SourceRejected, "Compressed"): download("https://www.hkexnews.hk/a.pdf")

    def test_explicit_https_dns_checks_question_status_and_public_answer(self):
        class Response:
            status = 200
            result = {"Status": 0, "Question": [{"name": "www.hkexnews.hk.", "type": 1}],
                      "Answer": [{"type": 1, "data": "8.8.8.8"}]}
            def read(self, size): return json.dumps(self.result).encode()
        class Connection:
            def __init__(self, *args, **kwargs): pass
            def request(self, *args, **kwargs): pass
            def getresponse(self): return Response()
            def close(self): pass
        with patch.dict("os.environ", {"APERTURE_DOCUMENT_DNS": "google_doh"}), patch("src.documents.network.http.client.HTTPSConnection", Connection):
            self.assertEqual(public_addresses("www.hkexnews.hk"), ["8.8.8.8"])
            for changes in ({"Status": 2}, {"CD": True}, {"TC": True}, {"Question": [{"name": "evil.example.", "type": 1}]},
                            {"Answer": [{"type": 1, "data": "127.0.0.1"}]}):
                with patch.object(Response, "result", {**Response.result, **changes}), self.assertRaises(SourceRejected):
                    public_addresses("www.hkexnews.hk")


if __name__ == "__main__":
    unittest.main()
