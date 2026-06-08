"""Base entities for the Hoymiles SolarPV integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import HoymilesDataUpdateCoordinator
from .hoymiles import MicroinverterData


class HoymilesDtuEntity(CoordinatorEntity[HoymilesDataUpdateCoordinator]):
    """Base class for entities that represent the DTU (whole plant)."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HoymilesDataUpdateCoordinator,
        description: EntityDescription,
    ) -> None:
        """Initialize the DTU entity."""
        super().__init__(coordinator)
        self.entity_description = description
        dtu_serial = coordinator.data.dtu
        self._attr_unique_id = f"{dtu_serial}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, dtu_serial)},
            name=f"Hoymiles DTU {dtu_serial}",
            manufacturer=MANUFACTURER,
            model="DTU",
            serial_number=dtu_serial,
        )


class HoymilesMicroinverterEntity(CoordinatorEntity[HoymilesDataUpdateCoordinator]):
    """Base class for entities that represent a single microinverter."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HoymilesDataUpdateCoordinator,
        description: EntityDescription,
        serial_number: str,
    ) -> None:
        """Initialize the microinverter entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._serial_number = serial_number
        dtu_serial = coordinator.data.dtu
        self._attr_unique_id = f"{serial_number}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial_number)},
            name=f"Hoymiles Microinverter {serial_number}",
            manufacturer=MANUFACTURER,
            model="Microinverter",
            serial_number=serial_number,
            via_device=(DOMAIN, dtu_serial),
        )

    @property
    def microinverter(self) -> MicroinverterData | None:
        """Return the microinverter record from the latest poll, if present."""
        for microinverter in self.coordinator.data.microinverter_data:
            if microinverter.serial_number == self._serial_number:
                return microinverter
        return None

    @property
    def available(self) -> bool:
        """Return True if the coordinator succeeded and the inverter is present."""
        return super().available and self.microinverter is not None
