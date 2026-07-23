# Arista EOS

Monitor Arista EOS switches in Home Assistant over eAPI (read‑only, local polling).

**Entities per switch:** temperature (max + alarm + per‑sensor), power draw + PSU status,
fan status + fan speeds, CPU/memory, last boot, EOS version, reload cause, and — optionally —
per‑interface link/throughput and transceiver temperatures.

**Setup:** enable eAPI on the switch (`management api http-commands` → `no shutdown`), then add the
integration and enter the management address and credentials. Switches are also auto‑discovered via
DHCP.

Built to the Home Assistant Integration Quality Scale **Platinum** tier — async, strictly typed,
config flow with reauth/reconfigure, diagnostics, and repair issues.
