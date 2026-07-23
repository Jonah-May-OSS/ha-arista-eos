"""Tests for the vendored async eAPI client."""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import aiohttp
import pytest
from custom_components.arista_eos.api import (
    EosAuthError,
    EosClient,
    EosCommandError,
    EosConnectionError,
)

pytestmark = pytest.mark.no_client_patch


class FakeResponse:
    """A minimal stand-in for an aiohttp response."""

    def __init__(
        self,
        *,
        status: int = 200,
        payload: dict[str, Any] | None = None,
        raise_exc: Exception | None = None,
    ) -> None:
        self.status = status
        self._payload = payload or {}
        self._raise = raise_exc

    def raise_for_status(self) -> None:
        if self._raise is not None:
            raise self._raise

    async def json(self) -> dict[str, Any]:
        return self._payload


class FakeSession:
    """A minimal stand-in for aiohttp.ClientSession."""

    def __init__(
        self,
        *,
        response: FakeResponse | None = None,
        post_exc: Exception | None = None,
    ) -> None:
        self._response = response
        self._post_exc = post_exc
        self.calls: list[dict[str, Any]] = []

    async def post(self, url: Any, *, json: Any = None, auth: Any = None) -> FakeResponse:
        self.calls.append({"url": url, "json": json, "auth": auth})
        if self._post_exc is not None:
            raise self._post_exc
        assert self._response is not None
        return self._response


def _client(session: FakeSession) -> EosClient:
    return EosClient(session, "10.0.0.10", "user", "pass", port=8080)  # type: ignore[arg-type]


async def test_run_cmds_success() -> None:
    """A successful call returns the result list and sends a runCmds payload."""
    session = FakeSession(
        response=FakeResponse(
            payload={"jsonrpc": "2.0", "id": "home-assistant", "result": [{"version": "4"}]}
        )
    )
    result = await _client(session).run_cmds(["show version"])
    assert result == [{"version": "4"}]
    sent = session.calls[0]["json"]
    assert sent["method"] == "runCmds"
    assert sent["params"]["cmds"] == ["show version"]


async def test_run_cmds_auth_status() -> None:
    """An HTTP 401 raises EosAuthError."""
    session = FakeSession(response=FakeResponse(status=401))
    with pytest.raises(EosAuthError):
        await _client(session).run_cmds(["show version"])


async def test_run_cmds_command_error() -> None:
    """A JSON-RPC error object raises EosCommandError with its code."""
    session = FakeSession(
        response=FakeResponse(payload={"error": {"message": "invalid command", "code": 1002}})
    )
    with pytest.raises(EosCommandError) as excinfo:
        await _client(session).run_cmds(["show bogus"])
    assert excinfo.value.code == 1002


async def test_run_cmds_missing_result() -> None:
    """A response without a result list raises EosCommandError."""
    session = FakeSession(response=FakeResponse(payload={"jsonrpc": "2.0", "id": "x"}))
    with pytest.raises(EosCommandError):
        await _client(session).run_cmds(["show version"])


async def test_run_cmds_http_error() -> None:
    """A non-auth HTTP error raises EosConnectionError."""
    exc = aiohttp.ClientResponseError(Mock(), (), status=500)
    session = FakeSession(response=FakeResponse(status=200, raise_exc=exc))
    with pytest.raises(EosConnectionError):
        await _client(session).run_cmds(["show version"])


async def test_run_cmds_http_forbidden() -> None:
    """A 403 surfaced via raise_for_status maps to EosAuthError."""
    exc = aiohttp.ClientResponseError(Mock(), (), status=403)
    session = FakeSession(response=FakeResponse(status=200, raise_exc=exc))
    with pytest.raises(EosAuthError):
        await _client(session).run_cmds(["show version"])


async def test_run_cmds_client_error() -> None:
    """A transport error raises EosConnectionError."""
    session = FakeSession(post_exc=aiohttp.ClientError("boom"))
    with pytest.raises(EosConnectionError):
        await _client(session).run_cmds(["show version"])


async def test_run_cmds_timeout() -> None:
    """A timeout raises EosConnectionError."""
    session = FakeSession(post_exc=TimeoutError())
    with pytest.raises(EosConnectionError):
        await _client(session).run_cmds(["show version"])


def test_url_property() -> None:
    """The endpoint URL reflects scheme, host and port."""
    session = FakeSession(response=FakeResponse())
    https = EosClient(session, "host", "u", "p", port=8080)  # type: ignore[arg-type]
    assert str(https.url) == "https://host:8080/command-api"
    http = EosClient(session, "host", "u", "p", port=8080, use_https=False)  # type: ignore[arg-type]
    assert str(http.url) == "http://host:8080/command-api"
