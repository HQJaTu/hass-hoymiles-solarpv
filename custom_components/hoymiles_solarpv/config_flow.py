"""
Config flow for the Hoymiles SolarPV integration.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback

from .const import (
    CONF_MICROINVERTER_TYPE,
    CONF_MQTT_ENABLED,
    CONF_MQTT_HOST,
    CONF_MQTT_PASSWORD,
    CONF_MQTT_PORT,
    CONF_MQTT_TOPIC,
    CONF_MQTT_USERNAME,
    CONF_UNIT_ID,
    DEFAULT_MICROINVERTER_TYPE,
    DEFAULT_MQTT_PORT,
    DEFAULT_MQTT_TOPIC,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_UNIT_ID,
    DOMAIN,
    MICROINVERTER_TYPES,
)
from .hoymiles import HoymilesModbusError, HoymilesModbusTCP, MicroinverterType

_LOGGER = logging.getLogger(__name__)

CONF_SCAN_INTERVAL = "scan_interval"

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=65535)
        ),
        vol.Required(CONF_MICROINVERTER_TYPE, default=DEFAULT_MICROINVERTER_TYPE): vol.In(
            MICROINVERTER_TYPES
        ),
        vol.Required(CONF_UNIT_ID, default=DEFAULT_UNIT_ID): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=255)
        ),
        vol.Required(CONF_MQTT_ENABLED, default=False): bool,
        vol.Optional(CONF_MQTT_HOST): str,
        vol.Optional(CONF_MQTT_PORT, default=DEFAULT_MQTT_PORT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=65535)
        ),
        vol.Optional(CONF_MQTT_USERNAME): str,
        vol.Optional(CONF_MQTT_PASSWORD): str,
        vol.Optional(CONF_MQTT_TOPIC, default=DEFAULT_MQTT_TOPIC): str,
    }
)


async def _validate_connection(hass, data: dict[str, Any]) -> str:
    """
    Validate the DTU connection and return its serial number.
    :param hass: Home Assistant core.
    :param data: A data object that contains information about the connection.
    :return: The serial number.
    """
    client = HoymilesModbusTCP(
        host=data[CONF_HOST],
        port=data[CONF_PORT],
        microinverter_type=MicroinverterType(data[CONF_MICROINVERTER_TYPE]),
        unit_id=data[CONF_UNIT_ID],
    )

    return await hass.async_add_executor_job(client.get_dtu_serial)


class HoymilesConfigFlow(ConfigFlow, domain=DOMAIN):
    """
    Handle a config flow for Hoymiles SolarPV.
    """

    VERSION = 1

    _validated_serial: str = ""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """
        Handle the initial step.
        :param user_input: A user input data that contains a dictionary that represents
        :return ConfigFlowResult
        """
        errors = await self._validate_input(user_input)
        if user_input is not None and not errors:
            serial = self._validated_serial
            await self.async_set_unique_id(serial)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=f"Hoymiles DTU {serial}", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(STEP_USER_DATA_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of an existing entry (host/port/MQTT/etc.)."""
        reconfigure_entry = self._get_reconfigure_entry()

        errors = await self._validate_input(user_input)
        if user_input is not None and not errors:
            # Make sure the (re)entered connection still points at the same DTU.
            await self.async_set_unique_id(self._validated_serial)
            self._abort_if_unique_id_mismatch(reason="wrong_dtu")
            return self.async_update_reload_and_abort(reconfigure_entry, data=user_input)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, user_input or dict(reconfigure_entry.data)
            ),
            errors=errors,
        )

    async def _validate_input(self, user_input: dict[str, Any] | None) -> dict[str, str]:
        """Validate user input, caching the discovered serial. Returns form errors."""
        self._validated_serial = ""
        if user_input is None:
            return {}
        if user_input.get(CONF_MQTT_ENABLED) and not user_input.get(CONF_MQTT_HOST):
            return {CONF_MQTT_HOST: "mqtt_host_required"}
        try:
            self._validated_serial = await _validate_connection(self.hass, user_input)
        except HoymilesModbusError:
            return {"base": "cannot_connect"}
        except Exception:  # noqa: BLE001 - defensive: report as unknown
            _LOGGER.exception("Unexpected error validating Hoymiles DTU connection")
            return {"base": "unknown"}
        return {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> HoymilesOptionsFlow:
        """Return the options flow handler."""
        return HoymilesOptionsFlow()


class HoymilesOptionsFlow(OptionsFlow):
    """
    Handle Hoymiles SolarPV options (polling interval).
    """

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """
        Manage the options.
        :param user_input: A user input data that contains a dictionary that represents
        :return ConfigFlowResult
        """
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        schema = vol.Schema(
            {
                vol.Required(CONF_SCAN_INTERVAL, default=current): vol.All(
                    vol.Coerce(int), vol.Range(min=5, max=3600)
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
