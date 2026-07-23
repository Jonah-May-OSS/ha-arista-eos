# Arista EOS for Home Assistant

[![hacs][hacs-badge]][hacs] [![validate][validate-badge]][validate-workflow] [![tests][tests-badge]][tests-workflow]

A [Home Assistant][ha] custom integration that monitors **Arista EOS** switches over the
[eAPI][eapi] JSON‑RPC interface. It is **read‑only** and **local‑polling** — no cloud, no writes.

Built to the Home Assistant [Integration Quality Scale][quality-scale] **Platinum** tier: fully
async, strictly typed, config‑flow driven, with reauth, reconfigure, DHCP discovery, diagnostics,
repair issues, and a test suite.

## Features

Per switch (created as a single Home Assistant **device**):

| Category | Entities |
| --- | --- |
| Temperature | Max temperature, temperature alarm, per‑sensor temperatures\* |
| Power | Total power draw, power‑supply status (+ per‑PSU power\* and per‑PSU problem\*) |
| Cooling | Fan status (+ per‑fan speed\* and per‑fan problem\*) |
| System | CPU %, memory %, last boot, EOS version, reload cause |
| Interfaces† | Per‑interface link (connectivity) and inbound/outbound throughput |
| Transceivers† | Per‑transceiver (DOM) temperature |

\* Disabled by default (enable per entity in the entity settings).
† Created only when the corresponding option is enabled (see [Options](#options)).

## Supported devices

Any Arista switch running EOS with eAPI enabled — fixed (e.g. 7050X/7060X/720XP) and modular
(e.g. 7500/7300) platforms are both handled by the model‑tolerant parsers. Virtual platforms
(vEOS/cEOS) work for system entities; they have no physical sensors, so environment entities are
unavailable and the integration raises a dismissible repair notice.

## Prerequisites — enable eAPI on the switch

```eos
configure
username homeassistant privilege 1 role network-operator secret <password>
management api http-commands
   protocol https
   no shutdown
```

A read‑only role (`network-operator`) is sufficient — the integration never issues configuration
commands.

## Installation

### HACS (recommended)

HACS must be installed first. Installing through HACS means you get updates automatically.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Jonah-May-OSS&repository=ha-arista-eos&category=integration)

Click the button above to add this repository to HACS, then choose **Download** and restart Home Assistant.

<details>
<summary>…or add the repository manually</summary>

1. In HACS, open the **⋮** menu (top‑right) → **Custom repositories**.
2. Repository: `https://github.com/Jonah-May-OSS/ha-arista-eos` — Category: **Integration**.
3. Click **Add**, then find **Arista EOS** in HACS, choose **Download**, and restart Home Assistant.

</details>

### Manual

1. Download the latest release from the [releases page](https://github.com/Jonah-May-OSS/ha-arista-eos/releases).
2. Copy the `custom_components/arista_eos` folder into your Home Assistant `config/custom_components/` directory.
3. Restart Home Assistant.

## Add the integration

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=arista_eos)

## Configuration

**Settings → Devices & services → Add integration → Arista EOS.** Arista switches on the network are
also auto‑discovered via DHCP and appear as discovered devices ready to configure.

### Installation parameters

| Field | Description | Default |
| --- | --- | --- |
| Host | Hostname or management IP of the switch | — |
| Username | eAPI username | — |
| Password | eAPI password | — |
| Port | eAPI HTTPS port | `443` |
| Verify SSL certificate | Validate the switch TLS certificate | Off |

`Verify SSL` is off by default because switches typically present a self‑signed management
certificate. Turn it on only if the switch presents a certificate trusted by Home Assistant.

### Options

**Settings → Devices & services → Arista EOS → Configure.**

| Option | Description | Default |
| --- | --- | --- |
| Polling interval (seconds) | How often to poll the switch | `60` |
| Monitor interfaces | Create per‑interface link + throughput entities (high entity count) | Off |
| Monitor transceivers | Create per‑transceiver temperature entities | Off |

## How data is updated

A single `DataUpdateCoordinator` polls the switch on the configured interval using eAPI `runCmds`.
System commands (`show version`, `show hostname`, `show processes top once`, `show reload cause`) run
first; environment commands (`show system environment temperature|power|cooling`) run separately so a
platform without sensors cannot take down the system entities; interface/transceiver commands run
only when their options are enabled. Authentication failures trigger the Home Assistant
re‑authentication flow.

## Example automation

```yaml
automation:
  - alias: "Arista overheating alert"
    trigger:
      - trigger: state
        entity_id: binary_sensor.spine1_temperature_alarm
        to: "on"
    action:
      - action: notify.mobile_app_phone
        data:
          title: "Switch overheating"
          message: >
            {{ state_attr('sensor.spine1_temperature', 'friendly_name') }} is
            {{ states('sensor.spine1_temperature') }} °C
```

## Use cases

- Rack thermal and power dashboards alongside servers and PDUs.
- Alerting on PSU/fan failure or link‑down on uplinks.
- Correlating switch power draw with per‑circuit energy monitoring.

## Known limitations

- **Read‑only**: no configuration or control actions are exposed.
- **Virtual EOS** (vEOS/cEOS) has no environment sensors; those entities are unavailable.
- Enabling interface monitoring on a high‑port‑count switch creates many entities; per‑interface
  entities are intended to be enabled selectively.
- Per‑sensor / per‑PSU / per‑fan entities are disabled by default to keep the device tidy.

## Troubleshooting

- **`cannot_connect`** — verify the host/port, that `management api http-commands` is `no shutdown`,
  and that Home Assistant can reach the management IP over HTTPS.
- **`invalid_auth`** — the username/password/role is wrong; `network-operator` (or higher) is required.
- **Environment entities unavailable** — expected on virtual platforms; otherwise confirm
  `show system environment temperature` returns data on the switch CLI.
- **Diagnostics** — download from the device page (**⋮ → Download diagnostics**); credentials are redacted.

## Removal

**Settings → Devices & services → Arista EOS → ⋮ → Delete**. No files or switch configuration remain.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-test.txt
ruff check .
mypy custom_components/arista_eos
pytest
```

## License

[MIT](LICENSE) © Jonah May

[ha]: https://www.home-assistant.io/
[eapi]: https://www.arista.com/en/support/toi/eos-4-12-3/eapi
[quality-scale]: https://developers.home-assistant.io/docs/core/integration-quality-scale/
[hacs]: https://hacs.xyz/
[hacs-badge]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg
[validate-badge]: https://github.com/Jonah-May-OSS/ha-arista-eos/actions/workflows/validate.yml/badge.svg
[validate-workflow]: https://github.com/Jonah-May-OSS/ha-arista-eos/actions/workflows/validate.yml
[tests-badge]: https://github.com/Jonah-May-OSS/ha-arista-eos/actions/workflows/test.yml/badge.svg
[tests-workflow]: https://github.com/Jonah-May-OSS/ha-arista-eos/actions/workflows/test.yml
