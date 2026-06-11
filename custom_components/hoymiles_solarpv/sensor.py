"""Sensor platform for the Hoymiles SolarPV integration."""

from __future__ import annotations

from decimal import Decimal

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import HoymilesConfigEntry
from .descriptions import DTU_SENSORS, MICROINVERTER_SENSORS, PORT_SENSORS
from .entity import HoymilesDtuEntity, HoymilesMicroinverterEntity, HoymilesPortEntity


def _coerce(value: object) -> float | int | str | None:
    """Convert a raw record value into a Home Assistant friendly native value."""
    if isinstance(value, Decimal):
        return float(value)
    return value  # type: ignore[return-value]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HoymilesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Hoymiles SolarPV sensors from a config entry."""
    coordinator = entry.runtime_data
    known_serials: set[str] = set()
    known_ports: set[tuple[str, int]] = set()

    @callback
    def _add_microinverter_entities() -> None:
        new_entities: list[SensorEntity] = []
        for microinverter in coordinator.data.microinverter_data:
            serial = microinverter.serial_number
            # Inverter-level sensors: one set per microinverter serial.
            if serial not in known_serials:
                known_serials.add(serial)
                new_entities.extend(
                    HoymilesMicroinverterSensor(coordinator, description, serial)
                    for description in MICROINVERTER_SENSORS
                )
            # Port-level sensors: one set per (serial, port).
            port_key = (serial, microinverter.port_number)
            if port_key not in known_ports:
                known_ports.add(port_key)
                new_entities.extend(
                    HoymilesPortSensor(coordinator, description, serial, microinverter.port_number)
                    for description in PORT_SENSORS
                )
        if new_entities:
            async_add_entities(new_entities)

    async_add_entities(HoymilesDtuSensor(coordinator, description) for description in DTU_SENSORS)
    _add_microinverter_entities()
    entry.async_on_unload(coordinator.async_add_listener(_add_microinverter_entities))


class HoymilesDtuSensor(HoymilesDtuEntity, SensorEntity):
    """Sensor reporting an aggregated DTU/plant value."""

    @property
    def native_value(self) -> float | int | str | None:
        """Return the current value of the sensor."""
        return _coerce(getattr(self.coordinator.data, self.entity_description.key))


class HoymilesMicroinverterSensor(HoymilesMicroinverterEntity, SensorEntity):
    """Sensor reporting an inverter-level value for a single microinverter."""

    @property
    def native_value(self) -> float | int | str | None:
        """Return the current value of the sensor."""
        microinverter = self.microinverter
        if microinverter is None:
            return None
        return _coerce(getattr(microinverter, self.entity_description.key))


class HoymilesPortSensor(HoymilesPortEntity, SensorEntity):
    """Sensor reporting a value for a single PV port of a microinverter."""

    @property
    def native_value(self) -> float | int | str | None:
        """Return the current value of the sensor."""
        port = self.port
        if port is None:
            return None
        return _coerce(getattr(port, self.entity_description.key))
