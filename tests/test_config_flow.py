"""Tests for the Hoymiles SolarPV config and options flow."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hoymiles_solarpv.const import (
    CONF_MICROINVERTER_TYPE,
    CONF_MQTT_ENABLED,
    CONF_UNIT_ID,
    DOMAIN,
)
from custom_components.hoymiles_solarpv.hoymiles import HoymilesModbusError

_BASE_INPUT = {
    CONF_HOST: "192.168.1.50",
    CONF_PORT: 502,
    CONF_MICROINVERTER_TYPE: "MI",
    CONF_UNIT_ID: 1,
    CONF_MQTT_ENABLED: False,
}


async def test_user_flow_success(hass: HomeAssistant) -> None:
    """A valid connection creates an entry keyed by the DTU serial."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM

    with (
        patch(
            "custom_components.hoymiles_solarpv.config_flow.HoymilesModbusTCP.get_dtu_serial",
            return_value="aabbccddeeff",
        ),
        patch(
            "custom_components.hoymiles_solarpv.async_setup_entry",
            return_value=True,
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], dict(_BASE_INPUT)
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Hoymiles DTU aabbccddeeff"
    assert result["result"].unique_id == "aabbccddeeff"
    assert result["data"][CONF_HOST] == "192.168.1.50"


async def test_user_flow_cannot_connect(hass: HomeAssistant) -> None:
    """A failed connection shows the cannot_connect error."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    with patch(
        "custom_components.hoymiles_solarpv.config_flow.HoymilesModbusTCP.get_dtu_serial",
        side_effect=HoymilesModbusError("boom"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], dict(_BASE_INPUT)
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_mqtt_host_required(hass: HomeAssistant) -> None:
    """Enabling MQTT without a host raises a validation error."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    user_input = dict(_BASE_INPUT)
    user_input[CONF_MQTT_ENABLED] = True
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"mqtt_host": "mqtt_host_required"}


async def test_user_flow_already_configured(hass: HomeAssistant) -> None:
    """A DTU that is already configured aborts the flow."""
    MockConfigEntry(domain=DOMAIN, unique_id="aabbccddeeff", data=dict(_BASE_INPUT)).add_to_hass(
        hass
    )

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    with patch(
        "custom_components.hoymiles_solarpv.config_flow.HoymilesModbusTCP.get_dtu_serial",
        return_value="aabbccddeeff",
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], dict(_BASE_INPUT)
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow(hass: HomeAssistant) -> None:
    """The options flow stores the polling interval."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id="aabbccddeeff", data=dict(_BASE_INPUT))
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"scan_interval": 30}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"scan_interval": 30}
