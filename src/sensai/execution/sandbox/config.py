"""Resource and isolation limits of the Python sandbox."""
from __future__ import annotations

from dataclasses import dataclass

# Put on every container so leftovers can be found and removed.
SANDBOX_LABEL_KEY = "sensai.sandbox"
SANDBOX_LABEL_VALUE = "1"


@dataclass(frozen=True)
class SandboxConfig:
    image: str = "python:3.12-slim"
    default_timeout_s: float = 10.0
    max_timeout_s: float = 60.0
    max_code_bytes: int = 100 * 1024
    max_output_bytes: int = 64 * 1024
    mem_limit: str = "256m"
    nano_cpus: int = 500_000_000  # 0.5 CPU
    pids_limit: int = 64
    user: str = "65534:65534"
    working_dir: str = "/tmp"
    tmpfs_size: str = "16m"

    def clamp_timeout(self, timeout_s: float | None) -> float:
        """A usable timeout: the default if missing or invalid, capped at the maximum."""
        if timeout_s is None or isinstance(timeout_s, bool):
            return self.default_timeout_s
        try:
            value = float(timeout_s)
        except (TypeError, ValueError):
            return self.default_timeout_s
        if value != value or value <= 0:  # NaN or non-positive
            return self.default_timeout_s
        return min(value, self.max_timeout_s)


@dataclass(frozen=True)
class BrowserConfig:
    """Limits of the Chromium container used to search the web."""

    # Built locally from docker/browser/Dockerfile: there is no registry to pull from.
    image: str = "sensai-browser:latest"
    # The only hosts the browser can resolve, in the order they are tried: the
    # next one is used when the previous blocks or finds nothing (ADR-0040).
    # Must match the image's policy file.
    search_hosts: tuple[str, ...] = ("html.duckduckgo.com", "www.bing.com")
    # Headless Chromium announces "HeadlessChrome" by default and Bing then serves
    # an impoverished page (0 or off-topic results, measured 2026-10-14). ADR-0017.
    user_agent: str = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
    )
    default_timeout_s: float = 25.0
    max_timeout_s: float = 45.0
    max_output_bytes: int = 1024 * 1024  # size of the page dump read back
    max_results: int = 10
    mem_limit: str = "768m"
    nano_cpus: int = 1_000_000_000  # 1 CPU
    pids_limit: int = 256  # Chromium starts many helper processes
    shm_size: str = "256m"  # Chromium crashes with the 64 MB default
    user: str = "65534:65534"
    tmpfs_size: str = "128m"

    @property
    def search_host(self) -> str:
        """The engine tried first."""
        return self.search_hosts[0]

    def clamp_timeout(self, timeout_s: float | None) -> float:
        if timeout_s is None or isinstance(timeout_s, bool):
            return self.default_timeout_s
        try:
            value = float(timeout_s)
        except (TypeError, ValueError):
            return self.default_timeout_s
        if value != value or value <= 0:
            return self.default_timeout_s
        return min(value, self.max_timeout_s)
