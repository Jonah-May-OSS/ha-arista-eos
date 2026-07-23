"""Config, options, reauth, reconfigure and discovery flows for Arista EOS."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import format_mac

from .api import (
    EosAuthError,
    EosClient,
    EosCommandError,
    EosConnectionError,
    create_ssl_context,
)
from .const import (
    CMD_HOSTNAME,
    CMD_VERSION,
    CONF_MAC,
    CONF_MONITOR_INTERFACES,
    CONF_MONITOR_TRANSCEIVERS,
    CONF_SCAN_INTERVAL,
    DEFAULT_MONITOR_INTERFACES,
    DEFAULT_MONITOR_TRANSCEIVERS,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    LOGGER,
    MIN_SCAN_INTERVAL,
)
from .coordinator import AristaConfigEntry

if TYPE_CHECKING:
    try:
        from homeassistant.helpers.service_info.dhcp import (  # type: ignore[import-not-found, unused-ignore]
            DhcpServiceInfo,
        )
    except ImportError:  # Home Assistant < 2025.2
        from homeassistant.components.dhcp import (  # type: ignore[import-not-found, no-redef, attr-defined, unused-ignore]
            DhcpServiceInfo,
        )


async def _async_validate(hass: HomeAssistant, data: Mapping[str, Any]) -> dict[str, str]:
    """Validate connectivity/credentials and return the switch identity.

    Raises EosAuthError / EosConnectionError / EosCommandError on failure.
    """
    session = async_get_clientsession(hass, verify_ssl=data[CONF_VERIFY_SSL])
    ssl_context = await hass.async_add_executor_job(create_ssl_context, data[CONF_VERIFY_SSL])
    client = EosClient(
        session,
        data[CONF_HOST],
        data[CONF_USERNAME],
        data[CONF_PASSWORD],
        port=data[CONF_PORT],
        ssl_context=ssl_context,
    )
    LOGGER.debug(
        "Validating Arista eAPI at %s:%s (verify_ssl=%s, user=%s)",
        data[CONF_HOST],
        data[CONF_PORT],
        data[CONF_VERIFY_SSL],
        data[CONF_USERNAME],
    )
    result = await client.run_cmds([CMD_VERSION, CMD_HOSTNAME])
    version = result[0]
    hostname = result[1]
    serial = str(version.get("serialNumber") or "").strip()
    title = str(
        hostname.get("hostname")
        or hostname.get("fqdn")
        or version.get("modelName")
        or data[CONF_HOST]
    )
    return {"serial": serial or str(data[CONF_HOST]), "title": title}


def _base_schema(defaults: Mapping[str, Any], *, include_host: bool = True) -> vol.Schema:
    """Build the connection schema with optional host field and defaults."""
    fields: dict[Any, Any] = {}
    if include_host:
        fields[vol.Required(CONF_HOST, default=defaults.get(CONF_HOST))] = str
    fields[vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME))] = str
    fields[vol.Required(CONF_PASSWORD)] = str
    fields[vol.Optional(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT))] = vol.All(
        vol.Coerce(int), vol.Range(min=1, max=65535)
    )
    fields[
        vol.Optional(CONF_VERIFY_SSL, default=defaults.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL))
    ] = bool
    return vol.Schema(fields)


class AristaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Arista EOS config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise transient discovery state."""
        self._discovered: dict[str, Any] = {}
        self._title: str = ""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle a user-initiated (or discovery-continued) setup."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**self._discovered, **user_input}
            errors = await self._async_try_create(data)
            if not errors:
                return self._create_entry(data)

        defaults = {**self._discovered, **(user_input or {})}
        return self.async_show_form(
            step_id="user",
            data_schema=_base_schema(defaults),
            errors=errors,
        )

    async def async_step_dhcp(self, discovery_info: DhcpServiceInfo) -> ConfigFlowResult:
        """Handle discovery of an Arista device via DHCP."""
        mac = format_mac(discovery_info.macaddress)
        host = discovery_info.ip

        for entry in self._async_current_entries(include_ignore=False):
            if entry.data.get(CONF_MAC) == mac:
                # Known device: update its host if the DHCP lease changed.
                if entry.data.get(CONF_HOST) != host:
                    self.hass.config_entries.async_update_entry(
                        entry, data={**entry.data, CONF_HOST: host}
                    )
                    self.hass.config_entries.async_schedule_reload(entry.entry_id)
                return self.async_abort(reason="already_configured")
            if entry.data.get(CONF_HOST) == host:
                return self.async_abort(reason="already_configured")

        self._discovered = {CONF_HOST: host, CONF_MAC: mac}
        self.context["title_placeholders"] = {"name": host}
        return await self.async_step_user()

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Handle re-authentication upon an auth failure."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm new credentials for an existing entry."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, **user_input}
            errors = await self._async_validate_only(data)
            if not errors:
                return self.async_update_reload_and_abort(entry, data_updates=user_input)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME, default=entry.data.get(CONF_USERNAME)): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
            description_placeholders={CONF_HOST: entry.data[CONF_HOST]},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of connection details for an existing entry."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, **user_input}
            info, errors = await self._async_validate_with_identity(data)
            if not errors and info is not None:
                await self.async_set_unique_id(info["serial"])
                self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(entry, data_updates=user_input)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_base_schema(entry.data),
            errors=errors,
        )

    async def _async_try_create(self, data: Mapping[str, Any]) -> dict[str, str]:
        """Validate for the create path and claim the unique id."""
        info, errors = await self._async_validate_with_identity(data)
        if errors or info is None:
            return errors
        await self.async_set_unique_id(info["serial"])
        self._abort_if_unique_id_configured(updates={CONF_HOST: data[CONF_HOST]})
        self._title = info["title"]
        return {}

    async def _async_validate_with_identity(
        self, data: Mapping[str, Any]
    ) -> tuple[dict[str, str] | None, dict[str, str]]:
        """Validate and return (identity, errors)."""
        try:
            info = await _async_validate(self.hass, data)
        except EosAuthError as err:
            LOGGER.debug("Arista eAPI auth failed for %s: %s", data.get(CONF_HOST), err)
            return None, {"base": "invalid_auth"}
        except EosConnectionError as err:
            LOGGER.warning(
                "Arista eAPI connection to %s:%s failed: %s",
                data.get(CONF_HOST),
                data.get(CONF_PORT),
                err,
            )
            return None, {"base": "cannot_connect"}
        except EosCommandError as err:
            LOGGER.warning("Arista eAPI command error from %s: %s", data.get(CONF_HOST), err)
            return None, {"base": "cannot_connect"}
        return info, {}

    async def _async_validate_only(self, data: Mapping[str, Any]) -> dict[str, str]:
        """Validate credentials without claiming a unique id (reauth path)."""
        _info, errors = await self._async_validate_with_identity(data)
        return errors

    def _create_entry(self, data: Mapping[str, Any]) -> ConfigFlowResult:
        """Create the config entry from validated data."""
        return self.async_create_entry(title=self._title or str(data[CONF_HOST]), data=dict(data))

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: AristaConfigEntry,
    ) -> AristaOptionsFlow:
        """Return the options flow handler."""
        return AristaOptionsFlow()


class AristaOptionsFlow(OptionsFlow):
    """Handle Arista EOS options."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage polling interval and optional monitoring toggles."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=3600)),
                vol.Optional(
                    CONF_MONITOR_INTERFACES,
                    default=options.get(CONF_MONITOR_INTERFACES, DEFAULT_MONITOR_INTERFACES),
                ): bool,
                vol.Optional(
                    CONF_MONITOR_TRANSCEIVERS,
                    default=options.get(CONF_MONITOR_TRANSCEIVERS, DEFAULT_MONITOR_TRANSCEIVERS),
                ): bool,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
