"""Base entity for the Arista EOS integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import AristaCoordinator


class AristaEntity(CoordinatorEntity[AristaCoordinator]):
    """Base entity binding to the switch device and coordinator."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AristaCoordinator, key: str) -> None:
        """Initialise the entity with a stable unique id and device info."""
        super().__init__(coordinator)
        data = coordinator.data
        self._attr_unique_id = f"{data.serial}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, data.serial)},
            name=data.hostname,
            manufacturer=MANUFACTURER,
            model=data.model,
            sw_version=data.version,
            hw_version=data.hardware_revision,
            configuration_url=str(coordinator.client.url.origin()),
        )
