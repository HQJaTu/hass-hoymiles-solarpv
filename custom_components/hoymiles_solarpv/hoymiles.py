"""
Self-contained Hoymiles DTU Modbus TCP client.

This module bundles the low level protocol handling that is specific to
Hoymiles DTU devices (DTU-Pro and similar).  It deliberately avoids any
heavy third party data-modelling dependency and only relies on ``pymodbus``
(which is already shipped with Home Assistant) plus the Python standard
library.

The client is fully synchronous.  Home Assistant code must therefore call
:meth:`HoymilesModbusTCP.get_plant_data` from an executor thread
(``hass.async_add_executor_job``) so the event loop is never blocked.
"""

from __future__ import annotations

import struct
from binascii import hexlify
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusException
from pymodbus.framer import FramerType


class HoymilesModbusError(Exception):
    """Raised when communication with the DTU fails or returns bad data."""


class MicroinverterType(str, Enum):
    """Supported microinverter families."""

    MI = "MI"
    HM = "HM"


@dataclass
class MicroinverterData:
    """Status data for a single microinverter / PV port."""

    data_type: int
    serial_number: str
    port_number: int
    pv_voltage: Decimal
    pv_current: Decimal
    grid_voltage: Decimal
    grid_frequency: Decimal
    pv_power: Decimal
    today_production: int
    total_production: int
    temperature: Decimal
    operating_status: int
    alarm_code: int
    alarm_count: int
    link_status: int


@dataclass
class PlantData:
    """Aggregated status data for the whole plant (one DTU)."""

    dtu: str
    pv_power: Decimal = Decimal(0)
    today_production: int = 0
    total_production: int = 0
    alarm_flag: bool = False
    microinverter_data: list[MicroinverterData] = field(default_factory=list)


# Binary layout of one microinverter record (40 bytes, big endian).
#   B   data_type            H   pv_power (/10)
#   6s  serial number        H   today_production
#   B   port number          I   total_production
#   H   pv_voltage (/10)     h   temperature (signed, /10)
#   H   pv_current (/10|/100) H  operating_status
#   H   grid_voltage (/10)   H   alarm_code
#   H   grid_frequency (/100) H  alarm_count
#                            B   link_status
#                            5s  reserved
_RECORD = struct.Struct(">B6sBHHHHHHIhHHHB7s")
_RECORD_REGISTERS = 20  # 20 modbus registers == 40 bytes

_DTU_SERIAL_ADDRESS = 0x2000
_DTU_SERIAL_REGISTERS = 3
_MICROINVERTER_BASE_ADDRESS = 0x1000
_MAX_MICROINVERTER_COUNT = 100
_NULL_MICROINVERTER = "000000000000"


def _registers_to_bytes(registers: list[int]) -> bytes:
    """Convert a list of 16-bit modbus registers to a big-endian byte string."""
    return struct.pack(f">{len(registers)}H", *registers)


def parse_microinverter_record(
    raw: bytes, microinverter_type: MicroinverterType
) -> MicroinverterData:
    """Parse a single 40-byte microinverter record.

    Arguments:
        raw: the 40 bytes that make up one microinverter record.
        microinverter_type: family of the microinverter (affects current scaling).

    """
    if len(raw) < _RECORD.size:
        raise HoymilesModbusError(
            f"Microinverter record too short: {len(raw)} bytes (expected {_RECORD.size})."
        )
    (
        data_type,
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
        _reserved,
    ) = _RECORD.unpack(raw[: _RECORD.size])

    current_divisor = 100 if microinverter_type == MicroinverterType.HM else 10

    return MicroinverterData(
        data_type=data_type,
        serial_number=hexlify(serial).decode("ascii"),
        port_number=port_number,
        pv_voltage=Decimal(pv_voltage) / 10,
        pv_current=Decimal(pv_current) / current_divisor,
        grid_voltage=Decimal(grid_voltage) / 10,
        grid_frequency=Decimal(grid_frequency) / 100,
        pv_power=Decimal(pv_power) / 10,
        today_production=today_production,
        total_production=total_production,
        temperature=Decimal(temperature) / 10,
        operating_status=operating_status,
        alarm_code=alarm_code,
        alarm_count=alarm_count,
        link_status=link_status,
    )


class HoymilesModbusTCP:
    """Synchronous Modbus TCP client for a Hoymiles DTU.

    The DTU reports an incorrect PDU byte-count in its responses.  This is
    corrected on the fly through the ``trace_packet`` hook of the pymodbus
    client (see :meth:`_fix_received_packet`).
    """

    def __init__(
        self,
        host: str,
        port: int = 502,
        microinverter_type: MicroinverterType = MicroinverterType.MI,
        unit_id: int = 1,
        timeout: float = 3.0,
        retries: int = 3,
    ) -> None:
        """Initialize the client.

        Arguments:
            host: DTU host / IP address.
            port: DTU Modbus TCP port.
            microinverter_type: microinverter family (applies to all inverters).
            unit_id: Modbus unit / device id.
            timeout: per-request timeout in seconds.
            retries: maximum number of retries per request.

        """
        self._host = host
        self._port = port
        self._microinverter_type = MicroinverterType(microinverter_type)
        self._unit_id = unit_id
        self._timeout = timeout
        self._retries = retries

    @staticmethod
    def _fix_received_packet(sending: bool, data: bytes) -> bytes:
        """Correct the PDU byte-count reported by the DTU.

        The DTU sends a wrong byte-count value at index 8 of the Modbus/TCP
        frame.  We recompute it from the actual payload length before the
        frame is handed over to the pymodbus decoder.
        """
        if not sending and len(data) > 9:
            fixed = bytearray(data)
            fixed[8] = len(fixed) - 9
            return bytes(fixed)
        return data

    def _get_client(self) -> ModbusTcpClient:
        return ModbusTcpClient(
            self._host,
            port=self._port,
            framer=FramerType.SOCKET,
            timeout=self._timeout,
            retries=self._retries,
            trace_packet=self._fix_received_packet,
        )

    def _read_registers(self, client: ModbusTcpClient, address: int, count: int) -> list[int]:
        result = client.read_holding_registers(address, count=count, device_id=self._unit_id)
        if result.isError():
            raise HoymilesModbusError(f"Modbus error response for address {hex(address)}: {result}")
        return result.registers

    def _read_dtu_serial(self, client: ModbusTcpClient) -> str:
        registers = self._read_registers(client, _DTU_SERIAL_ADDRESS, _DTU_SERIAL_REGISTERS)
        return hexlify(_registers_to_bytes(registers)).decode("ascii")

    def _read_microinverters(self, client: ModbusTcpClient) -> list[MicroinverterData]:
        data: list[MicroinverterData] = []
        for index in range(_MAX_MICROINVERTER_COUNT):
            address = index * 40 + _MICROINVERTER_BASE_ADDRESS
            registers = self._read_registers(client, address, _RECORD_REGISTERS)
            raw = _registers_to_bytes(registers)
            if index == 0 and len(raw) < _RECORD.size:
                raise HoymilesModbusError("Microinverters not mapped yet.")
            record = parse_microinverter_record(raw, self._microinverter_type)
            if record.serial_number == _NULL_MICROINVERTER:
                break
            data.append(record)
        return data

    def get_dtu_serial(self) -> str:
        """Read and return only the DTU serial number. Blocking call.

        Useful as a lightweight connection test.

        Raises:
            HoymilesModbusError: on any communication or decoding failure.

        """
        try:
            with self._get_client() as client:
                if not client.connected and not client.connect():
                    raise HoymilesModbusError(
                        f"Unable to connect to DTU at {self._host}:{self._port}."
                    )
                return self._read_dtu_serial(client)
        except ModbusException as exc:  # pragma: no cover - depends on hardware
            raise HoymilesModbusError(f"Modbus communication failed: {exc}") from exc
        except OSError as exc:  # pragma: no cover - depends on hardware
            raise HoymilesModbusError(f"Network error talking to DTU: {exc}") from exc

    def get_plant_data(self) -> PlantData:
        """Read and return the full plant status. Blocking call.

        Raises:
            HoymilesModbusError: on any communication or decoding failure.

        """
        try:
            with self._get_client() as client:
                if not client.connected and not client.connect():
                    raise HoymilesModbusError(
                        f"Unable to connect to DTU at {self._host}:{self._port}."
                    )
                dtu_serial = self._read_dtu_serial(client)
                microinverters = self._read_microinverters(client)
        except ModbusException as exc:  # pragma: no cover - depends on hardware
            raise HoymilesModbusError(f"Modbus communication failed: {exc}") from exc
        except OSError as exc:  # pragma: no cover - depends on hardware
            raise HoymilesModbusError(f"Network error talking to DTU: {exc}") from exc

        plant = PlantData(dtu=dtu_serial, microinverter_data=microinverters)
        for microinverter in microinverters:
            if microinverter.link_status:
                plant.pv_power += microinverter.pv_power
                plant.today_production += microinverter.today_production
                plant.total_production += microinverter.total_production
                if microinverter.alarm_code:
                    plant.alarm_flag = True
        return plant
