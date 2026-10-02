"""Fetching public web pages as text, used to verify research details against their source.

ADAPT never shows a phone number, email or address unless it appears on the page it is
attributed to. This fetcher reads that page. Because the URLs come from web search, it
refuses anything that isn't a public web address: http(s) only, ports 80/443, and every
resolved IP (re-checked on each redirect) must be globally routable. Bodies are capped
and only text content types are read.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Literal, Protocol
from urllib.parse import urljoin, urlsplit

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_TEXT_TYPES = ("text/html", "text/plain", "application/xhtml+xml")


class FetchedPage(BaseModel):
    url: str
    final_url: str
    text: str
    fetched_at: datetime


class PageFetcher(Protocol):
    mode: Literal["live", "demo"]

    async def fetch_text(self, url: str) -> FetchedPage | None: ...


class UnsafeUrl(ValueError):
    pass


def _is_public_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.is_global and not address.is_multicast


async def assert_public_url(url: str) -> list[str]:
    """Raise `UnsafeUrl` unless `url` is http(s) on a standard port and resolves only to
    public addresses."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise UnsafeUrl("malformed URL") from exc
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise UnsafeUrl("only http(s) URLs can be fetched")
    if parts.username is not None or parts.password is not None:
        raise UnsafeUrl("URL credentials are not allowed")
    if port not in (None, 80, 443):
        raise UnsafeUrl("non-standard port")
    host = parts.hostname
    try:
        ipaddress.ip_address(host)
        literal = True
    except ValueError:
        literal = False
    if literal:
        addresses = [host]
    else:
        if host.endswith((".local", ".internal", ".localhost")) or host == "localhost":
            raise UnsafeUrl("private host name")
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(
                host, port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM
            )
        except OSError as exc:
            raise UnsafeUrl("host does not resolve") from exc
        addresses = [str(info[4][0]) for info in infos]
    if not addresses or not all(_is_public_ip(a) for a in addresses):
        raise UnsafeUrl("host resolves to a non-public address")
    return sorted(set(addresses), key=lambda address: ":" in address)


class _TextExtractor(HTMLParser):
    """Visible text plus mailto:/tel: link targets (contacts are often only in hrefs)."""

    _SKIP = frozenset({"script", "style", "noscript", "template", "svg"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1
        for name, value in attrs:
            if name == "href" and value and value.lower().startswith(("mailto:", "tel:")):
                self._parts.append(value.split(":", 1)[1].split("?", 1)[0])

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth and data.strip():
            self._parts.append(data.strip())

    def text(self) -> str:
        return " ".join(self._parts)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # malformed markup: keep what was parsed
        logger.debug("html_parse_incomplete")
    return parser.text()


class SafeHttpPageFetcher:
    mode: Literal["live", "demo"] = "live"

    def __init__(
        self,
        *,
        timeout_seconds: float = 8.0,
        max_bytes: int = 1_500_000,
        max_redirects: int = 3,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._client = client or httpx.AsyncClient(
            timeout=timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            headers={
                "User-Agent": "ADAPT-research/0.1 (source verification)",
                "Accept": "text/html,text/plain;q=0.9",
            },
        )
        self._max_bytes = max_bytes
        self._max_redirects = max_redirects

    async def fetch_text(self, url: str) -> FetchedPage | None:
        current = url
        try:
            for _ in range(self._max_redirects + 1):
                addresses = await assert_public_url(current)
                original = httpx.URL(current)
                # Pin the validated address: the HTTP client must not resolve the host
                # a second time (DNS rebinding). Preserve Host and TLS certificate SNI.
                pinned = original.copy_with(host=addresses[0])
                async with self._client.stream(
                    "GET",
                    pinned,
                    headers={"Host": original.netloc.decode("ascii")},
                    extensions={"sni_hostname": original.host},
                ) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            return None
                        current = urljoin(current, location)
                        continue
                    if response.status_code != 200:
                        return None
                    content_type = response.headers.get("content-type", "").lower()
                    if not content_type.startswith(_TEXT_TYPES):
                        return None
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) >= self._max_bytes:
                            break
                    raw = bytes(body[: self._max_bytes]).decode(
                        response.encoding or "utf-8", errors="replace"
                    )
                    text = raw if content_type.startswith("text/plain") else html_to_text(raw)
                    return FetchedPage(
                        url=url, final_url=current, text=text, fetched_at=datetime.now(UTC)
                    )
        except UnsafeUrl as exc:
            logger.info("fetch_refused", extra={"reason": str(exc)})
        except httpx.HTTPError:
            logger.info("fetch_failed")
        return None

    async def aclose(self) -> None:
        await self._client.aclose()


class NoPageFetcher:
    """Offline mode: nothing is fetched, so nothing can be verified (and nothing is shown)."""

    mode: Literal["live", "demo"] = "demo"

    async def fetch_text(self, url: str) -> FetchedPage | None:
        return None
