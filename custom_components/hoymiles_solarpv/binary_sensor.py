"""Binary sensor platform for the Hoymiles SolarPV integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import HoymilesConfigEntry
from .descriptions import DTU_BINARY_SENSORS
from .entity import HoymilesDtuEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HoymilesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Hoymiles SolarPV binary sensors from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        HoymilesDtuBinarySensor(coordinator, description)
        for description in DTU_BINARY_SENSORS
    )


class HoymilesDtuBinarySensor(HoymilesDtuEntity, BinarySensorEntity):
    """Binary sensor reporting a DTU/plant boolean value."""

    @property
    def is_on(self) -> bool:
        """Return True if the underlying flag is set."""
        return bool(getattr(self.coordinator.data, self.entity_description.key))
