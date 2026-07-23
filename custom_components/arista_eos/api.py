"""Vendored asynchronous Arista EOS eAPI (JSON-RPC over HTTP) client.

This client is intentionally dependency-free (beyond aiohttp, which Home Assistant
ships) and accepts an injected :class:`aiohttp.ClientSession`, satisfying the
Platinum ``async-dependency`` and ``inject-websession`` quality-scale rules.
"""

from __future__ import annotations

import asyncio
import contextlib
import ssl
from typing import Any, Final

import aiohttp
from yarl import URL

DEFAULT_TIMEOUT: Final = 15
_COMMAND_API_PATH: Final = "/command-api"

# EOS eAPI JSON-RPC error codes. 1002 is returned for command errors; the message
# text is what distinguishes an unauthorized/unsupported command.
_JSONRPC_COMMAND_ERROR: Final = 1002


def create_ssl_context(verify_ssl: bool) -> ssl.SSLContext:
    """Build an SSL context tolerant of legacy switch TLS.

    Older EOS releases only offer TLS 1.0-1.2 with ciphers that modern OpenSSL
    rejects at its default security level, causing a handshake failure. Lowering
    the security level and TLS floor lets Home Assistant negotiate with them.

    Loads CA data from disk, so call this off the event loop (executor).
    """
    context = ssl.create_default_context()
    if not verify_ssl:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    context.minimum_version = ssl.TLSVersion.TLSv1
    with contextlib.suppress(ssl.SSLError):  # cipher string depends on OpenSSL build
        context.set_ciphers("DEFAULT@SECLEVEL=1")
    return context


class EosError(Exception):
    """Base error for the Arista EOS client."""


class EosConnectionError(EosError):
    """Raised when the switch cannot be reached."""


class EosAuthError(EosError):
    """Raised when authentication fails (HTTP 401)."""


class EosCommandError(EosError):
    """Raised when the switch rejects one of the requested commands."""

    def __init__(self, message: str, *, code: int | None = None) -> None:
        """Store the eAPI error message and optional JSON-RPC code."""
        super().__init__(message)
        self.code = code


class EosClient:
    """Minimal async client for the EOS eAPI ``runCmds`` method."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        username: str,
        password: str,
        *,
        port: int = 443,
        use_https: bool = True,
        timeout: int = DEFAULT_TIMEOUT,
        ssl_context: ssl.SSLContext | bool = True,
    ) -> None:
        """Initialise the client with an injected session and connection details.

        ``ssl_context`` is passed per-request to aiohttp: an ``ssl.SSLContext``
        (e.g. from :func:`create_ssl_context`), ``True`` to verify with the default
        context, or ``False`` to skip verification.
        """
        self._session = session
        self._host = host
        self._username = username
        self._password = password
        self._port = port
        self._scheme = "https" if use_https else "http"
        self._timeout = timeout
        self._ssl_context: ssl.SSLContext | bool = ssl_context

    @property
    def url(self) -> URL:
        """Return the eAPI endpoint URL."""
        return URL.build(
            scheme=self._scheme,
            host=self._host,
            port=self._port,
            path=_COMMAND_API_PATH,
        )

    async def run_cmds(
        self, cmds: list[str], *, fmt: str = "json", version: int = 1
    ) -> list[dict[str, Any]]:
        """Execute ``cmds`` on the switch and return the per-command result list.

        The returned list preserves the order of ``cmds``.
        """
        payload = {
            "jsonrpc": "2.0",
            "method": "runCmds",
            "params": {"version": version, "cmds": cmds, "format": fmt},
            "id": "home-assistant",
        }
        auth = aiohttp.BasicAuth(self._username, self._password)

        try:
            async with asyncio.timeout(self._timeout):
                response = await self._session.post(
                    self.url, json=payload, auth=auth, ssl=self._ssl_context
                )
                if response.status in (401, 403):
                    raise EosAuthError("Authentication with the switch failed")
                response.raise_for_status()
                body: dict[str, Any] = await response.json()
        except EosAuthError:
            raise
        except TimeoutError as err:
            raise EosConnectionError(f"Timed out connecting to {self._host}") from err
        except aiohttp.ClientResponseError as err:
            if err.status in (401, 403):
                raise EosAuthError("Authentication with the switch failed") from err
            raise EosConnectionError(str(err)) from err
        except aiohttp.ClientError as err:
            raise EosConnectionError(str(err)) from err

        if (error := body.get("error")) is not None:
            message = str(error.get("message", "eAPI command error"))
            raise EosCommandError(message, code=error.get("code"))

        result = body.get("result")
        if not isinstance(result, list):
            raise EosCommandError("Malformed eAPI response: missing result list")
        return result
