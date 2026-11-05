"""
Turn what Chromium dumped into a short list of search results.

The browser container is the untrusted side: this module reads its output with
the standard library parser only, never evaluates anything, and returns plain
strings of bounded size. Pages are never shown to the model, only these lists.
"""
from __future__ import annotations

import base64
import re
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote_plus, urlparse

MAX_QUERY_CHARS = 400
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_SPACES = re.compile(r"\s+")

# Texts of the bot-protection pages (captcha, challenge) a search engine serves
# instead of results. Compared in lower case.
_BLOCK_MARKERS = (
    "captcha", "/challenge", "unusual traffic", "cf-challenge", "b_captcha",
    "anomaly-modal",  # DuckDuckGo's bot challenge (ADR-0014)
)
# Marks a real Bing results page, with or without results in it. Structural
# markers only: Bing translates its visible texts.
_PAGE_MARKERS = (
    'id="b_results"', 'class="b_algo', 'class="b_no"',
    # DuckDuckGo HTML (ADR-0040): result links, or its "no results" block.
    'class="result__a"', 'class="no-results"',
)
# Chromium error pages (DNS failure, refused connection, URL blocked by policy).
_NETWORK_ERROR_MARKERS = (
    "err_name_not_resolved",
    "err_connection",
    "err_internet_disconnected",
    "err_blocked_by_administrator",
    "neterror",
)
_BING_HOST = "bing.com"
_DDG_HOST = "duckduckgo.com"
# The HTML version of DuckDuckGo, made for browsers without JavaScript (ADR-0040).
DDG_SEARCH_HOST = "html.duckduckgo.com"


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def clean_query(query: object) -> str:
    """The query to search for, or ValueError. Control characters never go in a URL."""
    if not isinstance(query, str):
        raise ValueError("the query must be a string")
    query = _SPACES.sub(" ", _CONTROL_CHARS.sub(" ", query)).strip()
    if not query:
        raise ValueError("the query is empty")
    if len(query) > MAX_QUERY_CHARS:
        raise ValueError(f"the query is longer than {MAX_QUERY_CHARS} characters")
    return query


def build_search_url(query: str, host: str) -> str:
    # The query is the only user-controlled part of the URL.
    path = "/html/" if host == DDG_SEARCH_HOST else "/search"
    return f"https://{host}{path}?q={quote_plus(clean_query(query))}"


def looks_empty(html: str) -> bool:
    """True when the browser dumped nothing at all (bot challenge, JS-only page)."""
    return not html.strip()


def looks_like_results_page(html: str) -> bool:
    """True for a Bing results page, with or without results in it."""
    lowered = html.lower()
    return any(marker in lowered for marker in _PAGE_MARKERS)


def looks_blocked(html: str) -> bool:
    """True for a bot-protection page. A results page is never one, even if a
    result talks about captchas."""
    lowered = html.lower()
    if looks_like_results_page(lowered):
        return False
    return any(marker in lowered for marker in _BLOCK_MARKERS)


def looks_like_network_error(html: str) -> bool:
    """True for a Chromium error page: the engine could not be reached."""
    lowered = html.lower()
    return any(marker in lowered for marker in _NETWORK_ERROR_MARKERS)


def _tidy(text: str, limit: int) -> str:
    text = _SPACES.sub(" ", _CONTROL_CHARS.sub(" ", text)).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _is_bing(host: str) -> bool:
    return host == _BING_HOST or host.endswith("." + _BING_HOST)


def _is_ddg(host: str) -> bool:
    return host == _DDG_HOST or host.endswith("." + _DDG_HOST)


def _external_url(href: str) -> str | None:
    """`href` if it is an http(s) URL outside Bing, else None."""
    if href.startswith("//"):
        href = "https:" + href
    if _CONTROL_CHARS.search(href):
        return None
    parsed = urlparse(href)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    if _is_bing(parsed.hostname.lower()) or _is_ddg(parsed.hostname.lower()):
        return None
    return href


def _decode_redirect(parsed_query: str) -> str | None:
    """Target of a Bing /ck/a link: `u=a1` followed by the URL in unpadded base64url."""
    value = parse_qs(parsed_query).get("u", [""])[0]
    if not value.startswith("a1"):
        return None
    payload = value[2:]
    try:
        raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        return raw.decode("utf-8")
    except ValueError:  # binascii.Error, UnicodeDecodeError and non-ASCII input
        return None


def _real_url(href: str) -> str | None:
    """The page a result points to. Bing wraps it in a /ck/a redirect link."""
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    host = (parsed.hostname or "").lower()
    if _is_bing(host):
        if parsed.path == "/ck/a":
            target = _decode_redirect(parsed.query)
            return _external_url(target) if target else None
        return None  # internal links
    return _external_url(href)


class _ResultParser(HTMLParser):
    """Collects, for each <li class="b_algo">, the first link of its <h2> and the
    first <p> of its caption. Anything else in the item (sitelinks, favicon link
    above the title, nested lists) is ignored."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict[str, str]] = []
        self._li_depth = 0  # > 0 while inside a result
        self._in_h2 = False
        self._caption_depth = 0  # > 0 while inside div.b_caption
        self._capture: str | None = None  # "title" or "snippet"
        self._buffer: list[str] = []

    def _finish_capture(self) -> None:
        if self._capture and self.items:
            current = self.items[-1]
            if not current[self._capture]:
                current[self._capture] = "".join(self._buffer)
        self._capture, self._buffer = None, []

    def _close_item(self) -> None:
        self._finish_capture()
        self._li_depth = 0
        self._in_h2 = False
        self._caption_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        if tag == "li":
            if self._li_depth:
                self._li_depth += 1
            elif "b_algo" in classes:
                self.items.append({"href": "", "title": "", "snippet": ""})
                self._li_depth = 1
            return
        if not self._li_depth:
            return
        if tag == "h2":
            self._in_h2 = True
        elif tag == "a" and self._in_h2 and not self.items[-1]["href"] and not self._capture:
            href = attributes.get("href")
            if href:
                self.items[-1]["href"] = href
                self._capture, self._buffer = "title", []
        elif tag == "div":
            if self._caption_depth:
                self._caption_depth += 1
            elif "b_caption" in classes:
                self._caption_depth = 1
        elif tag == "p" and self._caption_depth and not self._capture:
            if not self.items[-1]["snippet"]:
                self._capture, self._buffer = "snippet", []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self._li_depth:
            return
        if tag == "li":
            self._li_depth -= 1
            if self._li_depth == 0:
                self._close_item()
        elif tag == "a" and self._capture == "title":
            self._finish_capture()
        elif tag == "p" and self._capture == "snippet":
            self._finish_capture()
        elif tag == "h2":
            self._in_h2 = False
        elif tag == "div" and self._caption_depth:
            self._caption_depth -= 1

    def close(self) -> None:
        super().close()
        self._close_item()  # a page cut in the middle of a result keeps what was read


def _ddg_real_url(href: str) -> str | None:
    """The page a DuckDuckGo result points to: `//duckduckgo.com/l/?uddg=<URL>`."""
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if _is_ddg((parsed.hostname or "").lower()):
        if parsed.path != "/l/":
            return None  # internal links
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        return _external_url(target) if target else None
    return _external_url(href)


class _DdgResultParser(HTMLParser):
    """Collects, for each result of DuckDuckGo HTML, the link `a.result__a` (title)
    and the text of `.result__snippet`. Ads (`result--ad`) are skipped."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict[str, str]] = []
        self._ad = False
        self._capture: str | None = None  # "title" or "snippet"
        self._tag = ""  # tag whose end closes the capture
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        if tag == "div" and "result" in classes:
            self._ad = "result--ad" in classes
        if self._capture or self._ad:
            return
        if tag == "a" and "result__a" in classes and attributes.get("href"):
            self.items.append({"href": attributes["href"] or "", "title": "", "snippet": ""})
            self._capture, self._tag, self._buffer = "title", tag, []
        elif "result__snippet" in classes and self.items and not self.items[-1]["snippet"]:
            self._capture, self._tag, self._buffer = "snippet", tag, []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._capture and tag == self._tag:
            self.items[-1][self._capture] = "".join(self._buffer)
            self._capture, self._buffer = None, []


def parse_results(
    html: str, max_results: int = 10, snippet_chars: int = 300, title_chars: int = 150
) -> list[SearchResult]:
    """Results found in the page, without duplicates, ads or non-web links. The
    engine (Bing or DuckDuckGo HTML) is recognised from the page itself."""
    ddg = 'class="result__a"' in html
    parser: _ResultParser | _DdgResultParser = _DdgResultParser() if ddg else _ResultParser()
    real_url = _ddg_real_url if ddg else _real_url
    parser.feed(html)
    parser.close()

    results: list[SearchResult] = []
    seen: set[str] = set()
    for item in parser.items:
        url = real_url(item["href"])
        if url is None or url in seen:
            continue
        seen.add(url)
        results.append(
            SearchResult(
                title=_tidy(item["title"], title_chars) or url,
                url=url,
                snippet=_tidy(item["snippet"], snippet_chars),
            )
        )
        if len(results) >= max_results:
            break
    return results
