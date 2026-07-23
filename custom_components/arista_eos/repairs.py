"""Repair flows for the Arista EOS integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.core import HomeAssistant


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, Any] | None,
) -> RepairsFlow:
    """Create a fix flow for an integration repair issue.

    All current issues are acknowledgement-only, so a confirm flow is returned;
    confirming dismisses the issue until the condition recurs.
    """
    return ConfirmRepairFlow()
