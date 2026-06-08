"""DataUpdateCoordinator for the Hoymiles SolarPV integration."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_MICROINVERTER_TYPE,
    CONF_MQTT_ENABLED,
    CONF_UNIT_ID,
    DEFAULT_MICROINVERTER_TYPE,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_UNIT_ID,
    DOMAIN,
)
from .hoymiles import HoymilesModbusError, HoymilesModbusTCP, MicroinverterType, PlantData
from .mqtt import HoymilesMqttPublisher

_LOGGER = logging.getLogger(__name__)

type HoymilesConfigEntry = ConfigEntry[HoymilesDataUpdateCoordinator]


class HoymilesDataUpdateCoordinator(DataUpdateCoordinator[PlantData]):
    """Coordinate polling of a Hoymiles DTU and optional MQTT re-publishing."""

    config_entry: HoymilesConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: HoymilesConfigEntry,
        mqtt_publisher: HoymilesMqttPublisher | None,
    ) -> None:
        """Initialize the coordinator."""
        scan_interval = config_entry.options.get("scan_interval", DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self._client = HoymilesModbusTCP(
            host=config_entry.data[CONF_HOST],
            port=config_entry.data.get(CONF_PORT, DEFAULT_PORT),
            microinverter_type=MicroinverterType(
                config_entry.data.get(CONF_MICROINVERTER_TYPE, DEFAULT_MICROINVERTER_TYPE)
            ),
            unit_id=config_entry.data.get(CONF_UNIT_ID, DEFAULT_UNIT_ID),
        )
        self._mqtt_publisher = mqtt_publisher
        self._mqtt_enabled = config_entry.data.get(CONF_MQTT_ENABLED, False)

    @property
    def client(self) -> HoymilesModbusTCP:
        """Return the underlying Modbus client."""
        return self._client

    async def _async_update_data(self) -> PlantData:
        """Fetch data from the DTU (and optionally publish it to MQTT)."""
        try:
            plant_data = await self.hass.async_add_executor_job(self._client.get_plant_data)
        except HoymilesModbusError as err:
            raise UpdateFailed(f"Error communicating with Hoymiles DTU: {err}") from err

        if self._mqtt_enabled and self._mqtt_publisher is not None:
            # MQTT publishing must never break data collection; log and continue.
            try:
                await self.hass.async_add_executor_job(
                    self._mqtt_publisher.publish_plant_data, plant_data
                )
            except Exception:  # noqa: BLE001 - publishing is best effort
                _LOGGER.exception("Failed to publish Hoymiles data to MQTT broker")

        return plant_data
