"""Tests for the binary sensor platform."""

from __future__ import annotations

from custom_components.arista_eos.const import CONF_MONITOR_INTERFACES
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import FakeSwitch, setup_integration


async def test_status_binary_sensors_healthy(
    hass: HomeAssistant, config_entry: MockConfigEntry, switch: FakeSwitch
) -> None:
    """Status binary sensors are off on a healthy switch."""
    await setup_integration(hass, config_entry)
    assert hass.states.get("binary_sensor.spine1_temperature_alarm").state == "off"
    assert hass.states.get("binary_sensor.spine1_power_supply_status").state == "off"
    assert hass.states.get("binary_sensor.spine1_fan_status").state == "off"


async def test_psu_status_problem(
    hass: HomeAssistant, config_entry: MockConfigEntry, switch: FakeSwitch
) -> None:
    """A failed PSU turns the power supply status problem on."""
    switch.responses["show system environment power"]["powerSupplies"]["1"]["state"] = "powerLoss"
    await setup_integration(hass, config_entry)
    assert hass.states.get("binary_sensor.spine1_power_supply_status").state == "on"


async def test_interface_link_binary_sensors(
    hass: HomeAssistant, config_entry: MockConfigEntry, switch: FakeSwitch
) -> None:
    """Per-interface link connectivity reflects link status when enabled."""
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(config_entry, options={CONF_MONITOR_INTERFACES: True})
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.spine1_ethernet1_link").state == "on"
    assert hass.states.get("binary_sensor.spine1_ethernet2_link").state == "off"
