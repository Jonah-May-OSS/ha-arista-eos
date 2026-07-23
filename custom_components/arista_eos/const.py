"""Constants for the Arista EOS integration."""

from __future__ import annotations

import logging
from typing import Final

DOMAIN: Final = "arista_eos"
LOGGER: Final = logging.getLogger(__package__)

MANUFACTURER: Final = "Arista"

# Config entry data (standard keys — CONF_HOST/USERNAME/PASSWORD/PORT/VERIFY_SSL —
# are imported from homeassistant.const; only integration-specific keys live here).
CONF_MAC: Final = "mac"

# Options
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_MONITOR_INTERFACES: Final = "monitor_interfaces"
CONF_MONITOR_TRANSCEIVERS: Final = "monitor_transceivers"

DEFAULT_PORT: Final = 443
DEFAULT_VERIFY_SSL: Final = False
DEFAULT_SCAN_INTERVAL: Final = 60
MIN_SCAN_INTERVAL: Final = 15
DEFAULT_MONITOR_INTERFACES: Final = False
DEFAULT_MONITOR_TRANSCEIVERS: Final = False

# eAPI commands
CMD_VERSION: Final = "show version"
CMD_HOSTNAME: Final = "show hostname"
CMD_PROCESSES: Final = "show processes top once"
CMD_RELOAD_CAUSE: Final = "show reload cause"
CMD_TEMPERATURE: Final = "show environment temperature"
CMD_POWER: Final = "show environment power"
CMD_COOLING: Final = "show environment cooling"
CMD_INTERFACES_STATUS: Final = "show interfaces status"
CMD_INTERFACES_RATES: Final = "show interfaces counters rates"
CMD_TRANSCEIVERS: Final = "show interfaces transceiver"

# System commands are universally supported (including virtual EOS) and must
# succeed for the integration to be considered up.
SYSTEM_COMMANDS: Final = (CMD_VERSION, CMD_HOSTNAME, CMD_PROCESSES, CMD_RELOAD_CAUSE)
# Environment commands are absent on virtual platforms; failure is tolerated.
ENV_COMMANDS: Final = (CMD_TEMPERATURE, CMD_POWER, CMD_COOLING)
INTERFACE_COMMANDS: Final = (CMD_INTERFACES_STATUS, CMD_INTERFACES_RATES)

# Repair issue identifiers
ISSUE_NO_ENVIRONMENT: Final = "no_environment_support"
