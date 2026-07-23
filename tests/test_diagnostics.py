"""Tests for diagnostics."""

from __future__ import annotations

from custom_components.arista_eos.diagnostics import (
    async_get_config_entry_diagnostics,
)
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import FakeSwitch, setup_integration


async def test_diagnostics_redacts_credentials(
    hass: HomeAssistant, config_entry: MockConfigEntry, switch: FakeSwitch
) -> None:
    """Diagnostics include telemetry but redact credentials."""
    await setup_integration(hass, config_entry)
    diagnostics = await async_get_config_entry_diagnostics(hass, config_entry)

    assert diagnostics["entry"]["data"]["password"] == "**REDACTED**"
    assert diagnostics["entry"]["data"]["username"] == "**REDACTED**"
    assert diagnostics["last_update_success"] is True
    assert diagnostics["data"]["serial"] == "JPE12345678"
    assert diagnostics["data"]["hostname"] == "spine1"
