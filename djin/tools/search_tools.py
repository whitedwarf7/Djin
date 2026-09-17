"""Internet search and page reading. All returned content is treated as untrusted."""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlparse

import httpx

from djin.config import get_settings
from djin.tools.registry import Risk, ToolError, register, wrap_untrusted

MAX_PAGE_CHARS = 12000
MAX_DOWNLOAD_BYTES = 3_000_000
MAX_REDIRECTS = 3


def _assert_public_url(url: str) -> None:
    """Block non-HTTP schemes and any host resolving to a private/loopback address (SSRF)."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ToolError("Only http and https URLs can be fetched.")
    if not parsed.hostname:
        raise ToolError("URL has no host.")

    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise ToolError(f"Could not resolve host '{parsed.hostname}'.") from exc

    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            raise ToolError(
                f"Refusing to fetch '{parsed.hostname}': it resolves to a non-public address."
            )


def _safe_get(url: str) -> httpx.Response:
    current = url
    with httpx.Client(follow_redirects=False, timeout=25) as client:
        for _ in range(MAX_REDIRECTS + 1):
            _assert_public_url(current)
            response = client.get(
                current,
                headers={"User-Agent": "Djin/0.1 (personal assistant)"},
            )
            if response.is_redirect and (location := response.headers.get("location")):
                current = str(httpx.URL(current).join(location))
                continue
            return response
    raise ToolError("Too many redirects.")


def _brave(query: str, count: int) -> list[dict[str, str]]:
    settings = get_settings()
    response = httpx.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": count},
        headers={"Accept": "application/json", "X-Subscription-Token": settings.brave_api_key},
        timeout=25,
    )
    if response.status_code >= 400:
        raise ToolError(f"Brave search failed ({response.status_code}): {response.text[:200]}")
    results = response.json().get("web", {}).get("results", [])
    return [
        {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": re.sub(r"<[^>]+>", "", item.get("description", "")),
        }
        for item in results
    ]


def _tavily(query: str, count: int) -> list[dict[str, str]]:
    settings = get_settings()
    response = httpx.post(
        "https://api.tavily.com/search",
        json={
            "api_key": settings.tavily_api_key,
            "query": query,
            "max_results": count,
            "search_depth": "basic",
        },
        timeout=25,
    )
    if response.status_code >= 400:
        raise ToolError(f"Tavily search failed ({response.status_code}): {response.text[:200]}")
    return [
        {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("content", ""),
        }
        for item in response.json().get("results", [])
    ]


@register(
    name="web_search",
    description=(
        "Search the public internet and return titles, URLs and snippets."
        " Use this before answering questions about current events or unfamiliar topics."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "count": {"type": "integer", "description": "Number of results (1-10).", "default": 5},
        },
        "required": ["query"],
    },
    risk=Risk.READ,
    untrusted_output=True,
    tags=("web",),
)
def web_search(query: str, count: int = 5) -> str:
    settings = get_settings()
    if not settings.search_configured:
        raise ToolError(
            "Web search is not configured. Set DJIN_SEARCH_PROVIDER to 'brave' or 'tavily'"
            " and add the matching API key in .env."
        )
    limit = max(1, min(int(count), 10))
    results = _brave(query, limit) if settings.search_provider == "brave" else _tavily(query, limit)
    if not results:
        return f"No search results for: {query}"

    body = "\n".join(
        f"- {item['title']}\n  {item['url']}\n  {item['snippet'][:400]}" for item in results
    )
    return wrap_untrusted("web_search", body)


@register(
    name="fetch_url",
    description=(
        "Fetch a public web page and return its readable text."
        " Use after web_search to read a specific result."
    ),
    parameters={
        "type": "object",
        "properties": {"url": {"type": "string", "description": "Absolute http(s) URL."}},
        "required": ["url"],
    },
    risk=Risk.READ,
    untrusted_output=True,
    tags=("web",),
)
def fetch_url(url: str) -> str:
    response = _safe_get(url)
    if response.status_code >= 400:
        raise ToolError(f"Page returned HTTP {response.status_code}.")
    if len(response.content) > MAX_DOWNLOAD_BYTES:
        raise ToolError("Page is too large to process.")

    content_type = response.headers.get("content-type", "")
    if "html" in content_type:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
            tag.decompose()
        title = soup.title.get_text(strip=True) if soup.title else url
        text = re.sub(r"\n{3,}", "\n\n", soup.get_text("\n")).strip()
    elif "text" in content_type or "json" in content_type:
        title = url
        text = response.text
    else:
        raise ToolError(f"Unsupported content type: {content_type or 'unknown'}")

    if len(text) > MAX_PAGE_CHARS:
        text = text[:MAX_PAGE_CHARS] + "\n...[truncated]"
    return wrap_untrusted("web_page", f"URL: {url}\nTitle: {title}\n\n{text}")
