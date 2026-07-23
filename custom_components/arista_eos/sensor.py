"""Sensor platform for the Arista EOS integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfDataRate,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import AristaConfigEntry, AristaCoordinator
from .data import EosData
from .entity import AristaEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class AristaSensorEntityDescription(SensorEntityDescription):
    """Describes an Arista scalar sensor."""

    value_fn: Callable[[EosData], StateType | datetime]
    available_fn: Callable[[EosData], bool] = lambda _data: True


SENSORS: tuple[AristaSensorEntityDescription, ...] = (
    AristaSensorEntityDescription(
        key="temperature",
        translation_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.max_temperature,
        available_fn=lambda data: data.max_temperature is not None,
    ),
    AristaSensorEntityDescription(
        key="power_draw",
        translation_key="power_draw",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.total_output_power,
        available_fn=lambda data: data.total_output_power is not None,
    ),
    AristaSensorEntityDescription(
        key="cpu",
        translation_key="cpu",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.cpu_used_pct,
        available_fn=lambda data: data.cpu_used_pct is not None,
    ),
    AristaSensorEntityDescription(
        key="memory",
        translation_key="memory",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.memory_used_pct,
        available_fn=lambda data: data.memory_used_pct is not None,
    ),
    AristaSensorEntityDescription(
        key="last_boot",
        translation_key="last_boot",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.boot_time,
        available_fn=lambda data: data.boot_time is not None,
    ),
    AristaSensorEntityDescription(
        key="eos_version",
        translation_key="eos_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.version,
    ),
    AristaSensorEntityDescription(
        key="reload_cause",
        translation_key="reload_cause",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.reload_cause,
        available_fn=lambda data: data.reload_cause is not None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AristaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Arista sensors, including dynamically discovered per-unit sensors."""
    coordinator = entry.runtime_data

    entities: list[SensorEntity] = [
        AristaScalarSensor(coordinator, description) for description in SENSORS
    ]
    async_add_entities(entities)

    known: set[str] = set()

    @callback
    def _add_dynamic() -> None:
        data = coordinator.data
        new: list[SensorEntity] = []

        for psu in data.power_supplies:
            key = f"psu_{psu.name}_power"
            if key not in known:
                known.add(key)
                new.append(AristaPsuPowerSensor(coordinator, psu.name))

        for sensor in data.temp_sensors:
            key = f"tempsensor_{sensor.name}"
            if key not in known:
                known.add(key)
                new.append(AristaTempSensor(coordinator, sensor.name))

        for fan in data.fans:
            key = f"fan_{fan.name}_speed"
            if key not in known:
                known.add(key)
                new.append(AristaFanSpeedSensor(coordinator, fan.name))

        for interface in data.interfaces:
            for direction in ("in", "out"):
                key = f"iface_{interface.name}_{direction}"
                if key not in known:
                    known.add(key)
                    new.append(AristaInterfaceRateSensor(coordinator, interface.name, direction))

        for xcvr in data.transceivers:
            key = f"xcvr_{xcvr.name}_temp"
            if key not in known:
                known.add(key)
                new.append(AristaTransceiverTempSensor(coordinator, xcvr.name))

        if new:
            async_add_entities(new)

    _add_dynamic()
    entry.async_on_unload(coordinator.async_add_listener(_add_dynamic))


class AristaScalarSensor(AristaEntity, SensorEntity):
    """A scalar switch-wide sensor described by an entity description."""

    entity_description: AristaSensorEntityDescription

    def __init__(
        self, coordinator: AristaCoordinator, description: AristaSensorEntityDescription
    ) -> None:
        """Initialise the scalar sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        """Return availability, accounting for unsupported metrics."""
        return super().available and self.entity_description.available_fn(self.coordinator.data)

    @property
    def native_value(self) -> StateType | datetime:
        """Return the current value."""
        return self.entity_description.value_fn(self.coordinator.data)


class AristaPsuPowerSensor(AristaEntity, SensorEntity):
    """Output power for a single power supply."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "psu_power"

    def __init__(self, coordinator: AristaCoordinator, name: str) -> None:
        """Initialise the PSU power sensor."""
        super().__init__(coordinator, f"psu_{name}_power")
        self._name = name
        self._attr_translation_placeholders = {"unit": name}

    @property
    def available(self) -> bool:
        """Return whether the PSU is still reported and has a reading."""
        return super().available and self.native_value is not None

    @property
    def native_value(self) -> float | None:
        """Return the PSU output power in watts."""
        for psu in self.coordinator.data.power_supplies:
            if psu.name == self._name:
                return psu.output_power
        return None


class AristaTempSensor(AristaEntity, SensorEntity):
    """Temperature for a single sensor on the switch."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "temp_sensor"

    def __init__(self, coordinator: AristaCoordinator, name: str) -> None:
        """Initialise the temperature sensor."""
        super().__init__(coordinator, f"tempsensor_{name}")
        self._name = name
        self._attr_translation_placeholders = {"sensor": name}

    @property
    def available(self) -> bool:
        """Return whether the sensor is still reported and has a reading."""
        return super().available and self.native_value is not None

    @property
    def native_value(self) -> float | None:
        """Return the sensor temperature in Celsius."""
        for sensor in self.coordinator.data.temp_sensors:
            if sensor.name == self._name:
                return sensor.current
        return None


class AristaFanSpeedSensor(AristaEntity, SensorEntity):
    """Speed for a single fan on the switch."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "fan_speed"

    def __init__(self, coordinator: AristaCoordinator, name: str) -> None:
        """Initialise the fan speed sensor."""
        super().__init__(coordinator, f"fan_{name}_speed")
        self._name = name
        self._attr_translation_placeholders = {"fan": name}

    @property
    def available(self) -> bool:
        """Return whether the fan is still reported and has a reading."""
        return super().available and self.native_value is not None

    @property
    def native_value(self) -> int | None:
        """Return the fan speed as a percentage of maximum."""
        for fan in self.coordinator.data.fans:
            if fan.name == self._name:
                return fan.speed
        return None


class AristaInterfaceRateSensor(AristaEntity, SensorEntity):
    """Ingress or egress throughput for a single interface."""

    _attr_device_class = SensorDeviceClass.DATA_RATE
    _attr_native_unit_of_measurement = UnitOfDataRate.MEGABITS_PER_SECOND
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: AristaCoordinator, name: str, direction: str) -> None:
        """Initialise the interface rate sensor."""
        super().__init__(coordinator, f"iface_{name}_{direction}")
        self._name = name
        self._direction = direction
        self._attr_translation_key = f"interface_{direction}"
        self._attr_translation_placeholders = {"interface": name}

    @property
    def available(self) -> bool:
        """Return whether the interface is still reported and has a reading."""
        return super().available and self.native_value is not None

    @property
    def native_value(self) -> float | None:
        """Return the interface rate in Mbit/s."""
        for interface in self.coordinator.data.interfaces:
            if interface.name != self._name:
                continue
            bps = interface.in_bps if self._direction == "in" else interface.out_bps
            return round(bps / 1_000_000, 3) if bps is not None else None
        return None


class AristaTransceiverTempSensor(AristaEntity, SensorEntity):
    """Temperature for a single transceiver (DOM)."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "transceiver_temp"

    def __init__(self, coordinator: AristaCoordinator, name: str) -> None:
        """Initialise the transceiver temperature sensor."""
        super().__init__(coordinator, f"xcvr_{name}_temp")
        self._name = name
        self._attr_translation_placeholders = {"interface": name}

    @property
    def available(self) -> bool:
        """Return whether the transceiver is still reported and has a reading."""
        return super().available and self.native_value is not None

    @property
    def native_value(self) -> float | None:
        """Return the transceiver temperature in Celsius."""
        for xcvr in self.coordinator.data.transceivers:
            if xcvr.name == self._name:
                return xcvr.temperature
        return None
