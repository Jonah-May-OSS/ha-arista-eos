"""Tests for the Arista EOS coordinator and parsers."""

from __future__ import annotations

from datetime import datetime

import pytest
from custom_components.arista_eos.api import EosConnectionError
from custom_components.arista_eos.const import (
    CONF_MONITOR_INTERFACES,
    CONF_MONITOR_TRANSCEIVERS,
    DOMAIN,
)
from custom_components.arista_eos.coordinator import (
    _as_float,
    _as_int,
    _parse_cpu,
    _parse_reload_cause,
)
from custom_components.arista_eos.data import EosData, Fan, PowerSupply, TempSensor
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import FakeSwitch, setup_integration


async def test_fixed_parse(
    hass: HomeAssistant, config_entry: MockConfigEntry, switch: FakeSwitch
) -> None:
    """A fixed-form switch parses into the expected aggregate."""
    await setup_integration(hass, config_entry)
    data = config_entry.runtime_data.data

    assert data.serial == "JPE12345678"
    assert data.hostname == "spine1"
    assert data.model.startswith("DCS-7050")
    assert data.version == "4.30.3M"
    assert data.hardware_revision == "12.03"
    assert isinstance(data.boot_time, datetime)
    assert data.reload_cause == "Reload requested by the user."
    assert data.cpu_used_pct == 5.5
    assert data.memory_used_pct == pytest.approx(38.2, abs=0.2)
    assert data.max_temperature == 45.5
    assert len(data.temp_sensors) == 3
    assert data.total_output_power == 144.5
    assert len(data.power_supplies) == 2
    assert len(data.fans) == 3
    assert data.temp_alarm is False
    assert data.psu_problem is False
    assert data.fan_problem is False


async def test_modular_parse(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    switch: FakeSwitch,
    modular_responses: dict,
) -> None:
    """A modular switch flattens sensors across cards and PSUs."""
    switch.responses = modular_responses
    await setup_integration(hass, config_entry)
    data = config_entry.runtime_data.data

    assert data.hostname == "core1"
    assert len(data.temp_sensors) == 4
    assert data.max_temperature == 61.0
    assert data.total_output_power == 963.0
    assert len(data.power_supplies) == 4
    assert len(data.fans) == 4


async def test_environment_unsupported_creates_issue(
    hass: HomeAssistant, config_entry: MockConfigEntry, switch: FakeSwitch
) -> None:
    """A switch without environment support raises a repair issue."""
    for cmd in (
        "show environment temperature",
        "show environment power",
        "show environment cooling",
    ):
        switch.responses.pop(cmd)

    await setup_integration(hass, config_entry)
    data = config_entry.runtime_data.data

    assert data.max_temperature is None
    assert data.total_output_power is None
    assert data.power_supplies == []

    registry = ir.async_get(hass)
    issue = registry.async_get_issue(DOMAIN, f"no_environment_support_{config_entry.entry_id}")
    assert issue is not None
    assert issue.severity == ir.IssueSeverity.WARNING


async def test_environment_recovers_deletes_issue(
    hass: HomeAssistant, config_entry: MockConfigEntry, switch: FakeSwitch
) -> None:
    """When environment support returns, the repair issue is cleared."""
    saved = {
        cmd: switch.responses.pop(cmd)
        for cmd in (
            "show environment temperature",
            "show environment power",
            "show environment cooling",
        )
    }
    await setup_integration(hass, config_entry)
    registry = ir.async_get(hass)
    issue_id = f"no_environment_support_{config_entry.entry_id}"
    assert registry.async_get_issue(DOMAIN, issue_id) is not None

    switch.responses.update(saved)
    await config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert registry.async_get_issue(DOMAIN, issue_id) is None


async def test_optional_monitoring(
    hass: HomeAssistant, config_entry: MockConfigEntry, switch: FakeSwitch
) -> None:
    """Interface and transceiver telemetry is parsed only when enabled."""
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry,
        options={CONF_MONITOR_INTERFACES: True, CONF_MONITOR_TRANSCEIVERS: True},
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    data = config_entry.runtime_data.data
    assert len(data.interfaces) == 2
    assert {i.name for i in data.interfaces} == {"Ethernet1", "Ethernet2"}
    eth1 = next(i for i in data.interfaces if i.name == "Ethernet1")
    assert eth1.connected is True
    eth2 = next(i for i in data.interfaces if i.name == "Ethernet2")
    assert eth2.connected is False
    # Only Ethernet1 has a transceiver present.
    assert len(data.transceivers) == 1
    assert data.transceivers[0].name == "Ethernet1"


async def test_connection_error_marks_update_failed(
    hass: HomeAssistant, config_entry: MockConfigEntry, switch: FakeSwitch
) -> None:
    """A connection error during update marks the coordinator failed."""
    await setup_integration(hass, config_entry)
    switch.connection_error = True
    await config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert config_entry.runtime_data.last_update_success is False


def test_coercion_helpers() -> None:
    """Numeric coercion helpers tolerate junk values."""
    assert _as_float(True) is None
    assert _as_float(None) is None
    assert _as_float("nope") is None
    assert _as_float("3.5") == 3.5
    assert _as_int("7") == 7
    assert _as_int(None) is None


def test_parse_cpu_edge_cases() -> None:
    """CPU parsing tolerates missing structure."""
    assert _parse_cpu({}) is None
    assert _parse_cpu({"cpuInfo": {}}) is None
    assert _parse_cpu({"cpuInfo": {"%Cpu(s)": {}}}) is None
    assert _parse_cpu({"cpuInfo": {"%Cpu(s)": {"idle": 90.0}}}) == 10.0


def test_parse_reload_cause_edge_cases() -> None:
    """Reload-cause parsing tolerates missing structure."""
    assert _parse_reload_cause({}) is None
    assert _parse_reload_cause({"resetCauses": []}) is None
    assert _parse_reload_cause({"resetCauses": [{}]}) is None


def test_data_problem_properties() -> None:
    """The derived problem/alarm properties reflect component states."""
    data = EosData(serial="s", hostname="h", model="m", version="v")
    data.temp_sensors = [TempSensor(name="t", current=40.0, alert=True)]
    data.power_supplies = [PowerSupply(name="1", state="failed")]
    data.fans = [Fan(name="1", status="failed")]
    assert data.temp_alarm is True
    assert data.psu_problem is True
    assert data.fan_problem is True

    healthy = EosData(serial="s", hostname="h", model="m", version="v")
    healthy.temp_status = "temperatureOk"
    healthy.fan_status = "coolingOk"
    assert healthy.temp_alarm is False
    assert healthy.fan_problem is False


async def test_environment_connection_error_fails_update(
    hass: HomeAssistant, config_entry: MockConfigEntry, switch: FakeSwitch
) -> None:
    """A connection error while polling environment fails the update."""
    await setup_integration(hass, config_entry)
    switch.raise_for = {"show environment temperature": EosConnectionError("boom")}
    await config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert config_entry.runtime_data.last_update_success is False


async def test_optional_commands_unsupported_are_skipped(
    hass: HomeAssistant, config_entry: MockConfigEntry, switch: FakeSwitch
) -> None:
    """Unsupported interface/transceiver commands are skipped, not fatal."""
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry,
        options={CONF_MONITOR_INTERFACES: True, CONF_MONITOR_TRANSCEIVERS: True},
    )
    for cmd in (
        "show interfaces status",
        "show interfaces counters rates",
        "show interfaces transceiver",
    ):
        switch.responses.pop(cmd, None)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    data = config_entry.runtime_data.data
    assert data.interfaces == []
    assert data.transceivers == []
    assert config_entry.runtime_data.last_update_success is True


async def test_optional_connection_errors_fail_update(
    hass: HomeAssistant, config_entry: MockConfigEntry, switch: FakeSwitch
) -> None:
    """Connection errors while polling optional data fail the update."""
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry,
        options={CONF_MONITOR_INTERFACES: True, CONF_MONITOR_TRANSCEIVERS: True},
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    switch.raise_for = {"show interfaces status": EosConnectionError("boom")}
    await config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert config_entry.runtime_data.last_update_success is False

    switch.raise_for = {"show interfaces transceiver": EosConnectionError("boom")}
    await config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert config_entry.runtime_data.last_update_success is False
