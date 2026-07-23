"""Shared fixtures for the Arista EOS integration tests."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from custom_components.arista_eos.api import (
    EosAuthError,
    EosClient,
    EosCommandError,
    EosConnectionError,
)
from custom_components.arista_eos.const import CONF_MAC, DOMAIN
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    """Load a JSON fixture by file name."""
    return json.loads((FIXTURES / name).read_text())


class FakeSwitch:
    """Configurable fake eAPI backend used to patch EosClient.run_cmds."""

    def __init__(self, responses: dict[str, Any]) -> None:
        """Store the initial command->response mapping."""
        self.responses: dict[str, Any] = dict(responses)
        self.auth_error = False
        self.connection_error = False
        # Map a command to an exception to raise when it is requested.
        self.raise_for: dict[str, Exception] = {}

    async def run_cmds(
        self, cmds: list[str], *, fmt: str = "json", version: int = 1
    ) -> list[dict[str, Any]]:
        """Return canned responses, raising configured errors."""
        if self.auth_error:
            raise EosAuthError("authentication failed")
        if self.connection_error:
            raise EosConnectionError("connection failed")
        for cmd in cmds:
            if cmd in self.raise_for:
                raise self.raise_for[cmd]
        out: list[dict[str, Any]] = []
        for cmd in cmds:
            if cmd not in self.responses:
                raise EosCommandError(f"unsupported command: {cmd}", code=1002)
            out.append(self.responses[cmd])
        return out


@pytest.fixture(autouse=True)
def mock_clientsession() -> Iterator[None]:
    """Avoid creating real aiohttp sessions (run_cmds is patched anyway)."""
    session = MagicMock()
    with (
        patch(
            "custom_components.arista_eos.async_get_clientsession",
            return_value=session,
        ),
        patch(
            "custom_components.arista_eos.config_flow.async_get_clientsession",
            return_value=session,
        ),
    ):
        yield


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: Any,
) -> None:
    """Enable loading of the custom integration in every test."""
    return


@pytest.fixture
def fixed_responses() -> dict[str, Any]:
    """Return responses for a fixed-form-factor switch."""
    return load_fixture("fixed.json")


@pytest.fixture
def modular_responses() -> dict[str, Any]:
    """Return responses for a modular switch."""
    return load_fixture("modular.json")


@pytest.fixture
def switch(fixed_responses: dict[str, Any]) -> FakeSwitch:
    """Return a fake switch backend (defaults to the fixed fixture)."""
    return FakeSwitch(fixed_responses)


@pytest.fixture(autouse=True)
def patch_client(request: pytest.FixtureRequest, switch: FakeSwitch) -> Iterator[FakeSwitch]:
    """Patch EosClient.run_cmds to use the fake switch (unless opted out)."""
    if request.node.get_closest_marker("no_client_patch"):
        yield switch
        return

    async def _run(
        _self: EosClient, cmds: list[str], *, fmt: str = "json", version: int = 1
    ) -> list[dict[str, Any]]:
        return await switch.run_cmds(cmds, fmt=fmt, version=version)

    with patch.object(EosClient, "run_cmds", _run):
        yield switch


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Return a mock config entry for the switch."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="spine1",
        unique_id="JPE12345678",
        data={
            CONF_HOST: "10.0.0.10",
            CONF_USERNAME: "homeassistant",
            CONF_PASSWORD: "secret",
            CONF_PORT: 443,
            CONF_VERIFY_SSL: False,
            CONF_MAC: "00:1c:73:aa:bb:cc",
        },
    )


async def setup_integration(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    """Add the entry to hass and set it up."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
