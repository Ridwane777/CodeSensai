"""Docker client doubles: replay the sandboxes without a daemon (tests and EV4 corpus)."""
from __future__ import annotations

from typing import Any

import requests
from docker.errors import DockerException, ImageNotFound


class FakeContainer:
    def __init__(
        self,
        stdout: bytes = b"",
        stderr: bytes = b"",
        exit_code: int = 0,
        oom: bool = False,
        hang: bool = False,
    ) -> None:
        self._stdout, self._stderr = stdout, stderr
        self._exit_code, self._oom, self._hang = exit_code, oom, hang
        self.attrs: dict[str, Any] = {}
        self.started = self.killed = self.removed = False
        self.wait_timeout: float | None = None

    def start(self) -> None:
        self.started = True

    def wait(self, timeout: float) -> dict:
        self.wait_timeout = timeout
        if self._hang:
            raise requests.exceptions.ReadTimeout("still running")
        return {"StatusCode": self._exit_code}

    def kill(self) -> None:
        self.killed = True

    def reload(self) -> None:
        self.attrs = {"State": {"OOMKilled": self._oom}}

    def logs(self, stdout: bool = True, stderr: bool = True) -> bytes:
        return self._stdout if stdout and not stderr else self._stderr

    def remove(self, force: bool = False) -> None:
        self.removed = True


class _Containers:
    def __init__(self, owner: FakeClient) -> None:
        self._owner = owner

    def create(self, **kwargs: Any) -> FakeContainer:
        if self._owner.create_error:
            raise self._owner.create_error
        self._owner.created_with = kwargs
        self._owner.all_created.append(kwargs)
        if self._owner.sequence:  # one container per call, in order (engine fallback)
            return self._owner.sequence.pop(0)
        return self._owner.container


class _Images:
    def __init__(self, owner: FakeClient) -> None:
        self._owner = owner

    def get(self, name: str) -> object:
        if not self._owner.image_present:
            raise ImageNotFound("missing")
        return object()

    def pull(self, name: str) -> None:
        self._owner.pulled.append(name)


class FakeClient:
    def __init__(self, container: FakeContainer | None = None, image_present: bool = True) -> None:
        self.container = container or FakeContainer()
        self.image_present = image_present
        self.create_error: Exception | None = None
        self.created_with: dict[str, Any] = {}
        self.all_created: list[dict[str, Any]] = []
        self.sequence: list[FakeContainer] = []
        self.pulled: list[str] = []
        self.containers = _Containers(self)
        self.images = _Images(self)


def broken_client() -> FakeClient:
    client = FakeClient()
    client.create_error = DockerException("daemon went away")
    return client
