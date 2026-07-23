"""Tests for the Arista EOS config, reauth, reconfigure and options flows."""

from __future__ import annotations

from types import SimpleNamespace

from custom_components.arista_eos.const import (
    CONF_MAC,
    CONF_MONITOR_INTERFACES,
    CONF_SCAN_INTERVAL,
    DOMAIN,
)
from homeassistant import config_entries
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import FakeSwitch


def _dhcp(ip: str, mac: str, hostname: str = "switch") -> SimpleNamespace:
    """Return a lightweight DHCP discovery-info stand-in."""
    return SimpleNamespace(ip=ip, hostname=hostname, macaddress=mac)


USER_INPUT = {
    CONF_HOST: "10.0.0.10",
    CONF_USERNAME: "homeassistant",
    CONF_PASSWORD: "secret",
    CONF_PORT: 443,
    CONF_VERIFY_SSL: False,
}


async def test_user_flow_success(hass: HomeAssistant, switch: FakeSwitch) -> None:
    """A valid user flow creates an entry keyed by serial number."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "spine1"
    assert result["result"].unique_id == "JPE12345678"


async def test_user_flow_invalid_auth(hass: HomeAssistant, switch: FakeSwitch) -> None:
    """Auth failures surface as a recoverable form error."""
    switch.auth_error = True
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}

    # Recover on the same flow once creds work.
    switch.auth_error = False
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_cannot_connect(hass: HomeAssistant, switch: FakeSwitch) -> None:
    """Connection failures surface as a recoverable form error."""
    switch.connection_error = True
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_duplicate(
    hass: HomeAssistant, config_entry: MockConfigEntry, switch: FakeSwitch
) -> None:
    """Adding an already-configured switch aborts."""
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_dhcp_discovery_creates_entry(hass: HomeAssistant, switch: FakeSwitch) -> None:
    """DHCP discovery proceeds to the user step and can create an entry."""
    info = _dhcp("10.0.0.10", "001c73aabbcc", "spine1")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_DHCP}, data=info
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: "homeassistant", CONF_PASSWORD: "secret"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].data[CONF_MAC] == "00:1c:73:aa:bb:cc"
    assert result["result"].data[CONF_HOST] == "10.0.0.10"


async def test_dhcp_discovery_updates_host(
    hass: HomeAssistant, config_entry: MockConfigEntry, switch: FakeSwitch
) -> None:
    """Re-discovery of a known MAC updates the stored host and aborts."""
    config_entry.add_to_hass(hass)
    info = _dhcp("10.0.0.99", "001c73aabbcc", "spine1")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_DHCP}, data=info
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert config_entry.data[CONF_HOST] == "10.0.0.99"
    await hass.async_block_till_done()


async def test_dhcp_discovery_known_host(
    hass: HomeAssistant, config_entry: MockConfigEntry, switch: FakeSwitch
) -> None:
    """Discovery of an already-configured host aborts."""
    config_entry.add_to_hass(hass)
    info = _dhcp("10.0.0.10", "aabbccddeeff", "spine1")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_DHCP}, data=info
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_flow(
    hass: HomeAssistant, config_entry: MockConfigEntry, switch: FakeSwitch
) -> None:
    """A reauth flow validates and updates credentials."""
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_REAUTH,
            "entry_id": config_entry.entry_id,
        },
        data=dict(config_entry.data),
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: "homeassistant", CONF_PASSWORD: "newsecret"},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_PASSWORD] == "newsecret"
    await hass.async_block_till_done()


async def test_reauth_flow_invalid(
    hass: HomeAssistant, config_entry: MockConfigEntry, switch: FakeSwitch
) -> None:
    """A reauth flow reports invalid credentials."""
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_REAUTH,
            "entry_id": config_entry.entry_id,
        },
        data=dict(config_entry.data),
    )
    switch.auth_error = True
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: "homeassistant", CONF_PASSWORD: "bad"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_reconfigure_flow(
    hass: HomeAssistant, config_entry: MockConfigEntry, switch: FakeSwitch
) -> None:
    """A reconfigure flow updates connection details for the same device."""
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": config_entry.entry_id,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_HOST: "10.0.0.20"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_HOST] == "10.0.0.20"
    await hass.async_block_till_done()


async def test_reconfigure_wrong_device(
    hass: HomeAssistant, config_entry: MockConfigEntry, switch: FakeSwitch
) -> None:
    """Reconfiguring against a different switch is rejected."""
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": config_entry.entry_id,
        },
    )
    switch.responses["show version"] = {
        **switch.responses["show version"],
        "serialNumber": "DIFFERENT123",
    }
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_HOST: "10.0.0.20"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_device"


async def test_options_flow(
    hass: HomeAssistant, config_entry: MockConfigEntry, switch: FakeSwitch
) -> None:
    """The options flow stores polling and monitoring preferences."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_SCAN_INTERVAL: 30,
            CONF_MONITOR_INTERFACES: True,
            "monitor_transceivers": False,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options[CONF_SCAN_INTERVAL] == 30
    assert config_entry.options[CONF_MONITOR_INTERFACES] is True
