"""Run untrusted Python code in a locked-down, throw-away Docker container."""
from __future__ import annotations

import logging
import time
from typing import Any

from . import docker_utils
from .config import SANDBOX_LABEL_KEY, SANDBOX_LABEL_VALUE, SandboxConfig
from .docker_utils import DOCKER_ERRORS, LOG_CONFIG
from .result import ExecutionResult, extract_traceback, parse_error

log = logging.getLogger(__name__)


class PythonSandbox:
    """Execute Python source in an isolated container and return a structured result.

    `run` never raises: every failure comes back as an `ExecutionResult`.
    """

    def __init__(self, config: SandboxConfig | None = None, client: Any | None = None) -> None:
        self.config = config or SandboxConfig()
        self._client = client  # tests inject a fake here

    def run(self, code: str, timeout_s: float | None = None) -> ExecutionResult:
        cfg = self.config
        if not isinstance(code, str):
            return ExecutionResult.failure("SandboxError", "code must be a string")
        if len(code.encode("utf-8")) > cfg.max_code_bytes:
            return ExecutionResult.failure(
                "SandboxError", f"code exceeds the {cfg.max_code_bytes} byte limit"
            )
        timeout = cfg.clamp_timeout(timeout_s)

        container = None
        started = time.monotonic()
        try:
            client = self._get_client()
            self._ensure_image(client)
            container = client.containers.create(**self._container_kwargs(code))
            started = time.monotonic()
            container.start()
            timed_out, exit_code = docker_utils.wait_for_exit(container, timeout)
            duration = time.monotonic() - started
            stdout_b = container.logs(stdout=True, stderr=False)
            stderr_b = container.logs(stdout=False, stderr=True)
            oom = docker_utils.oom_killed(container)
        except DOCKER_ERRORS as exc:
            log.warning("sandbox infrastructure failure: %s", exc)
            return ExecutionResult.failure(
                "SandboxError",
                f"Docker is unavailable or failed: {exc}",
                duration_s=time.monotonic() - started,
            )
        finally:
            docker_utils.remove_container(container)

        return self._build_result(stdout_b, stderr_b, exit_code, timed_out, oom, duration)

    # -- internals ------------------------------------------------------------

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = docker_utils.connect()
        return self._client

    def _ensure_image(self, client: Any) -> None:
        docker_utils.ensure_image(client, self.config.image)

    def _container_kwargs(self, code: str) -> dict[str, Any]:
        cfg = self.config
        return {
            "image": cfg.image,
            # -I: isolated mode, ignores PYTHON* variables and the current directory.
            # The code is an argument: no file is shared with the host.
            "command": ["python", "-I", "-c", code],
            "labels": {SANDBOX_LABEL_KEY: SANDBOX_LABEL_VALUE},
            "environment": {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"},
            "working_dir": cfg.working_dir,
            "user": cfg.user,
            # Set twice on purpose: either one alone would already cut the network.
            "network_disabled": True,
            "network_mode": "none",
            "read_only": True,
            "tmpfs": {"/tmp": f"rw,noexec,nosuid,size={cfg.tmpfs_size}"},
            "mem_limit": cfg.mem_limit,
            "memswap_limit": cfg.mem_limit,  # equal to mem_limit: no swap
            "nano_cpus": cfg.nano_cpus,
            "pids_limit": cfg.pids_limit,
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges"],
            "log_config": LOG_CONFIG,
            "auto_remove": False,  # removed explicitly so logs can be read first
        }

    def _build_result(
        self,
        stdout_b: bytes,
        stderr_b: bytes,
        exit_code: int | None,
        timed_out: bool,
        oom: bool,
        duration: float,
    ) -> ExecutionResult:
        cap = self.config.max_output_bytes
        truncated = len(stdout_b) > cap or len(stderr_b) > cap
        stdout = stdout_b[:cap].decode("utf-8", errors="replace")
        # Keep the end of stderr: the traceback is there.
        stderr = stderr_b[-cap:].decode("utf-8", errors="replace")

        traceback = extract_traceback(stderr)
        error_type, error_message = parse_error(traceback)
        if timed_out:
            error_type = "Timeout"
            error_message = "execution exceeded the time limit and was killed"
        elif oom:
            error_type = "OOMKilled"
            error_message = "process exceeded the memory limit and was killed"
        elif error_type is None and exit_code not in (0, None):
            error_message = f"process exited with code {exit_code}"

        return ExecutionResult(
            ok=exit_code == 0 and not timed_out and not oom,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            traceback=traceback,
            error_type=error_type,
            error_message=error_message,
            timed_out=timed_out,
            oom_killed=oom,
            duration_s=round(duration, 3),
            truncated=truncated,
        )
