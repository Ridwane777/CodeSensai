"""
Search the web from a disposable Chromium container.

Why a container and not `requests`: a search page is hostile input parsed by a
large engine. If Chromium is exploited, the attacker lands in a throw-away,
unprivileged, read-only container that holds nothing, instead of in the agent's
process. Only plain text results come back.

Layers, outermost first (see docs/architecture/sandbox.md for what each one does not cover):

1. Container: non-root, no capabilities, read-only root, no volumes, memory /
   CPU / process limits, killed on timeout, removed after every search.
2. Chromium resolves one host only (`--host-resolver-rules`) and an enterprise
   policy baked into the image blocks every other URL.
3. JavaScript is off (image policy): the results page does not need it.
4. Output is parsed with the standard library into bounded plain strings.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from docker.errors import ImageNotFound

from . import docker_utils
from .config import SANDBOX_LABEL_KEY, SANDBOX_LABEL_VALUE, BrowserConfig
from .docker_utils import DOCKER_ERRORS, LOG_CONFIG
from .search_parsing import (
    SearchResult,
    build_search_url,
    looks_blocked,
    looks_empty,
    looks_like_network_error,
    looks_like_results_page,
    parse_results,
)

log = logging.getLogger(__name__)

IMAGE_HELP = "Build it once with: docker build -t sensai-browser:latest docker/browser"


# Below this, starting another browser is pointless: it would be cut at once.
MIN_ATTEMPT_S = 5.0
# Failures another engine cannot fix: the same Docker, image or query would fail too.
_NO_FALLBACK = frozenset({"ImageMissing", "SandboxError", "InvalidQuery"})


@dataclass
class SearchOutcome:
    ok: bool
    query: str = ""
    results: list[SearchResult] = field(default_factory=list)
    error_type: str | None = None
    error_message: str | None = None
    duration_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "query": self.query,
            "results": [r.to_dict() for r in self.results],
            "error_type": self.error_type,
            "error_message": self.error_message,
            "duration_s": self.duration_s,
        }

    @classmethod
    def failure(
        cls, error_type: str, message: str, query: str = "", duration_s: float = 0.0
    ) -> SearchOutcome:
        return cls(
            ok=False,
            query=query,
            error_type=error_type,
            error_message=message,
            duration_s=duration_s,
        )


class BrowserSandbox:
    """Run one web search in a fresh container. `search` never raises."""

    def __init__(self, config: BrowserConfig | None = None, client: Any | None = None) -> None:
        self.config = config or BrowserConfig()
        self._client = client  # tests inject a fake here

    def search(
        self, query: str, max_results: int | None = None, timeout_s: float | None = None
    ) -> SearchOutcome:
        """Tries each engine of `search_hosts` in turn, within one time budget, and
        keeps the first that gives results (ADR-0040). Measured on 2026-10-24: Bing
        answered on the first word of the query only ; DuckDuckGo had been blocked
        on another network on 2026-10-14. One engine alone is not enough."""
        cfg = self.config
        try:
            build_search_url(query, cfg.search_host)
        except ValueError as exc:
            return SearchOutcome.failure("InvalidQuery", str(exc))
        wanted = self._clamp_results(max_results)
        budget = cfg.clamp_timeout(timeout_s)
        deadline = time.monotonic() + budget
        outcome = SearchOutcome.failure("Timeout", "No time left to search.", query)
        for attempt, host in enumerate(cfg.search_hosts):
            # The first engine gets the whole budget; a fallback only what is left.
            remaining = budget if attempt == 0 else deadline - time.monotonic()
            if attempt and remaining < MIN_ATTEMPT_S:
                break
            outcome = self._search_once(query, host, wanted, remaining)
            if outcome.ok and outcome.results:
                return outcome
            if outcome.error_type in _NO_FALLBACK:
                return outcome
            log.info("web search on %s gave nothing usable (%s), trying the next engine",
                     host, outcome.error_type or "no results")
        return outcome

    def _search_once(self, query: str, host: str, wanted: int, timeout: float) -> SearchOutcome:
        cfg = self.config
        url = build_search_url(query, host)

        container = None
        started = time.monotonic()
        try:
            client = self._get_client()
            docker_utils.ensure_image(client, cfg.image, pull=False)
            container = client.containers.create(**self._container_kwargs(url))
            started = time.monotonic()
            container.start()
            timed_out, exit_code = docker_utils.wait_for_exit(container, timeout)
            duration = time.monotonic() - started
            dump = container.logs(stdout=True, stderr=False)
            oom = docker_utils.oom_killed(container)
        except ImageNotFound:
            return SearchOutcome.failure(
                "ImageMissing", f"The browser image {cfg.image} is not built. {IMAGE_HELP}", query
            )
        except DOCKER_ERRORS as exc:
            log.warning("browser sandbox infrastructure failure: %s", exc)
            return SearchOutcome.failure(
                "SandboxError",
                f"Docker is unavailable or failed: {exc}",
                query,
                time.monotonic() - started,
            )
        finally:
            docker_utils.remove_container(container)

        return self._build_outcome(query, dump, exit_code, timed_out, oom, wanted, duration)

    # -- internals ------------------------------------------------------------

    def _clamp_results(self, wanted: int | None) -> int:
        cap = self.config.max_results
        if isinstance(wanted, bool) or not isinstance(wanted, int) or wanted <= 0:
            return cap
        return min(wanted, cap)

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = docker_utils.connect()
        return self._client

    def _chromium_command(self, url: str) -> list[str]:
        return [
            "chromium",
            "--headless=new",
            # Chromium's own sandbox needs kernel features Docker's default
            # profile removes. The container is the sandbox here: unprivileged,
            # no capabilities, read-only, disposable.
            "--no-sandbox",
            "--disable-gpu",
            "--disable-extensions",
            "--disable-sync",
            "--disable-background-networking",
            "--disable-component-update",
            "--no-first-run",
            "--no-default-browser-check",
            "--user-data-dir=/tmp/profile",
            # Without it Bing sees "HeadlessChrome" and serves a poorer page (ADR-0017).
            f"--user-agent={self.config.user_agent}",
            # No --blink-settings=scriptEnabled=false: with it --dump-dom prints
            # nothing (measured on Bing, 2026-10-14). JavaScript is switched off by
            # the policy baked into the image ("JavascriptEnabled": false) instead.
            # Every name except the search host fails to resolve.
            "--host-resolver-rules=MAP * ~NOTFOUND"
            + "".join(f" , EXCLUDE {host}" for host in self.config.search_hosts),
            "--dump-dom",
            url,
        ]

    def _container_kwargs(self, url: str) -> dict[str, Any]:
        cfg = self.config
        return {
            "image": cfg.image,
            "command": self._chromium_command(url),  # a list: no shell involved
            "labels": {SANDBOX_LABEL_KEY: SANDBOX_LABEL_VALUE},
            "environment": {"HOME": "/tmp"},
            "user": cfg.user,
            # Default bridge: outbound access is needed to reach the search
            # engine. See docs/architecture/sandbox.md for what keeps it from reaching more.
            "read_only": True,
            "tmpfs": {"/tmp": f"rw,nosuid,size={cfg.tmpfs_size}"},
            "shm_size": cfg.shm_size,
            "mem_limit": cfg.mem_limit,
            "memswap_limit": cfg.mem_limit,
            "nano_cpus": cfg.nano_cpus,
            "pids_limit": cfg.pids_limit,
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges"],
            "log_config": LOG_CONFIG,
            "auto_remove": False,
        }

    def _build_outcome(
        self,
        query: str,
        dump: bytes,
        exit_code: int | None,
        timed_out: bool,
        oom: bool,
        wanted: int,
        duration: float,
    ) -> SearchOutcome:
        duration = round(duration, 3)
        if timed_out:
            return SearchOutcome.failure(
                "Timeout", "The search took too long and was stopped.", query, duration
            )
        if oom:
            return SearchOutcome.failure(
                "OOMKilled", "The browser ran out of memory and was stopped.", query, duration
            )
        if exit_code != 0:
            return SearchOutcome.failure(
                "BrowserError", f"The browser exited with code {exit_code}.", query, duration
            )

        html = dump[: self.config.max_output_bytes].decode("utf-8", errors="replace")
        if looks_blocked(html):
            return SearchOutcome.failure(
                "SearchBlocked",
                "The search engine refused the request (bot protection). Try again later.",
                query,
                duration,
            )
        if looks_empty(html):
            return SearchOutcome.failure(
                "SearchEmptyPage",
                "The search engine returned an empty page (likely a bot challenge or a "
                "JavaScript-only page); no results could be read.",
                query,
                duration,
            )
        if not looks_like_results_page(html):
            if looks_like_network_error(html):
                return SearchOutcome.failure(
                    "SearchUnavailable",
                    "The search engine could not be reached from the sandbox.",
                    query,
                    duration,
                )
            return SearchOutcome.failure(
                "SearchUnexpectedPage",
                "The search engine answered with a page that is not a results page.",
                query,
                duration,
            )
        results = parse_results(html, max_results=wanted)
        return SearchOutcome(ok=True, query=query, results=results, duration_s=duration)
