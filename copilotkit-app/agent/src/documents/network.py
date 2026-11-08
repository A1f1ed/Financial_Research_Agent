"""Bounded official-source downloads, with validation at every redirect.

The TLS socket connects to an already checked public IP while preserving the
original hostname for certificate validation/SNI, avoiding a second DNS lookup.
"""
import http.client
import ipaddress
import json
import os
import socket
import ssl
import time
from urllib.parse import unquote, urlencode, urljoin, urlsplit

from .contracts import MAX_PDF_BYTES, safe_filename

OFFICIAL_DOMAINS = ("hkexnews.hk", "bydglobal.com", "geelyauto.com.hk", "ec.europa.eu")


class SourceRejected(ValueError):
    pass


def validate_url(url):
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.fragment or parsed.query or parsed.port not in (None, 443)):
            raise ValueError()
        hostname = parsed.hostname.lower().rstrip(".")
        if not any(hostname == domain or hostname.endswith("." + domain) for domain in OFFICIAL_DOMAINS):
            raise ValueError()
        if any(ord(char) <= 32 for char in url) or "\\" in url:
            raise ValueError()
    except ValueError:
        raise SourceRejected("Use a direct HTTPS file link from a supported official issuer, exchange or policy source") from None
    return hostname, parsed.path or "/"


def public_addresses(hostname):
    mode = os.getenv("APERTURE_DOCUMENT_DNS", "system")
    if mode == "google_doh":
        # Explicit deployment setting for VPN fake-IP DNS environments. The
        # resolver host is fixed, TLS is verified, and every answer must still
        # be public. No environment proxy or caller-provided resolver URL.
        validate_url("https://" + hostname + "/")
        connection = http.client.HTTPSConnection("dns.google", timeout=5, context=ssl.create_default_context())
        try:
            connection.request("GET", "/resolve?" + urlencode({"name": hostname, "type": "A", "edns_client_subnet": "0.0.0.0/0"}),
                               headers={"Accept": "application/dns-json"})
            response = connection.getresponse()
            body = response.read(32769)
            if response.status != 200 or len(body) > 32768:
                raise SourceRejected("Public DNS resolver is unavailable; retry later or upload the original file")
            result = json.loads(body)
            question = result.get("Question", [])
            if (result.get("Status") != 0 or result.get("TC") or result.get("CD")
                    or len(question) != 1 or question[0].get("name", "").rstrip(".").lower() != hostname.lower()
                    or question[0].get("type") != 1):
                raise SourceRejected("Public DNS resolver could not verify this source")
            addresses = list(dict.fromkeys(row["data"] for row in result.get("Answer", []) if row.get("type") == 1))
        except (ValueError, KeyError, TypeError):
            raise SourceRejected("Public DNS resolver returned an invalid response") from None
        finally:
            connection.close()
    elif mode == "system":
        addresses = list(dict.fromkeys(item[4][0] for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)))
    else:
        raise SourceRejected("Document DNS setting is unsupported")
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise SourceRejected("Source resolved to a non-public address; configure public DNS or upload the original file")
    return sorted(addresses, key=lambda value: ipaddress.ip_address(value).version)


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, address, timeout):
        super().__init__(host, port=443, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        self.sock = self._context.wrap_socket(socket.create_connection((self.address, 443), timeout=self.timeout),
                                              server_hostname=self.host)


def download(url, checkpoint=lambda: None):
    started = time.monotonic()
    current = url
    for redirect in range(4):
        checkpoint()
        hostname, path = validate_url(current)
        addresses = public_addresses(hostname)
        remaining = 45 - (time.monotonic() - started)
        if remaining <= 0:
            raise TimeoutError("Official-source download time limit exceeded")
        connection = PinnedHTTPSConnection(hostname, addresses[0], min(10, remaining))
        try:
            connection.request("GET", path, headers={"Accept-Encoding": "identity", "User-Agent": "ApertureResearch/1.0 document-import"})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location or redirect == 3:
                    raise SourceRejected("Too many or invalid source redirects")
                current = urljoin(current, location)
                validate_url(current)
                continue
            if response.status != 200:
                raise SourceRejected("Official source did not return a downloadable file")
            if response.getheader("Content-Encoding", "identity").lower() not in ("", "identity"):
                raise SourceRejected("Compressed transport is unsupported; upload the original file instead")
            length = response.getheader("Content-Length")
            if length and (not length.isdigit() or int(length) > MAX_PDF_BYTES):
                raise SourceRejected("Source exceeds the 50 MB download limit")
            result = bytearray()
            while True:
                checkpoint()
                if time.monotonic() - started > 45:
                    raise TimeoutError("Official-source download time limit exceeded")
                chunk = response.read(min(256 * 1024, MAX_PDF_BYTES + 1 - len(result)))
                if not chunk:
                    break
                result.extend(chunk)
                if len(result) > MAX_PDF_BYTES:
                    raise SourceRejected("Source exceeds the 50 MB download limit")
            return bytes(result), safe_filename(unquote(urlsplit(current).path)), current
        finally:
            connection.close()
    raise SourceRejected("Source download could not be completed")
