# Hoymiles SolarPV — Home Assistant integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

This project is a custom [Home Assistant](https://www.home-assistant.io/) integration that reads
photovoltaic sensor data from a **Hoymiles DTU** (e.g. DTU-Pro) over **Modbus TCP**
and exposes it as native Home Assistant entities. It can additionally re-publish all
received records to an **external MQTT broker** using the Home Assistant MQTT
discovery format.

The integration talks to the DTU using the same `pymodbus` stack that ships with
Home Assistant's built-in Modbus integration, while handling the Hoymiles-specific
framing quirk transparently.

## Features

- 🔌 **Local polling** of a supported Hoymiles DTU — no cloud required.
- 🏭 Native Home Assitant entities for the **DTU/plant**.
- 📡 Optional **MQTT support**.

### Technical
- 🔌 **Local polling** of a Hoymiles DTU over Modbus TCP — no cloud required.
- 🧭 Native **config flow** — set up entirely from the UI (host, port, unit ID,
  microinverter type).
- ♻️ Native **`DataUpdateCoordinator`** — a single poll feeds all entities.
- 🏭 Entities for the **DTU/plant** (current power, today's & total production,
  alarm state) and for **each microinverter** (PV voltage/current/power, grid
  voltage/frequency, temperature, status, alarms, link state).
- 📡 Optional **MQTT re-publishing** to any external broker (host, port, username,
  password) with HA-discovery config and JSON state messages.
- 🧱 Fully **asynchronous**, all blocking Modbus/MQTT I/O runs in the executor.
- 🧪 Errors are handled and surfaced through Home Assistant logging.

## Supported devices

Hoymiles DTU devices that expose the Modbus TCP interface (DTU-Pro and compatible),
managing **MI** or **HM** series microinverters.

Note: All microinverters in one DTU must
be of the same family.

## Installation

### HACS (recommended)

1. In HACS, add this repository as a **Custom repository** of type *Integration*.
2. Install **Hoymiles SolarPV**.
3. Restart Home Assistant.

### Manual

Copy the `custom_components/hoymiles_solarpv` directory into your Home Assistant
`config/custom_components/` directory and restart Home Assistant.

## Configuration

> **Note:** Installing via HACS only copies the files — it does **not** create a
> device. You must add the integration afterwards (step 1 below) to enter the
> connection settings.

Configuration is done entirely through the UI:

1. Go to **Settings → Devices & Services → Add Integration**.
2. Search for **Hoymiles SolarPV**.
3. Fill in the form:

   | Field | Description | Default |
   |-------|-------------|---------|
   | DTU host | IP / hostname of the DTU | — |
   | DTU Modbus port | Modbus TCP port of the DTU | `502` |
   | Microinverter type | `MI` or `HM` | `MI` |
   | Modbus unit ID | Modbus device/unit ID | `1` |
   | Re-publish to MQTT | Enable external MQTT re-publishing | off |
   | MQTT broker host/port | External broker address | `1883` |
   | MQTT username/password | Broker credentials (optional) | — |
   | MQTT base topic | Topic prefix for state messages | `homeassistant/hoymiles_solarpv` |

The integration validates the connection to the DTU before finishing setup and uses
the DTU serial number as a unique identifier.

### Options

After setup, open the integration's **Configure** dialog to change the **polling
interval** (in seconds, default `60`).

### Reconfigure (change host / MQTT)

To change the DTU host/port, microinverter type, unit ID or MQTT settings after
setup: **Settings → Devices & Services → Hoymiles SolarPV → ⋮ → Reconfigure**.
The form is pre-filled with your current values; the connection is re-validated and
must still report the same DTU serial.

### Verify your settings

To see exactly what is stored (handy if you're unsure what was entered):
**Settings → Devices & Services → Hoymiles SolarPV → ⋮ → Download diagnostics**.
The downloaded file lists the host, port, type, unit ID and MQTT settings (the MQTT
password is redacted) plus the latest poll summary.

## Entities

A device is created for the DTU and one device per discovered microinverter
(linked to the DTU as their parent).

**DTU / plant**

- PV power (W)
- Today's production (Wh)
- Total production (Wh)
- Alarm (binary problem sensor)

**Per microinverter**

- PV voltage (V), PV current (A), PV power (W)
- Grid voltage (V), Grid frequency (Hz)
- Temperature (°C)
- Today's / Total production (Wh)
- Operating status, Alarm code, Alarm count, Link status (diagnostic)

The energy sensors use the `total_increasing` state class and can be added to the
Home Assistant **Energy dashboard**.

### Production smoothing & daily reset

Hoymiles DTUs occasionally report a momentarily *lower* today/total production
value, and they reset the **today** counter at ~22:00 local time (not midnight).
To keep the Energy dashboard accurate the integration keeps an in-memory monotonic
cache per microinverter port: transient dips are clamped to the last good value,
while the genuine daily reset around hour 22 is detected and lets the today counter
fall back to zero exactly once per day. The cache is rebuilt from live values after
a Home Assistant restart.

## MQTT re-publishing

When enabled, after each poll the integration publishes:

- retained **discovery** messages under `homeassistant/<platform>/<serial>/<key>/config`
- **state** messages (JSON):
  - plant/DTU: `<base_topic>/<dtu_serial>/state`
  - microinverter (inverter-wide telemetry — grid, temperature, status): `<base_topic>/<serial>/state`
  - each PV **port** of a microinverter (voltage/current/power/production):
    `<base_topic>/<serial>/<port>/state`

A microinverter with multiple PV inputs reports one record per port, so each port
gets its own state topic and its own set of discovery entities (named `Port N …`),
all grouped under the one microinverter device.

This lets a second Home Assistant instance (or any MQTT consumer) auto-discover the
same entities. MQTT publishing is *best effort*: failures are logged and never
interrupt data collection in this instance.

The DTU state message also carries a `last_update` field — an ISO 8601 timestamp of
when the data was published — exposed as a `timestamp` sensor on the DTU device.
Home Assistant renders it as relative time ("3 minutes ago"), so dashboards can show
how fresh the data is.

## Troubleshooting

Enable debug logging by adding to `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.hoymiles_solarpv: debug
```

- **Cannot connect** during setup: verify the DTU IP/port and that the DTU is on and
  reachable. The DTU must have finished mapping its microinverters.
- **Entities unavailable**: a microinverter may have lost its RF link to the DTU;
  it becomes available again on the next successful poll.

## Development
See [DEVELOPMENT.md](DEVELOPMENT.md) for details.

## Credits

Modbus protocol handling is derived from the https://github.com/wasilukm/hoymiles_modbus / https://github.com/wasilukm/hoymiles-mqtt
projects and re-implemented as a self-contained, Home-Assistant-friendly module.

## License

MIT
