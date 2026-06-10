"""
Optional re-publishing of DTU data to an external MQTT broker.

This is completely independent from Home Assistant's own MQTT integration.
It targets a user supplied broker (host/port/username/password) and publishes
Home Assistant MQTT-discovery compatible configuration and state messages so
the same data can be consumed by a second Home Assistant instance or any other
MQTT consumer.

All methods are synchronous and meant to be executed from an executor thread.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

import paho.mqtt.client as mqtt
from homeassistant.components.sensor import SensorDeviceClass, SensorEntityDescription
from homeassistant.helpers.entity import EntityDescription

from .const import MANUFACTURER
from .descriptions import DTU_BINARY_SENSORS, DTU_SENSORS, MICROINVERTER_SENSORS

if TYPE_CHECKING:
    from .hoymiles import MicroinverterData, PlantData

_LOGGER = logging.getLogger(__name__)

_DISCOVERY_PREFIX = "homeassistant"

# Synthetic DTU sensor carrying the time the data was published. It is handled
# only here (not a real plant attribute), so Home Assistant consumers can show
# how old the data is. ``timestamp`` device class renders as relative time.
_LAST_UPDATE_KEY = "last_update"
_LAST_UPDATE_SENSOR = SensorEntityDescription(
    key=_LAST_UPDATE_KEY,
    device_class=SensorDeviceClass.TIMESTAMP,
)


def _json_default(value: object) -> object:
    """JSON encoder helper that renders Decimal as float."""
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(f"Object of type {type(value)} is not JSON serializable")


class HoymilesMqttPublisher:
    """Publish plant data to an external MQTT broker."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        topic_base: str,
    ) -> None:
        """Initialize the publisher (no network activity yet)."""
        self._host = host
        self._port = port
        self._topic_base = topic_base.rstrip("/")
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if username:
            self._client.username_pw_set(username, password)
        self._configured = False

    # -- connection management ----------------------------------------------

    def _ensure_connected(self) -> None:
        if self._client.is_connected():
            return
        self._client.connect(self._host, self._port)
        self._client.loop_start()

    def close(self) -> None:
        """Disconnect from the broker."""
        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:  # noqa: BLE001 - best effort cleanup
            _LOGGER.debug("Error while disconnecting MQTT client", exc_info=True)

    # -- topic helpers ------------------------------------------------------

    def _state_topic(self, device_serial: str) -> str:
        return f"{self._topic_base}/{device_serial}/state"

    @staticmethod
    def _config_topic(platform: str, device_serial: str, key: str) -> str:
        return f"{_DISCOVERY_PREFIX}/{platform}/{device_serial}/{key}/config"

    # -- payload builders ---------------------------------------------------

    def _discovery_payloads(self, plant_data: PlantData) -> list[tuple[str, str]]:
        """Build all retained discovery config messages for the plant."""
        messages: list[tuple[str, str]] = []
        dtu_serial = plant_data.dtu

        for sensor in DTU_SENSORS:
            messages.append(self._build_discovery("sensor", "DTU", dtu_serial, dtu_serial, sensor))
        messages.append(
            self._build_discovery("sensor", "DTU", dtu_serial, dtu_serial, _LAST_UPDATE_SENSOR)
        )
        for binary_sensor in DTU_BINARY_SENSORS:
            messages.append(
                self._build_discovery("binary_sensor", "DTU", dtu_serial, dtu_serial, binary_sensor)
            )
        for microinverter in plant_data.microinverter_data:
            serial = microinverter.serial_number
            for sensor in MICROINVERTER_SENSORS:
                messages.append(
                    self._build_discovery(
                        "sensor", f"Inverter {serial}", serial, dtu_serial, sensor
                    )
                )
        return messages

    def _build_discovery(
        self,
        platform: str,
        device_name: str,
        device_serial: str,
        dtu_serial: str,
        description: EntityDescription,
    ) -> tuple[str, str]:
        state_topic = self._state_topic(device_serial)
        key = description.key
        payload: dict[str, object] = {
            "name": key,
            "unique_id": f"hoymiles_solarpv_{device_serial}_{key}",
            "object_id": f"hoymiles_{device_serial}_{key}",
            "state_topic": state_topic,
            "value_template": (
                f"{{{{ value_json.{key} if value_json.{key} is defined else None }}}}"
            ),
            "device": {
                "identifiers": [f"hoymiles_solarpv_{device_serial}"],
                "name": device_name,
                "manufacturer": MANUFACTURER,
                "via_device": f"hoymiles_solarpv_{dtu_serial}",
            },
        }
        device_class = getattr(description, "device_class", None)
        if device_class is not None:
            payload["device_class"] = str(device_class)
        unit = getattr(description, "native_unit_of_measurement", None)
        if unit is not None:
            payload["unit_of_measurement"] = unit
        state_class = getattr(description, "state_class", None)
        if state_class is not None:
            payload["state_class"] = str(state_class)
        topic = self._config_topic(platform, device_serial, key)
        return topic, json.dumps(payload)

    def _state_payloads(self, plant_data: PlantData, timestamp: datetime) -> list[tuple[str, str]]:
        messages: list[tuple[str, str]] = []
        dtu_values: dict[str, object] = {
            description.key: getattr(plant_data, description.key) for description in DTU_SENSORS
        }
        for description in DTU_BINARY_SENSORS:
            dtu_values[description.key] = "ON" if getattr(plant_data, description.key) else "OFF"
        # ISO 8601 timestamp so HA can render the data age as relative time.
        dtu_values[_LAST_UPDATE_KEY] = timestamp.isoformat()
        messages.append(
            (self._state_topic(plant_data.dtu), json.dumps(dtu_values, default=_json_default))
        )

        seen: set[str] = set()
        for microinverter in plant_data.microinverter_data:
            serial = microinverter.serial_number
            if serial in seen:
                continue
            seen.add(serial)
            messages.append(self._microinverter_state(microinverter))
        return messages

    def _microinverter_state(self, microinverter: MicroinverterData) -> tuple[str, str]:
        values = {
            description.key: getattr(microinverter, description.key)
            for description in MICROINVERTER_SENSORS
        }
        return (
            self._state_topic(microinverter.serial_number),
            json.dumps(values, default=_json_default),
        )

    # -- public API ---------------------------------------------------------

    def publish_plant_data(self, plant_data: PlantData, timestamp: datetime | None = None) -> None:
        """Publish discovery (once) and state messages for the given plant data.

        Arguments:
            plant_data: the data to publish.
            timestamp: time the data was read; defaults to ``now`` (UTC). Published
                as a ``last_update`` timestamp sensor so consumers can show data age.

        Raises whatever the underlying MQTT client raises on connection errors;
        the coordinator is responsible for logging and continuing.
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        self._ensure_connected()

        if not self._configured:
            for topic, payload in self._discovery_payloads(plant_data):
                self._client.publish(topic, payload, retain=True)
            self._configured = True
            _LOGGER.debug("Published MQTT discovery config for DTU %s", plant_data.dtu)

        for topic, payload in self._state_payloads(plant_data, timestamp):
            self._client.publish(topic, payload)
        _LOGGER.debug("Published MQTT state for DTU %s", plant_data.dtu)
