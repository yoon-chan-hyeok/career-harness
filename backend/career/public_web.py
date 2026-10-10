"""Bounded, credential-free public page reader. Never a browser or a proxy."""

import http.client
import ipaddress
import re
import socket
import ssl
import zlib
from html.parser import HTMLParser
from time import monotonic
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

from career.provider_policy import StagePolicy
from career.request_budget import call_with_deadline, check_deadline

MAX_BYTES = 1_000_000
MAX_TEXT = 20_000
FETCH_SECONDS = 15


class PublicPageError(ValueError):
    pass


def public_url(value: str) -> str:
    """Validate syntax without resolving DNS; never expose credentials in errors."""
    try:
        if len(value) > 2048 or re.search(r"[\s\\\x00-\x1f\x7f]", value):
            raise ValueError()
        parsed = urlsplit(value)
        host = (parsed.hostname or "").encode("idna").decode("ascii").lower()
        if (parsed.scheme != "https" or parsed.username is not None or parsed.password is not None
                or parsed.port not in {None, 443} or not host or "%" in host):
            raise ValueError()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if (host.endswith((".localhost", ".local", ".internal")) or "." not in host
                    or not re.fullmatch(r"[a-z0-9.-]+", host) or host.endswith(".")):
                raise ValueError() from None
        else:
            if not address.is_global or address.is_multicast or address.is_reserved:
                raise ValueError()
        netloc = f"[{host}]" if ":" in host else host
        return urlunsplit(("https", netloc, quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~"),
                           quote(parsed.query, safe="%/?@!$&'()*+,;=:-._~"), ""))
    except (ValueError, UnicodeError):
        raise PublicPageError("공개된 HTTPS 주소를 입력해 주세요. 내부 주소·로그인 정보·별도 포트는 사용할 수 없습니다.") from None


def public_addresses(host: str) -> list[tuple]:
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    if not addresses:
        raise PublicPageError("자료 주소를 확인할 수 없습니다. 필요한 원문을 직접 붙여 넣어 주세요.")
    for _, _, _, _, target in addresses:
        address = ipaddress.ip_address(target[0])
        if (not address.is_global or address.is_multicast or address.is_reserved
                or getattr(address, "ipv4_mapped", None) is not None):
            raise PublicPageError("공개 인터넷 자료만 가져올 수 있습니다.")
    return addresses


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host: str, address: tuple, timeout: float):
        context = ssl.create_default_context()
        context.set_alpn_protocols(["http/1.1"])
        super().__init__(host, timeout=timeout, context=context)
        self.tls_context = context
        self.address = address

    def connect(self):
        # Connect to the already checked numeric address, while TLS verifies the
        # original hostname. No second DNS lookup and no environment proxy.
        family, kind, protocol, _, target = self.address
        raw = socket.socket(family, kind, protocol)
        raw.settimeout(self.timeout)
        try:
            raw.connect(target)
            self.sock = self.tls_context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ignored: list[str] = []
        self.parts: list[str] = []
        self.title: list[str] = []
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "template", "svg"}:
            self.ignored.append(tag)
        if tag == "title":
            self.in_title = True
        if tag in {"p", "br", "div", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if self.ignored and tag == self.ignored[-1]:
            self.ignored.pop()
        if tag == "title":
            self.in_title = False
        if tag in {"p", "div", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.ignored:
            self.parts.append(data)
            if self.in_title:
                self.title.append(data)


def _read_page(url: str) -> dict:
    deadline = monotonic() + FETCH_SECONDS
    current = public_url(url)
    for hop in range(4):
        check_deadline()
        if monotonic() >= deadline:
            raise PublicPageError("자료 응답 시간이 지났습니다. 원문을 직접 붙여 넣어 주세요.")
        parsed = urlsplit(current)
        host = parsed.hostname or ""
        address = public_addresses(host)[0]
        connection = _PinnedHTTPS(host, address, max(0.01, deadline - monotonic()))
        try:
            path = urlunsplit(("", "", parsed.path, parsed.query, ""))
            connection.request("GET", path, headers={
                "Accept": "text/html, text/plain", "Accept-Encoding": "identity",
                "User-Agent": "CareerHarness-PublicResearch/1.0",
            })
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                if hop == 3 or not location:
                    raise PublicPageError("주소 이동을 완료하지 못했습니다. 최종 자료 주소를 입력해 주세요.")
                current = public_url(urljoin(current, location))
                continue
            content_type = response.headers.get_content_type()
            if response.status != 200 or content_type not in {"text/html", "text/plain"}:
                raise PublicPageError("이 페이지는 직접 읽을 수 없습니다. 공개된 본문을 붙여 넣어 주세요.")
            content_encoding = response.getheader("Content-Encoding", "identity").lower().strip()
            if content_encoding not in {"identity", "gzip"}:
                raise PublicPageError("이 페이지의 압축 형식은 지원하지 않습니다. 본문을 붙여 넣어 주세요.")
            chunks, size = [], 0
            while size <= MAX_BYTES:
                check_deadline()
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise PublicPageError("자료 응답 시간이 지났습니다. 원문을 직접 붙여 넣어 주세요.")
                if connection.sock is not None:
                    connection.sock.settimeout(remaining)
                chunk = response.read1(min(65536, MAX_BYTES + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            raw = b"".join(chunks)
            if len(raw) > MAX_BYTES:
                raise PublicPageError("페이지가 너무 큽니다. 필요한 본문을 직접 붙여 넣어 주세요.")
            if content_encoding == "gzip":
                decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
                raw = decoder.decompress(raw, MAX_BYTES + 1)
                if len(raw) > MAX_BYTES or not decoder.eof or decoder.unused_data:
                    raise PublicPageError("압축 본문이 너무 크거나 완전하지 않습니다. 필요한 본문을 붙여 넣어 주세요.")
            encoding = response.headers.get_content_charset() or "utf-8"
            try:
                text = raw.decode(encoding)
            except (LookupError, UnicodeDecodeError):
                raise PublicPageError("페이지의 문자 형식을 확인하지 못했습니다. 본문을 붙여 넣어 주세요.") from None
            parser = _Text()
            if content_type == "text/html":
                parser.feed(text)
                text = "\n".join(" ".join(line.split()) for line in "".join(parser.parts).splitlines() if line.strip())
            if not text.strip() or len(text) > MAX_TEXT:
                raise PublicPageError("읽을 본문이 없거나 2만 자를 넘습니다. 필요한 부분을 직접 붙여 넣어 주세요.")
            return {"url": current, "title": " ".join(parser.title).strip()[:300] or host, "text": text.strip()}
        finally:
            connection.close()
    raise PublicPageError("자료를 가져오지 못했습니다.")


def fetch_page(url: str) -> dict:
    canonical = public_url(url)
    try:
        return call_with_deadline(lambda: _read_page(canonical), StagePolicy(model="public-web", timeout_seconds=FETCH_SECONDS))
    except PublicPageError:
        raise
    except Exception:
        # Errors must not echo remote content, redirect URLs or connection data.
        raise PublicPageError("자료를 가져오지 못했습니다. 주소를 확인하거나 원문을 직접 붙여 넣어 주세요.") from None
