"""Tests for setup, entities and unload of the Hoymiles SolarPV integration."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hoymiles_solarpv.const import (
    CONF_MICROINVERTER_TYPE,
    CONF_MQTT_ENABLED,
    CONF_UNIT_ID,
    DOMAIN,
)

_ENTRY_DATA = {
    CONF_HOST: "192.168.1.50",
    CONF_PORT: 502,
    CONF_MICROINVERTER_TYPE: "MI",
    CONF_UNIT_ID: 1,
    CONF_MQTT_ENABLED: False,
}


async def _setup(hass: HomeAssistant, plant_data) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="aabbccddeeff", data=_ENTRY_DATA)
    entry.add_to_hass(hass)
    with patch(
        "custom_components.hoymiles_solarpv.coordinator.HoymilesModbusTCP.get_plant_data",
        return_value=plant_data,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_setup_creates_entities(hass: HomeAssistant, sample_plant_data) -> None:
    """Setup creates DTU and microinverter entities with correct values."""
    entry = await _setup(hass, sample_plant_data)
    assert entry.state is ConfigEntryState.LOADED

    dtu_power = hass.states.get("sensor.hoymiles_dtu_aabbccddeeff_pv_power")
    assert dtu_power is not None
    assert float(dtu_power.state) == 150.0

    alarm = hass.states.get("binary_sensor.hoymiles_dtu_aabbccddeeff_alarm")
    assert alarm is not None
    assert alarm.state == "off"

    # Inverter-level sensor (per serial).
    mi_temp = hass.states.get("sensor.hoymiles_microinverter_112233445566_temperature")
    assert mi_temp is not None
    assert float(mi_temp.state) == 35.5

    # Port-level sensor (per serial + port), name carries the port number.
    port_voltage = hass.states.get("sensor.hoymiles_microinverter_112233445566_port_1_pv_voltage")
    assert port_voltage is not None
    assert float(port_voltage.state) == 245.0


async def test_unload_entry(hass: HomeAssistant, sample_plant_data) -> None:
    """An entry can be unloaded cleanly."""
    entry = await _setup(hass, sample_plant_data)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_failure_raises_retry(hass: HomeAssistant) -> None:
    """A communication error during first refresh sets the entry to retry."""
    from custom_components.hoymiles_solarpv.hoymiles import HoymilesModbusError

    entry = MockConfigEntry(domain=DOMAIN, unique_id="aabbccddeeff", data=_ENTRY_DATA)
    entry.add_to_hass(hass)
    with patch(
        "custom_components.hoymiles_solarpv.coordinator.HoymilesModbusTCP.get_plant_data",
        side_effect=HoymilesModbusError("no route"),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_diagnostics_redacts_password(hass: HomeAssistant, sample_plant_data) -> None:
    """Diagnostics expose the settings for verification, with the password hidden."""
    from custom_components.hoymiles_solarpv.const import (
        CONF_MQTT_HOST,
        CONF_MQTT_PASSWORD,
    )
    from custom_components.hoymiles_solarpv.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    # MQTT stays disabled (so setup doesn't open a broker socket), but the stored
    # credentials are still present and must be redacted in diagnostics.
    data = dict(_ENTRY_DATA)
    data[CONF_MQTT_HOST] = "10.0.0.5"
    data[CONF_MQTT_PASSWORD] = "supersecret"

    entry = MockConfigEntry(domain=DOMAIN, unique_id="aabbccddeeff", data=data)
    entry.add_to_hass(hass)
    with patch(
        "custom_components.hoymiles_solarpv.coordinator.HoymilesModbusTCP.get_plant_data",
        return_value=sample_plant_data,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["config"]["data"][CONF_HOST] == "192.168.1.50"
    assert diag["config"]["data"][CONF_MQTT_HOST] == "10.0.0.5"
    assert diag["config"]["data"][CONF_MQTT_PASSWORD] == "**REDACTED**"
    assert diag["data"]["dtu"] == "aabbccddeeff"
