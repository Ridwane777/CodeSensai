"""Convert a document (PDF, Office, EPUB…) to Markdown in a throw-away container.

Issue #64, ADR-0034, level 3. Parsers of complex formats are where malicious
files strike (pypdf alone had several denial-of-service CVEs in 2025-2026), so
the conversion runs with MarkItDown inside the `sensai-docs` image, with the
same hardening as the Python sandbox: no network, read-only root, no
capabilities, memory / CPU / process / time limits. The only host file the
container sees is the document, mounted read-only.

Built locally from docker/docs/Dockerfile.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docker.errors import ImageNotFound

from . import docker_utils
from .config import SANDBOX_LABEL_KEY, SANDBOX_LABEL_VALUE
from .docker_utils import DOCKER_ERRORS, LOG_CONFIG

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DocumentConfig:
    image: str = "sensai-docs:latest"
    timeout_s: float = 60.0
    max_output_bytes: int = 2 * 1024 * 1024
    mem_limit: str = "512m"
    nano_cpus: int = 1_000_000_000  # 1 CPU
    pids_limit: int = 64
    tmpfs_size: str = "64m"


@dataclass(frozen=True)
class ConversionResult:
    ok: bool
    text: str = ""
    # image_missing, sandbox_error, timeout, oom, failed, empty
    error: str | None = None
    message: str = ""
    truncated: bool = False
    duration_s: float = 0.0


def _container_user() -> str:
    # The host user can read its own files, including ones only it may read
    # (mode 600); "nobody" could not. The container still has no capability,
    # no network and nothing else of the host mounted.
    if hasattr(os, "getuid"):
        return f"{os.getuid()}:{os.getgid()}"
    return "65534:65534"


class DocumentSandbox:
    """`convert` never raises: every failure comes back as a `ConversionResult`."""

    def __init__(self, config: DocumentConfig | None = None, client: Any | None = None) -> None:
        self.config = config or DocumentConfig()
        self._client = client  # tests inject a fake here

    def __call__(self, path: Path, extension: str | None = None) -> ConversionResult:
        return self.convert(path, extension)

    def convert(self, path: Path, extension: str | None = None) -> ConversionResult:
        cfg = self.config
        target = f"/input/document{extension or Path(path).suffix.lower() or '.bin'}"
        container = None
        started = time.monotonic()
        try:
            if self._client is None:
                self._client = docker_utils.connect()
            # Built locally: there is no registry to pull it from.
            docker_utils.ensure_image(self._client, cfg.image, pull=False)
            container = self._client.containers.create(**self._kwargs(Path(path), target))
            started = time.monotonic()
            container.start()
            timed_out, exit_code = docker_utils.wait_for_exit(container, cfg.timeout_s)
            stdout = container.logs(stdout=True, stderr=False)
            stderr = container.logs(stdout=False, stderr=True)
            oom = docker_utils.oom_killed(container)
        except ImageNotFound:
            return ConversionResult(False, error="image_missing",
                                    message=f"image {cfg.image} is not built")
        except DOCKER_ERRORS as exc:
            log.warning("document sandbox failure: %s", exc)
            return ConversionResult(False, error="sandbox_error",
                                    message=f"Docker is unavailable or failed: {exc}")
        finally:
            docker_utils.remove_container(container)

        duration = round(time.monotonic() - started, 3)
        if timed_out:
            return ConversionResult(False, error="timeout", duration_s=duration,
                                    message=f"conversion took more than {cfg.timeout_s:.0f} s")
        if oom:
            return ConversionResult(False, error="oom", duration_s=duration,
                                    message=f"conversion exceeded {cfg.mem_limit} of memory")
        if exit_code != 0:
            last = stderr.decode("utf-8", errors="replace").strip().splitlines()[-1:]
            return ConversionResult(False, error="failed", duration_s=duration,
                                    message=last[0] if last else f"exit code {exit_code}")
        truncated = len(stdout) > cfg.max_output_bytes
        text = stdout[:cfg.max_output_bytes].decode("utf-8", errors="ignore")
        if "\x00" in text:  # raw bytes, not text (also checked inside the image)
            return ConversionResult(False, error="failed", duration_s=duration,
                                    message="the converter returned the raw file")
        if not text.strip():
            return ConversionResult(False, error="empty", duration_s=duration,
                                    message="no text found")
        return ConversionResult(True, text=text, truncated=truncated, duration_s=duration)

    def _kwargs(self, path: Path, target: str) -> dict[str, Any]:
        cfg = self.config
        return {
            "image": cfg.image,
            "command": ["python", "-I", "/opt/convert.py", target],
            "labels": {SANDBOX_LABEL_KEY: SANDBOX_LABEL_VALUE},
            "environment": {"HOME": "/tmp", "PYTHONDONTWRITEBYTECODE": "1"},
            "volumes": {str(path): {"bind": target, "mode": "ro"}},
            "working_dir": "/tmp",
            "user": _container_user(),
            # Set twice on purpose: either one alone would already cut the network.
            "network_disabled": True,
            "network_mode": "none",
            "read_only": True,
            "tmpfs": {"/tmp": f"rw,noexec,nosuid,size={cfg.tmpfs_size}"},
            "mem_limit": cfg.mem_limit,
            "memswap_limit": cfg.mem_limit,
            "nano_cpus": cfg.nano_cpus,
            "pids_limit": cfg.pids_limit,
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges"],
            "log_config": LOG_CONFIG,
            "auto_remove": False,  # removed explicitly so logs can be read first
        }
