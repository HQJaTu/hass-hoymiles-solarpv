"""Diagnostics support for the Hoymiles SolarPV integration.

Lets the user download (Settings -> Devices & Services -> Hoymiles SolarPV ->
the three-dot menu -> Download diagnostics) a redacted snapshot of the stored
configuration and the most recent poll, to verify their settings.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.redact import async_redact_data

from .const import CONF_MQTT_PASSWORD
from .coordinator import HoymilesConfigEntry

# Only the password is hidden; host/port/topic/username are shown so settings
# can actually be verified.
TO_REDACT = {CONF_MQTT_PASSWORD}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HoymilesConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    plant = coordinator.data

    return {
        "config": {
            "title": entry.title,
            "unique_id": entry.unique_id,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "status": {
            "last_update_success": coordinator.last_update_success,
            "update_interval_seconds": (
                coordinator.update_interval.total_seconds() if coordinator.update_interval else None
            ),
        },
        "data": {
            "dtu": plant.dtu if plant else None,
            "microinverter_records": len(plant.microinverter_data) if plant else 0,
            "pv_power": float(plant.pv_power) if plant else None,
            "today_production": plant.today_production if plant else None,
            "total_production": plant.total_production if plant else None,
            "alarm_flag": plant.alarm_flag if plant else None,
        },
    }
