"""Data update coordinator and eAPI response parsers for Arista EOS."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import EosAuthError, EosClient, EosCommandError, EosConnectionError
from .const import (
    CMD_HOSTNAME,
    CMD_INTERFACES_RATES,
    CMD_INTERFACES_STATUS,
    CMD_PROCESSES,
    CMD_RELOAD_CAUSE,
    CMD_TRANSCEIVERS,
    CMD_VERSION,
    CONF_MONITOR_INTERFACES,
    CONF_MONITOR_TRANSCEIVERS,
    CONF_SCAN_INTERVAL,
    DEFAULT_MONITOR_INTERFACES,
    DEFAULT_MONITOR_TRANSCEIVERS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    ENV_COMMANDS,
    ENV_COMMANDS_LEGACY,
    INTERFACE_COMMANDS,
    ISSUE_NO_ENVIRONMENT,
    LOGGER,
    SYSTEM_COMMANDS,
)
from .data import EosData, Fan, Interface, PowerSupply, TempSensor, Transceiver

type AristaConfigEntry = ConfigEntry[AristaCoordinator]


def _as_float(value: Any) -> float | None:
    """Coerce a value to float, returning None if not possible."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    """Coerce a value to int, returning None if not possible."""
    result = _as_float(value)
    return None if result is None else int(result)


class AristaCoordinator(DataUpdateCoordinator[EosData]):
    """Coordinate polling of a single Arista switch via eAPI."""

    config_entry: AristaConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: AristaConfigEntry,
        client: EosClient,
    ) -> None:
        """Initialise the coordinator."""
        self.client = client
        self._environment_supported = True
        interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=timedelta(seconds=interval),
        )

    @property
    def _monitor_interfaces(self) -> bool:
        return bool(
            self.config_entry.options.get(CONF_MONITOR_INTERFACES, DEFAULT_MONITOR_INTERFACES)
        )

    @property
    def _monitor_transceivers(self) -> bool:
        return bool(
            self.config_entry.options.get(CONF_MONITOR_TRANSCEIVERS, DEFAULT_MONITOR_TRANSCEIVERS)
        )

    @property
    def _issue_id(self) -> str:
        return f"{ISSUE_NO_ENVIRONMENT}_{self.config_entry.entry_id}"

    def _set_environment_supported(self, *, supported: bool) -> None:
        """Track environment support and raise/clear the repair issue on transitions."""
        if supported == self._environment_supported:
            return
        self._environment_supported = supported
        if supported:
            ir.async_delete_issue(self.hass, DOMAIN, self._issue_id)
            return
        LOGGER.info(
            "Switch %s does not support environment commands; "
            "environment sensors will be unavailable",
            self.config_entry.title,
        )
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            self._issue_id,
            is_fixable=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key="no_environment_support",
            translation_placeholders={"name": self.config_entry.title},
        )

    async def _fetch_environment(
        self,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
        """Return (temperature, power, cooling) payloads, or None if unsupported.

        Tries the modern command set first, then the legacy set; a command error
        on both means the platform has no environment sensors.
        """
        for commands in (ENV_COMMANDS, ENV_COMMANDS_LEGACY):
            try:
                results = await self.client.run_cmds(list(commands))
            except EosCommandError:
                continue
            temperature, power, cooling = results
            return temperature, power, cooling
        return None

    async def _run(self, cmds: tuple[str, ...] | list[str]) -> dict[str, dict[str, Any]]:
        """Run a batch of commands and map each command to its result."""
        results = await self.client.run_cmds(list(cmds))
        return dict(zip(cmds, results, strict=False))

    async def _async_update_data(self) -> EosData:
        """Fetch and parse telemetry from the switch."""
        try:
            system = await self._run(SYSTEM_COMMANDS)
        except EosAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="invalid_auth"
            ) from err
        except (EosConnectionError, EosCommandError) as err:
            raise UpdateFailed(str(err)) from err

        data = _parse_system(system)

        # Environment is optional (absent on virtual platforms) and the command
        # names changed across EOS releases, so the modern "show system
        # environment" form is tried first, then the legacy "show environment" form.
        try:
            env = await self._fetch_environment()
        except EosConnectionError as err:
            raise UpdateFailed(str(err)) from err
        if env is None:
            self._set_environment_supported(supported=False)
        else:
            self._set_environment_supported(supported=True)
            _parse_environment(*env, data)

        if self._monitor_interfaces:
            try:
                interfaces = await self._run(INTERFACE_COMMANDS)
            except EosCommandError as err:
                LOGGER.debug("Interface telemetry unavailable: %s", err)
            except EosConnectionError as err:
                raise UpdateFailed(str(err)) from err
            else:
                _parse_interfaces(interfaces, data)

        if self._monitor_transceivers:
            try:
                xcvr = await self._run([CMD_TRANSCEIVERS])
            except EosCommandError as err:
                LOGGER.debug("Transceiver telemetry unavailable: %s", err)
            except EosConnectionError as err:
                raise UpdateFailed(str(err)) from err
            else:
                _parse_transceivers(xcvr, data)

        return data


def _parse_system(results: dict[str, dict[str, Any]]) -> EosData:
    """Parse the always-present system commands into a fresh EosData."""
    version = results.get(CMD_VERSION, {})
    hostname_data = results.get(CMD_HOSTNAME, {})

    boot_time: datetime | None = None
    if (boot_ts := _as_float(version.get("bootupTimestamp"))) is not None:
        boot_time = datetime.fromtimestamp(boot_ts, tz=UTC)

    memory_used_pct: float | None = None
    mem_total = _as_float(version.get("memTotal"))
    mem_free = _as_float(version.get("memFree"))
    if mem_total and mem_free is not None and mem_total > 0:
        memory_used_pct = round((mem_total - mem_free) / mem_total * 100, 1)

    hostname = (
        hostname_data.get("hostname")
        or hostname_data.get("fqdn")
        or version.get("modelName")
        or "Arista switch"
    )

    return EosData(
        serial=str(version.get("serialNumber") or "").strip(),
        hostname=str(hostname),
        model=str(version.get("modelName") or "Unknown"),
        version=str(version.get("version") or "Unknown"),
        hardware_revision=version.get("hardwareRevision") or None,
        boot_time=boot_time,
        reload_cause=_parse_reload_cause(results.get(CMD_RELOAD_CAUSE, {})),
        memory_used_pct=memory_used_pct,
        cpu_used_pct=_parse_cpu(results.get(CMD_PROCESSES, {})),
    )


def _parse_reload_cause(result: dict[str, Any]) -> str | None:
    """Extract the most recent reload cause description."""
    causes = result.get("resetCauses")
    if isinstance(causes, list) and causes:
        first = causes[0]
        if isinstance(first, dict):
            description = first.get("description")
            if description:
                return str(description)
    return None


def _parse_cpu(result: dict[str, Any]) -> float | None:
    """Compute CPU utilisation (percent) from 'show processes top once'."""
    cpu_info = result.get("cpuInfo")
    if not isinstance(cpu_info, dict):
        return None
    stats = cpu_info.get("%Cpu(s)")
    if not isinstance(stats, dict):
        return None
    idle = _as_float(stats.get("idle"))
    if idle is None:
        return None
    return round(max(0.0, min(100.0, 100.0 - idle)), 1)


def _iter_temp_sensors(payload: dict[str, Any]) -> list[TempSensor]:
    """Flatten temperature sensors across top-level, cards, and PSU slots."""
    sensors: list[TempSensor] = []

    def _collect(raw_list: Any) -> None:
        if not isinstance(raw_list, list):
            return
        for raw in raw_list:
            if not isinstance(raw, dict):
                continue
            sensors.append(
                TempSensor(
                    name=str(raw.get("name") or raw.get("description") or "sensor"),
                    current=_as_float(raw.get("currentTemperature")),
                    status=raw.get("hwStatus") or raw.get("status"),
                    description=raw.get("description") or None,
                    alert=bool(raw.get("inAlertState", False)),
                )
            )

    _collect(payload.get("tempSensors"))
    for group_key in ("cardSlots", "powerSupplySlots"):
        group = payload.get(group_key)
        if isinstance(group, list):
            for slot in group:
                if isinstance(slot, dict):
                    _collect(slot.get("tempSensors"))
    return sensors


def _parse_environment(
    temperature: dict[str, Any],
    power: dict[str, Any],
    cooling: dict[str, Any],
    data: EosData,
) -> None:
    """Parse environment temperature/power/cooling payloads into data (in place)."""
    data.temp_status = temperature.get("systemStatus")
    data.temp_sensors = _iter_temp_sensors(temperature)
    readings = [s.current for s in data.temp_sensors if s.current is not None]
    data.max_temperature = round(max(readings), 1) if readings else None

    supplies = power.get("powerSupplies")
    total = 0.0
    have_power = False
    if isinstance(supplies, dict):
        for name, raw in supplies.items():
            if not isinstance(raw, dict):
                continue
            output = _as_float(raw.get("outputPower"))
            if output is not None:
                total += output
                have_power = True
            data.power_supplies.append(
                PowerSupply(
                    name=str(name),
                    output_power=output,
                    input_current=_as_float(raw.get("inputCurrent")),
                    output_current=_as_float(raw.get("outputCurrent")),
                    capacity=_as_float(raw.get("capacity")),
                    state=raw.get("state"),
                )
            )
    data.total_output_power = round(total, 1) if have_power else None

    data.fan_status = cooling.get("systemStatus")
    for group_key in ("fanTraySlots", "powerSupplySlots"):
        group = cooling.get(group_key)
        if not isinstance(group, list):
            continue
        for slot in group:
            if not isinstance(slot, dict):
                continue
            fans = slot.get("fans")
            if not isinstance(fans, list):
                continue
            for raw in fans:
                if not isinstance(raw, dict):
                    continue
                data.fans.append(
                    Fan(
                        name=str(raw.get("label") or raw.get("name") or "fan"),
                        speed=_as_int(raw.get("actualSpeed") or raw.get("speed")),
                        status=raw.get("status"),
                    )
                )


def _parse_interfaces(results: dict[str, dict[str, Any]], data: EosData) -> None:
    """Parse interface status and rates (in place)."""
    statuses = results.get(CMD_INTERFACES_STATUS, {}).get("interfaceStatuses")
    rates = results.get(CMD_INTERFACES_RATES, {}).get("interfaces")
    rates = rates if isinstance(rates, dict) else {}

    if not isinstance(statuses, dict):
        return

    for name, raw in statuses.items():
        if not isinstance(raw, dict):
            continue
        raw_rate = rates.get(name)
        rate = raw_rate if isinstance(raw_rate, dict) else {}
        data.interfaces.append(
            Interface(
                name=str(name),
                link_status=raw.get("linkStatus"),
                description=raw.get("description") or None,
                bandwidth=_as_int(raw.get("bandwidth")),
                in_bps=_as_float(rate.get("inBpsRate")),
                out_bps=_as_float(rate.get("outBpsRate")),
            )
        )


def _parse_transceivers(results: dict[str, dict[str, Any]], data: EosData) -> None:
    """Parse transceiver (DOM) readings (in place)."""
    interfaces = results.get(CMD_TRANSCEIVERS, {}).get("interfaces")
    if not isinstance(interfaces, dict):
        return
    for name, raw in interfaces.items():
        if not isinstance(raw, dict):
            continue
        temperature = _as_float(raw.get("temperature"))
        if temperature is None:
            # No transceiver present in this port.
            continue
        data.transceivers.append(
            Transceiver(
                name=str(name),
                temperature=temperature,
                tx_power=_as_float(raw.get("txPower")),
                rx_power=_as_float(raw.get("rxPower")),
            )
        )
