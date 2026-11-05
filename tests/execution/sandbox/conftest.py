"""Fixtures for tests that run real containers (marked `docker`).

They skip when no Docker daemon answers, so the suite still runs everywhere.
"""
import pytest

from sensai.execution.sandbox.config import (
    SANDBOX_LABEL_KEY,
    SANDBOX_LABEL_VALUE,
    SandboxConfig,
)
from sensai.execution.sandbox.python_sandbox import PythonSandbox


def _docker_client():
    try:
        import docker

        client = docker.from_env()
        client.ping()
        return client
    except Exception:
        return None


@pytest.fixture(scope="session")
def docker_client():
    client = _docker_client()
    if client is None:
        pytest.skip("Docker daemon not reachable")
    return client


@pytest.fixture(scope="session")
def sandbox_image(docker_client):
    """Pull the image once, so the download never counts against a timeout."""
    import docker.errors

    image = SandboxConfig().image
    try:
        docker_client.images.get(image)
    except docker.errors.ImageNotFound:
        docker_client.images.pull(image)
    return image


@pytest.fixture(scope="session")
def sandbox(docker_client, sandbox_image):
    return PythonSandbox(client=docker_client)


@pytest.fixture(autouse=True)
def _no_leftover_containers(request):
    yield
    if not request.node.get_closest_marker("docker"):
        return
    client = _docker_client()
    if client is None:
        return
    label = f"{SANDBOX_LABEL_KEY}={SANDBOX_LABEL_VALUE}"
    leftovers = client.containers.list(all=True, filters={"label": label})
    assert not leftovers, f"leftover sandbox containers: {[c.short_id for c in leftovers]}"
