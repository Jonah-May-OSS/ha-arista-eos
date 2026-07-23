"""Binary sensor platform for the Arista EOS integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import AristaConfigEntry, AristaCoordinator
from .data import EosData
from .entity import AristaEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class AristaBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes an Arista scalar binary sensor."""

    value_fn: Callable[[EosData], bool]
    available_fn: Callable[[EosData], bool] = lambda _data: True


BINARY_SENSORS: tuple[AristaBinarySensorEntityDescription, ...] = (
    AristaBinarySensorEntityDescription(
        key="temperature_alarm",
        translation_key="temperature_alarm",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.temp_alarm,
        available_fn=lambda data: data.temp_status is not None or bool(data.temp_sensors),
    ),
    AristaBinarySensorEntityDescription(
        key="psu_status",
        translation_key="psu_status",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.psu_problem,
        available_fn=lambda data: bool(data.power_supplies),
    ),
    AristaBinarySensorEntityDescription(
        key="fan_status",
        translation_key="fan_status",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.fan_problem,
        available_fn=lambda data: data.fan_status is not None or bool(data.fans),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AristaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Arista binary sensors, including dynamically discovered per-unit ones."""
    coordinator = entry.runtime_data

    entities: list[BinarySensorEntity] = [
        AristaScalarBinarySensor(coordinator, description) for description in BINARY_SENSORS
    ]
    async_add_entities(entities)

    known: set[str] = set()

    @callback
    def _add_dynamic() -> None:
        data = coordinator.data
        new: list[BinarySensorEntity] = []

        for psu in data.power_supplies:
            key = f"psu_{psu.name}_problem"
            if key not in known:
                known.add(key)
                new.append(AristaPsuProblem(coordinator, psu.name))

        for fan in data.fans:
            key = f"fan_{fan.name}_problem"
            if key not in known:
                known.add(key)
                new.append(AristaFanProblem(coordinator, fan.name))

        for interface in data.interfaces:
            key = f"iface_{interface.name}_link"
            if key not in known:
                known.add(key)
                new.append(AristaInterfaceLink(coordinator, interface.name))

        if new:
            async_add_entities(new)

    _add_dynamic()
    entry.async_on_unload(coordinator.async_add_listener(_add_dynamic))


class AristaScalarBinarySensor(AristaEntity, BinarySensorEntity):
    """A scalar switch-wide binary sensor described by an entity description."""

    entity_description: AristaBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: AristaCoordinator,
        description: AristaBinarySensorEntityDescription,
    ) -> None:
        """Initialise the scalar binary sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        """Return availability, accounting for unsupported metrics."""
        return super().available and self.entity_description.available_fn(self.coordinator.data)

    @property
    def is_on(self) -> bool:
        """Return True when the monitored condition indicates a problem."""
        return self.entity_description.value_fn(self.coordinator.data)


class AristaPsuProblem(AristaEntity, BinarySensorEntity):
    """Problem state for a single power supply."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_translation_key = "psu_problem"

    def __init__(self, coordinator: AristaCoordinator, name: str) -> None:
        """Initialise the per-PSU problem sensor."""
        super().__init__(coordinator, f"psu_{name}_problem")
        self._name = name
        self._attr_translation_placeholders = {"unit": name}

    @property
    def available(self) -> bool:
        """Return whether the PSU is still reported."""
        return super().available and self._psu_state is not None

    @property
    def _psu_state(self) -> str | None:
        for psu in self.coordinator.data.power_supplies:
            if psu.name == self._name:
                return psu.state
        return None

    @property
    def is_on(self) -> bool:
        """Return True when the PSU is not in an ok state."""
        state = self._psu_state
        return state is not None and state.lower() != "ok"


class AristaFanProblem(AristaEntity, BinarySensorEntity):
    """Problem state for a single fan."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_translation_key = "fan_problem"

    def __init__(self, coordinator: AristaCoordinator, name: str) -> None:
        """Initialise the per-fan problem sensor."""
        super().__init__(coordinator, f"fan_{name}_problem")
        self._name = name
        self._attr_translation_placeholders = {"fan": name}

    @property
    def available(self) -> bool:
        """Return whether the fan is still reported."""
        return super().available and self._fan_status is not None

    @property
    def _fan_status(self) -> str | None:
        for fan in self.coordinator.data.fans:
            if fan.name == self._name:
                return fan.status
        return None

    @property
    def is_on(self) -> bool:
        """Return True when the fan is not in an ok state."""
        status = self._fan_status
        return status is not None and status.lower() != "ok"


class AristaInterfaceLink(AristaEntity, BinarySensorEntity):
    """Link state for a single interface."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "interface_link"

    def __init__(self, coordinator: AristaCoordinator, name: str) -> None:
        """Initialise the interface link sensor."""
        super().__init__(coordinator, f"iface_{name}_link")
        self._name = name
        self._attr_translation_placeholders = {"interface": name}

    @property
    def available(self) -> bool:
        """Return whether the interface is still reported with a known link state."""
        return super().available and self._connected is not None

    @property
    def _connected(self) -> bool | None:
        for interface in self.coordinator.data.interfaces:
            if interface.name == self._name:
                return interface.connected
        return None

    @property
    def is_on(self) -> bool:
        """Return True when the link is connected."""
        return bool(self._connected)
