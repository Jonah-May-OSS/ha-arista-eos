"""Tests for the sensor platform."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from custom_components.arista_eos.const import (
    CONF_MONITOR_INTERFACES,
    CONF_MONITOR_TRANSCEIVERS,
    DOMAIN,
)
from homeassistant.components.sensor import SensorExtraStoredData
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache_with_extra_data,
)

from .conftest import FakeSwitch, setup_integration


async def test_scalar_sensor_states(
    hass: HomeAssistant, config_entry: MockConfigEntry, switch: FakeSwitch
) -> None:
    """Switch-wide sensors report parsed values."""
    await setup_integration(hass, config_entry)
    assert hass.states.get("sensor.spine1_temperature").state == "45.5"
    assert hass.states.get("sensor.spine1_power_draw").state == "144.5"
    assert hass.states.get("sensor.spine1_cpu_utilization").state == "5.5"
    assert hass.states.get("sensor.spine1_eos_version").state == "4.30.3M"
    assert hass.states.get("sensor.spine1_reload_cause").state == ("Reload requested by the user.")


async def test_per_unit_value_sensors_enabled_by_default(
    hass: HomeAssistant, config_entry: MockConfigEntry, switch: FakeSwitch
) -> None:
    """Per-unit value sensors are enabled; redundant problem flags stay disabled."""
    await setup_integration(hass, config_entry)
    registry = er.async_get(hass)

    power_id = registry.async_get_entity_id("sensor", DOMAIN, "JPE12345678_psu_1_power")
    assert power_id is not None
    assert registry.async_get(power_id).disabled is False
    assert hass.states.get(power_id).state == "73.5"

    # The redundant per-unit problem flag remains disabled by default.
    problem_id = registry.async_get_entity_id("binary_sensor", DOMAIN, "JPE12345678_psu_1_problem")
    assert problem_id is not None
    assert registry.async_get(problem_id).disabled is True


async def test_temperature_unavailable_without_environment(
    hass: HomeAssistant, config_entry: MockConfigEntry, switch: FakeSwitch
) -> None:
    """Environment sensors report unavailable on platforms without sensors."""
    for cmd in (
        "show system environment temperature",
        "show system environment power",
        "show system environment cooling",
    ):
        switch.responses.pop(cmd)
    await setup_integration(hass, config_entry)
    assert hass.states.get("sensor.spine1_temperature").state == "unavailable"
    assert hass.states.get("sensor.spine1_power_draw").state == "unavailable"


async def test_energy_sensor_integrates_power(
    hass: HomeAssistant, config_entry: MockConfigEntry, switch: FakeSwitch
) -> None:
    """Energy is integrated from the power draw over the elapsed interval."""
    clock = {"now": datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)}
    with patch(
        "custom_components.arista_eos.sensor.dt_util.utcnow",
        side_effect=lambda: clock["now"],
    ):
        await setup_integration(hass, config_entry)
        # Baseline established at startup; nothing accumulated yet.
        assert hass.states.get("sensor.spine1_energy").state == "0.0"

        # Advance one hour and poll again: 144.5 W for 1 h == 0.1445 kWh.
        clock["now"] = datetime(2024, 1, 1, 1, 0, 0, tzinfo=UTC)
        await config_entry.runtime_data.async_refresh()
        await hass.async_block_till_done()

    energy = hass.states.get("sensor.spine1_energy")
    assert energy.attributes["device_class"] == "energy"
    assert energy.attributes["state_class"] == "total_increasing"
    assert energy.attributes["unit_of_measurement"] == "kWh"
    assert float(energy.state) == pytest.approx(0.1445)


async def test_energy_sensor_restores_total(
    hass: HomeAssistant, config_entry: MockConfigEntry, switch: FakeSwitch
) -> None:
    """The accumulated energy total survives a restart."""
    restored = SensorExtraStoredData(2.5, UnitOfEnergy.KILO_WATT_HOUR)
    mock_restore_cache_with_extra_data(
        hass,
        ((State("sensor.spine1_energy", "2.5"), restored.as_dict()),),
    )
    now = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
    with patch(
        "custom_components.arista_eos.sensor.dt_util.utcnow",
        return_value=now,
    ):
        await setup_integration(hass, config_entry)

    assert float(hass.states.get("sensor.spine1_energy").state) == pytest.approx(2.5)


async def test_interface_and_transceiver_sensors(
    hass: HomeAssistant, config_entry: MockConfigEntry, switch: FakeSwitch
) -> None:
    """Interface throughput and transceiver temp entities appear when enabled."""
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry,
        options={CONF_MONITOR_INTERFACES: True, CONF_MONITOR_TRANSCEIVERS: True},
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.spine1_ethernet1_inbound").state == "125.0"
    assert hass.states.get("sensor.spine1_ethernet1_outbound").state == "98.0"
    assert hass.states.get("sensor.spine1_ethernet1_transceiver_temperature").state == "38.2"
