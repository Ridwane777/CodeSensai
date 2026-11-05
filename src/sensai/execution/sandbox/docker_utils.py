"""Container plumbing shared by the Python and the browser sandboxes."""
from __future__ import annotations

import logging
from typing import Any

import docker
import requests
from docker.errors import DockerException, ImageNotFound

log = logging.getLogger(__name__)

# Cap the Docker log kept on disk: a program that prints forever must not fill
# the host's disk.
LOG_CONFIG = {"type": "json-file", "config": {"max-size": "4m", "max-file": "1"}}

# What can go wrong when talking to Docker, as opposed to a bug in our code.
DOCKER_ERRORS = (DockerException, requests.exceptions.RequestException, OSError)


def connect() -> Any:
    client = docker.from_env()
    client.ping()  # a dead daemon must fail now, not in the middle of a run
    return client


def ensure_image(client: Any, image: str, pull: bool = True) -> None:
    """Make sure `image` exists locally.

    A locally built image (the browser one) has no registry to pull from, so
    callers pass `pull=False` and get a clear error instead of a failed pull.
    """
    try:
        client.images.get(image)
    except ImageNotFound:
        if not pull:
            raise
        client.images.pull(image)


def wait_for_exit(container: Any, timeout: float) -> tuple[bool, int | None]:
    """Wait for the exit. Returns (timed_out, exit_code); kills the container on timeout."""
    try:
        status = container.wait(timeout=timeout)
        return False, status.get("StatusCode")
    except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError):
        try:
            container.kill()
        except DockerException:
            pass  # it exited between the timeout and the kill
        return True, None


def oom_killed(container: Any) -> bool:
    container.reload()
    return bool(container.attrs.get("State", {}).get("OOMKilled", False))


def remove_container(container: Any) -> None:
    if container is None:
        return
    try:
        container.remove(force=True)
    except Exception as exc:  # cleanup must never hide the real result
        log.warning("failed to remove sandbox container: %s", exc)
