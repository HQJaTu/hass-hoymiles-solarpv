"""
Constants for the Hoymiles SolarPV integration.
"""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "hoymiles_solarpv"

# Default Modbus / polling settings
DEFAULT_PORT: Final = 502
DEFAULT_UNIT_ID: Final = 1
DEFAULT_SCAN_INTERVAL: Final = 60
DEFAULT_MICROINVERTER_TYPE: Final = "MI"

MICROINVERTER_TYPES: Final = ["MI", "HM"]

# Configuration keys (Modbus)
CONF_UNIT_ID: Final = "unit_id"
CONF_MICROINVERTER_TYPE: Final = "microinverter_type"

# Configuration keys (MQTT re-publishing - optional)
CONF_MQTT_ENABLED: Final = "mqtt_enabled"
CONF_MQTT_HOST: Final = "mqtt_host"
CONF_MQTT_PORT: Final = "mqtt_port"
CONF_MQTT_USERNAME: Final = "mqtt_username"
CONF_MQTT_PASSWORD: Final = "mqtt_password"
CONF_MQTT_TOPIC: Final = "mqtt_topic"

DEFAULT_MQTT_PORT: Final = 1883
DEFAULT_MQTT_TOPIC: Final = "homeassistant/hoymiles_solarpv"

# Manufacturer string used for the device registry
MANUFACTURER: Final = "Hoymiles"
