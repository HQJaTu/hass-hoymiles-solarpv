"""Unit tests for the self-contained Hoymiles Modbus client logic."""

from __future__ import annotations

import struct
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from custom_components.hoymiles_solarpv.hoymiles import (
    HoymilesModbusError,
    HoymilesModbusTCP,
    MicroinverterType,
    _registers_to_bytes,
    parse_microinverter_record,
)

from .conftest import build_record


def test_registers_to_bytes_roundtrip():
    """Registers are packed big-endian."""
    assert _registers_to_bytes([0x1122, 0x3344]) == b"\x11\x22\x33\x44"


def test_parse_microinverter_mi_scaling():
    """MI series scales current by 10 and applies documented decimal precision."""
    record = parse_microinverter_record(build_record(), MicroinverterType.MI)
    assert record.serial_number == "112233445566"
    assert record.port_number == 1
    assert record.pv_voltage == Decimal("245.0")
    assert record.pv_current == Decimal("5.0")  # 50 / 10
    assert record.grid_voltage == Decimal("230.0")
    assert record.grid_frequency == Decimal("50")  # 5000 / 100
    assert record.pv_power == Decimal("150.0")
    assert record.today_production == 120
    assert record.total_production == 654321
    assert record.temperature == Decimal("35.5")
    assert record.operating_status == 3
    assert record.link_status == 1


def test_parse_microinverter_hm_current_scaling():
    """HM series scales current by 100."""
    record = parse_microinverter_record(build_record(pv_current=50), MicroinverterType.HM)
    assert record.pv_current == Decimal("0.5")  # 50 / 100


def test_parse_negative_temperature():
    """Temperature is a signed value."""
    record = parse_microinverter_record(build_record(temperature=-105), MicroinverterType.MI)
    assert record.temperature == Decimal("-10.5")


def test_parse_short_record_raises():
    """A truncated record raises a domain error."""
    with pytest.raises(HoymilesModbusError):
        parse_microinverter_record(b"\x00\x01", MicroinverterType.MI)


def test_fix_received_packet_corrects_byte_count():
    """Received packets get their PDU byte-count recomputed."""
    # 7 header bytes + func(1) + bad bytecount(1) + 4 data bytes => index 8 should become 4
    packet = bytes([0, 1, 0, 0, 0, 6, 1, 3, 99, 10, 20, 30, 40])
    fixed = HoymilesModbusTCP._fix_received_packet(False, packet)
    assert fixed[8] == len(packet) - 9 == 4


def test_fix_sent_packet_unchanged():
    """Outgoing packets are not modified."""
    packet = bytes([0, 1, 0, 0, 0, 6, 1, 3, 99, 10, 20, 30, 40])
    assert HoymilesModbusTCP._fix_received_packet(True, packet) is packet


def test_fix_short_packet_unchanged():
    """Packets too short to contain a PDU byte-count are left alone."""
    packet = bytes([0, 1, 0, 0, 0, 6, 1, 3])
    assert HoymilesModbusTCP._fix_received_packet(False, packet) is packet


def _fake_client_context(registers_map):
    """Build a fake pymodbus client whose context manager returns canned reads."""
    client = MagicMock()
    client.connected = True

    def read_holding_registers(address, count, device_id):  # noqa: ARG001
        response = MagicMock()
        response.isError.return_value = False
        response.registers = registers_map[address]
        return response

    client.read_holding_registers.side_effect = read_holding_registers
    ctx = MagicMock()
    ctx.__enter__.return_value = client
    ctx.__exit__.return_value = False
    return ctx


def test_get_plant_data_aggregates_linked_inverters():
    """Plant aggregates power/energy only for linked microinverters with alarms flagged."""
    dtu_registers = list(struct.unpack(">3H", b"\xaa\xbb\xcc\xdd\xee\xff"))

    linked = build_record(serial=b"\x00\x00\x00\x00\x00\x01", pv_power=1000, today_production=10,
                          total_production=100, alarm_code=7, link_status=1)
    unlinked = build_record(serial=b"\x00\x00\x00\x00\x00\x02", pv_power=9999,
                            today_production=999, total_production=999, link_status=0)
    null = build_record(serial=b"\x00\x00\x00\x00\x00\x00")

    registers_map = {
        0x2000: dtu_registers,
        0x1000: list(struct.unpack(">20H", linked)),
        0x1028: list(struct.unpack(">20H", unlinked)),
        0x1050: list(struct.unpack(">20H", null)),
    }

    client = HoymilesModbusTCP("1.2.3.4", microinverter_type=MicroinverterType.MI)
    with patch.object(client, "_get_client", return_value=_fake_client_context(registers_map)):
        plant = client.get_plant_data()

    assert plant.dtu == "aabbccddeeff"
    assert len(plant.microinverter_data) == 2  # null terminator stops iteration
    assert plant.pv_power == Decimal("100.0")  # only linked inverter (1000/10)
    assert plant.today_production == 10
    assert plant.total_production == 100
    assert plant.alarm_flag is True


def test_get_plant_data_wraps_errors():
    """An error response is converted into a HoymilesModbusError."""
    client = HoymilesModbusTCP("1.2.3.4")

    bad_client = MagicMock()
    bad_client.connected = True
    error_response = MagicMock()
    error_response.isError.return_value = True
    bad_client.read_holding_registers.return_value = error_response
    ctx = MagicMock()
    ctx.__enter__.return_value = bad_client
    ctx.__exit__.return_value = False

    with patch.object(client, "_get_client", return_value=ctx):
        with pytest.raises(HoymilesModbusError):
            client.get_plant_data()
