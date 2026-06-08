"""Common fixtures for Hoymiles SolarPV tests."""

from __future__ import annotations

import struct

import pytest

from custom_components.hoymiles_solarpv.hoymiles import (
    MicroinverterData,
    MicroinverterType,
    PlantData,
    parse_microinverter_record,
)

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading of custom integrations in all tests."""
    yield


def build_record(
    *,
    serial: bytes = b"\x11\x22\x33\x44\x55\x66",
    port_number: int = 1,
    pv_voltage: int = 2450,
    pv_current: int = 50,
    grid_voltage: int = 2300,
    grid_frequency: int = 5000,
    pv_power: int = 1500,
    today_production: int = 120,
    total_production: int = 654321,
    temperature: int = 355,
    operating_status: int = 3,
    alarm_code: int = 0,
    alarm_count: int = 0,
    link_status: int = 1,
) -> bytes:
    """Build a raw 40-byte microinverter record for testing."""
    return struct.pack(
        ">B6sBHHHHHHIhHHHB7s",
        0x01,
        serial,
        port_number,
        pv_voltage,
        pv_current,
        grid_voltage,
        grid_frequency,
        pv_power,
        today_production,
        total_production,
        temperature,
        operating_status,
        alarm_code,
        alarm_count,
        link_status,
        b"\x00\x00\x00\x00\x00\x00\x00",
    )


@pytest.fixture
def sample_microinverter() -> MicroinverterData:
    """Return a parsed sample microinverter record."""
    return parse_microinverter_record(build_record(), MicroinverterType.MI)


@pytest.fixture
def sample_plant_data(sample_microinverter: MicroinverterData) -> PlantData:
    """Return a sample plant with a single microinverter, aggregated."""
    plant = PlantData(dtu="aabbccddeeff", microinverter_data=[sample_microinverter])
    mi = sample_microinverter
    plant.pv_power = mi.pv_power
    plant.today_production = mi.today_production
    plant.total_production = mi.total_production
    plant.alarm_flag = bool(mi.alarm_code)
    return plant
