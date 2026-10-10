import gzip
import io
import socket
from email.message import Message

import pytest
from career import public_web as web


@pytest.mark.parametrize("url", [
    "http://example.com/", "file:///tmp/test", "https://u:p@example.com", "https://example.com:444/",
    "https://localhost/", "https://service.local/", "https://127.0.0.1/", "https://169.254.169.254/latest/",
    "https://[::1]/", "https://10.0.0.1/", "https://224.0.0.1/", "https://example.com\\@localhost/",
    "https://example.com/\nHost:internal", "https://example.com./",
])
def test_reject_nonpublic_or_ambiguous_urls(url):
    with pytest.raises(web.PublicPageError):
        web.public_url(url)


def address(ip):
    return (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, 443))


def test_mixed_dns_and_rebinding_targets_are_rejected_before_connect(monkeypatch):
    monkeypatch.setattr(web.socket, "getaddrinfo", lambda *_, **__: [address("93.184.216.34"), address("127.0.0.1")])
    with pytest.raises(web.PublicPageError):
        web.public_addresses("example.com")


class Response:
    def __init__(self, body=b"<title>Source</title><p>Public company text.</p>", status=200, **headers):
        self.status = status
        self.headers = Message()
        self.headers["Content-Type"] = "text/html; charset=utf-8"
        for key, value in headers.items():
            key = key.replace("_", "-")
            if key in self.headers:
                self.headers.replace_header(key, value)
            else:
                self.headers[key] = value
        self.body = io.BytesIO(body)

    def getheader(self, key, default=None):
        return self.headers.get(key, default)

    def read1(self, size):
        return self.body.read(size)


def transport(monkeypatch, responses, ips=None):
    connections = []
    dns = []
    def resolve(host, *_args, **_kwargs):
        dns.append(host)
        return [address((ips or {}).get(host, "93.184.216.34"))]
    class Connection:
        sock = None

        def __init__(self, host, pinned, timeout):
            connections.append((host, pinned, timeout))

        def request(self, method, path, headers):
            assert method == "GET" and "Authorization" not in headers and "Cookie" not in headers
            assert headers["Accept-Encoding"] == "identity"

        def getresponse(self):
            return responses.pop(0)

        def close(self):
            pass
    monkeypatch.setattr(web.socket, "getaddrinfo", resolve)
    monkeypatch.setattr(web, "_PinnedHTTPS", Connection)
    return connections, dns


def test_redirect_resolves_and_validates_every_destination(monkeypatch):
    connections, dns = transport(monkeypatch, [Response(status=302, Location="https://internal.example.com/data")],
                                  {"internal.example.com": "10.1.2.3"})
    with pytest.raises(web.PublicPageError):
        web.fetch_page("https://example.com/")
    assert dns == ["example.com", "internal.example.com"] and len(connections) == 1


def test_public_fetch_strips_scripts_keeps_text_and_pins_checked_address(monkeypatch):
    connections, dns = transport(monkeypatch, [Response(body=b"<title>Company</title><script>secret()</script><style>hide</style><p>Public &amp; quoted.</p>")])
    page = web.fetch_page("https://example.com/company#fragment")
    assert page["text"] == "Company\nPublic & quoted." and page["title"] == "Company"
    assert page["url"] == "https://example.com/company" and dns == ["example.com"]
    assert connections[0][1][-1][0] == "93.184.216.34"


@pytest.mark.parametrize("response", [
    Response(body=b"x" * (web.MAX_BYTES + 1)), Response(body=b"x" * (web.MAX_TEXT + 1)),
    Response(Content_Type="application/pdf"), Response(Content_Encoding="br"), Response(status=403),
    Response(status=302, Location="http://example.com/plain"),
])
def test_limits_and_unsupported_pages_fail_without_partial_research(monkeypatch, response):
    transport(monkeypatch, [response])
    with pytest.raises(web.PublicPageError):
        web.fetch_page("https://example.com/")


def test_tls_connect_uses_numeric_target_but_checks_original_hostname(monkeypatch):
    events = []
    class Socket:
        def settimeout(self, value):
            events.append(("timeout", value))

        def connect(self, target):
            events.append(("connect", target))

        def close(self):
            events.append(("close",))
    class Context:
        def set_alpn_protocols(self, value):
            assert value == ["http/1.1"]

        def wrap_socket(self, raw, server_hostname):
            events.append(("tls", server_hostname))
            return raw
    monkeypatch.setattr(web.ssl, "create_default_context", Context)
    monkeypatch.setattr(web.socket, "socket", lambda *_: Socket())
    connection = web._PinnedHTTPS("example.com", address("93.184.216.34"), 10)
    connection.connect()
    assert ("connect", ("93.184.216.34", 443)) in events and ("tls", "example.com") in events


def test_gzip_is_bounded_after_decompression_and_incomplete_streams_fail(monkeypatch):
    transport(monkeypatch, [Response(body=gzip.compress(b"<p>Company source text.</p>"), Content_Encoding="gzip")])
    assert web.fetch_page("https://example.com/")["text"] == "Company source text."
    for payload in (gzip.compress(b"x" * (web.MAX_BYTES + 1)), gzip.compress(b"text")[:-2]):
        transport(monkeypatch, [Response(body=payload, Content_Encoding="gzip")])
        with pytest.raises(web.PublicPageError):
            web.fetch_page("https://example.com/")
