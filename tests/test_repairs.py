"""Tests for repair flows."""

from __future__ import annotations

from custom_components.arista_eos.repairs import async_create_fix_flow
from homeassistant.components.repairs import ConfirmRepairFlow
from homeassistant.core import HomeAssistant


async def test_create_fix_flow(hass: HomeAssistant) -> None:
    """The repair issue is acknowledged via a confirm flow."""
    flow = await async_create_fix_flow(hass, "no_environment_support_abc", None)
    assert isinstance(flow, ConfirmRepairFlow)
