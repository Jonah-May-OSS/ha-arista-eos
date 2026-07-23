"""The Arista EOS integration."""

from __future__ import annotations

from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import EosClient
from .const import DOMAIN
from .coordinator import AristaConfigEntry, AristaCoordinator

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: AristaConfigEntry) -> bool:
    """Set up Arista EOS from a config entry."""
    session = async_get_clientsession(hass, verify_ssl=entry.data[CONF_VERIFY_SSL])
    client = EosClient(
        session,
        entry.data[CONF_HOST],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        port=entry.data[CONF_PORT],
    )
    coordinator = AristaCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AristaConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: AristaConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    entry: AristaConfigEntry,
    device_entry: dr.DeviceEntry,
) -> bool:
    """Allow removal of a device only if it no longer matches the switch serial."""
    current = entry.runtime_data.data.serial
    return not any(
        identifier[0] == DOMAIN and identifier[1] == current
        for identifier in device_entry.identifiers
    )
