"""The Hoymiles SolarPV integration."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_MQTT_ENABLED,
    CONF_MQTT_HOST,
    CONF_MQTT_PASSWORD,
    CONF_MQTT_PORT,
    CONF_MQTT_TOPIC,
    CONF_MQTT_USERNAME,
    DEFAULT_MQTT_PORT,
    DEFAULT_MQTT_TOPIC,
)
from .coordinator import HoymilesConfigEntry, HoymilesDataUpdateCoordinator
from .mqtt import HoymilesMqttPublisher

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: HoymilesConfigEntry) -> bool:
    """Set up Hoymiles SolarPV from a config entry."""
    mqtt_publisher: HoymilesMqttPublisher | None = None
    if entry.data.get(CONF_MQTT_ENABLED):
        mqtt_publisher = HoymilesMqttPublisher(
            host=entry.data[CONF_MQTT_HOST],
            port=entry.data.get(CONF_MQTT_PORT, DEFAULT_MQTT_PORT),
            username=entry.data.get(CONF_MQTT_USERNAME),
            password=entry.data.get(CONF_MQTT_PASSWORD),
            topic_base=entry.data.get(CONF_MQTT_TOPIC, DEFAULT_MQTT_TOPIC),
        )

    coordinator = HoymilesDataUpdateCoordinator(hass, entry, mqtt_publisher)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HoymilesConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok and entry.data.get(CONF_MQTT_ENABLED):
        publisher = getattr(entry.runtime_data, "_mqtt_publisher", None)
        if publisher is not None:
            await hass.async_add_executor_job(publisher.close)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: HoymilesConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)
