"""Typed data models for parsed Arista EOS telemetry."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class TempSensor:
    """A single temperature sensor reading."""

    name: str
    current: float | None = None
    status: str | None = None
    description: str | None = None
    alert: bool = False


@dataclass(slots=True)
class PowerSupply:
    """A power supply unit reading."""

    name: str
    output_power: float | None = None
    input_current: float | None = None
    output_current: float | None = None
    capacity: float | None = None
    state: str | None = None


@dataclass(slots=True)
class Fan:
    """A fan reading."""

    name: str
    speed: int | None = None
    status: str | None = None


@dataclass(slots=True)
class Interface:
    """An interface status/rate reading."""

    name: str
    link_status: str | None = None
    description: str | None = None
    bandwidth: int | None = None
    in_bps: float | None = None
    out_bps: float | None = None

    @property
    def connected(self) -> bool | None:
        """Return whether the link is connected, or None if unknown."""
        if self.link_status is None:
            return None
        return self.link_status.lower() == "connected"


@dataclass(slots=True)
class Transceiver:
    """A transceiver (DOM) reading."""

    name: str
    temperature: float | None = None
    tx_power: float | None = None
    rx_power: float | None = None


@dataclass(slots=True)
class EosData:
    """Aggregated, parsed telemetry for a single switch."""

    # Identity / system
    serial: str
    hostname: str
    model: str
    version: str
    hardware_revision: str | None = None
    boot_time: datetime | None = None
    reload_cause: str | None = None

    # Health
    memory_used_pct: float | None = None
    cpu_used_pct: float | None = None

    # Environment — temperature
    temp_status: str | None = None
    max_temperature: float | None = None
    temp_sensors: list[TempSensor] = field(default_factory=list)

    # Environment — power
    total_output_power: float | None = None
    power_supplies: list[PowerSupply] = field(default_factory=list)

    # Environment — cooling
    fan_status: str | None = None
    fans: list[Fan] = field(default_factory=list)

    # Optional
    interfaces: list[Interface] = field(default_factory=list)
    transceivers: list[Transceiver] = field(default_factory=list)

    @property
    def temp_alarm(self) -> bool:
        """Return True if any temperature sensor is in alert or overall status is not ok."""
        status_bad = self.temp_status is not None and self.temp_status.lower() not in (
            "ok",
            "temperatureok",
        )
        return status_bad or any(sensor.alert for sensor in self.temp_sensors)

    @property
    def psu_problem(self) -> bool:
        """Return True if any power supply reports a non-ok state."""
        return any(
            psu.state is not None and psu.state.lower() != "ok" for psu in self.power_supplies
        )

    @property
    def fan_problem(self) -> bool:
        """Return True if any fan (or overall cooling status) reports a non-ok state."""
        if self.fan_status is not None and self.fan_status.lower() not in ("ok", "coolingok"):
            return True
        return any(fan.status is not None and fan.status.lower() != "ok" for fan in self.fans)
