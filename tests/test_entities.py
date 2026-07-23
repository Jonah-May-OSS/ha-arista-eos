"""Direct tests of per-unit entities and their not-found/availability branches."""

from __future__ import annotations

from custom_components.arista_eos.binary_sensor import (
    AristaFanProblem,
    AristaInterfaceLink,
    AristaPsuProblem,
)
from custom_components.arista_eos.coordinator import (
    _parse_environment,
    _parse_interfaces,
    _parse_transceivers,
)
from custom_components.arista_eos.data import EosData, Interface
from custom_components.arista_eos.sensor import (
    AristaFanSpeedSensor,
    AristaInterfaceRateSensor,
    AristaPsuPowerSensor,
    AristaTempSensor,
    AristaTransceiverTempSensor,
)
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import FakeSwitch


async def test_per_unit_sensor_values_and_missing(
    hass: HomeAssistant, config_entry: MockConfigEntry, switch: FakeSwitch
) -> None:
    """Per-unit sensors resolve known units and go unavailable for missing ones."""
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry,
        options={"monitor_interfaces": True, "monitor_transceivers": True},
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = config_entry.runtime_data

    assert AristaPsuPowerSensor(coordinator, "1").native_value == 73.5
    assert AristaPsuPowerSensor(coordinator, "missing").native_value is None
    assert AristaPsuPowerSensor(coordinator, "missing").available is False

    assert AristaTempSensor(coordinator, "TempSensor1").native_value == 45.5
    assert AristaTempSensor(coordinator, "missing").native_value is None
    assert AristaTempSensor(coordinator, "missing").available is False

    assert AristaFanSpeedSensor(coordinator, "1/1").native_value == 5100
    assert AristaFanSpeedSensor(coordinator, "missing").native_value is None
    assert AristaFanSpeedSensor(coordinator, "missing").available is False

    assert AristaInterfaceRateSensor(coordinator, "Ethernet1", "in").native_value == 125.0
    assert AristaInterfaceRateSensor(coordinator, "missing", "in").native_value is None
    assert AristaInterfaceRateSensor(coordinator, "missing", "in").available is False

    assert AristaTransceiverTempSensor(coordinator, "Ethernet1").native_value == 38.2
    assert AristaTransceiverTempSensor(coordinator, "missing").native_value is None
    assert AristaTransceiverTempSensor(coordinator, "missing").available is False


async def test_per_unit_binary_sensors_missing(
    hass: HomeAssistant, config_entry: MockConfigEntry, switch: FakeSwitch
) -> None:
    """Per-unit binary sensors resolve state and go unavailable for missing units."""
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(config_entry, options={"monitor_interfaces": True})
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = config_entry.runtime_data

    assert AristaPsuProblem(coordinator, "1").is_on is False
    assert AristaPsuProblem(coordinator, "missing").available is False
    assert AristaFanProblem(coordinator, "1/1").is_on is False
    assert AristaFanProblem(coordinator, "missing").available is False
    assert AristaInterfaceLink(coordinator, "Ethernet1").is_on is True
    assert AristaInterfaceLink(coordinator, "Ethernet2").is_on is False
    assert AristaInterfaceLink(coordinator, "missing").available is False


def test_parse_environment_malformed() -> None:
    """Environment parsing tolerates malformed structures."""
    data = EosData(serial="s", hostname="h", model="m", version="v")
    _parse_environment(
        {
            "show environment temperature": {
                "tempSensors": "not-a-list",
                "cardSlots": [1, {"tempSensors": [{"currentTemperature": 50.0}]}],
            },
            "show environment power": {"powerSupplies": "not-a-dict"},
            "show environment cooling": {"fanTraySlots": [1, {"fans": "x"}, {"fans": [1, {}]}]},
        },
        data,
    )
    assert data.total_output_power is None
    # One valid sensor came from the cardSlots entry.
    assert data.max_temperature == 50.0


def test_parse_interfaces_and_transceivers_malformed() -> None:
    """Interface and transceiver parsing tolerate malformed structures."""
    data = EosData(serial="s", hostname="h", model="m", version="v")
    _parse_interfaces({"show interfaces status": {"interfaceStatuses": "nope"}}, data)
    assert data.interfaces == []

    _parse_interfaces(
        {
            "show interfaces status": {"interfaceStatuses": {"Ethernet1": "bad", "Ethernet2": {}}},
            "show interfaces counters rates": {"interfaces": "nope"},
        },
        data,
    )
    assert [i.name for i in data.interfaces] == ["Ethernet2"]

    _parse_transceivers({"show interfaces transceiver": {"interfaces": "nope"}}, data)
    _parse_transceivers(
        {"show interfaces transceiver": {"interfaces": {"Et1": "bad", "Et2": {}}}}, data
    )
    assert data.transceivers == []


def test_interface_connected_unknown() -> None:
    """An interface with unknown link status reports connected as None."""
    assert Interface(name="Ethernet9").connected is None
