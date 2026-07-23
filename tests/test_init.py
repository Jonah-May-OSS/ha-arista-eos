"""Tests for setup, unload and device removal."""

from __future__ import annotations

from types import SimpleNamespace

from custom_components.arista_eos import async_remove_config_entry_device
from custom_components.arista_eos.const import DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import FakeSwitch, setup_integration


async def test_setup_and_unload(
    hass: HomeAssistant, config_entry: MockConfigEntry, switch: FakeSwitch
) -> None:
    """The entry sets up and unloads cleanly."""
    await setup_integration(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_retry_on_connection_error(
    hass: HomeAssistant, config_entry: MockConfigEntry, switch: FakeSwitch
) -> None:
    """A connection failure at setup raises ConfigEntryNotReady (retry)."""
    switch.connection_error = True
    config_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_auth_failure_triggers_reauth(
    hass: HomeAssistant, config_entry: MockConfigEntry, switch: FakeSwitch
) -> None:
    """An auth failure during update starts a reauth flow."""
    await setup_integration(hass, config_entry)
    switch.auth_error = True
    await config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    flows = hass.config_entries.flow.async_progress()
    assert any(flow["context"]["source"] == "reauth" for flow in flows)


async def test_creates_device(
    hass: HomeAssistant, config_entry: MockConfigEntry, switch: FakeSwitch
) -> None:
    """A single device is created for the switch with rich device info."""
    await setup_integration(hass, config_entry)
    registry = dr.async_get(hass)
    device = registry.async_get_device(identifiers={(DOMAIN, "JPE12345678")})
    assert device is not None
    assert device.manufacturer == "Arista"
    assert device.name == "spine1"
    assert device.sw_version == "4.30.3M"


async def test_remove_stale_device_only(
    hass: HomeAssistant, config_entry: MockConfigEntry, switch: FakeSwitch
) -> None:
    """The current device cannot be removed, a stale one can."""
    await setup_integration(hass, config_entry)

    current = SimpleNamespace(identifiers={(DOMAIN, "JPE12345678")})
    stale = SimpleNamespace(identifiers={(DOMAIN, "OLD-SERIAL")})

    assert (
        await async_remove_config_entry_device(hass, config_entry, current)  # type: ignore[arg-type]
        is False
    )
    assert (
        await async_remove_config_entry_device(hass, config_entry, stale)  # type: ignore[arg-type]
        is True
    )
