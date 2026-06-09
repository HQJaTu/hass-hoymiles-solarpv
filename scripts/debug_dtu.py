#!/usr/bin/env python3

# vim: autoindent tabstop=4 shiftwidth=4 expandtab softtabstop=4 filetype=python

"""
Run and debug the Hoymiles SolarPV integration logic outside Home Assistant.

This talks to a real DTU using the integration's own Modbus client and prints the
decoded plant data, so you can verify connectivity and step through the parsing
code without a running Home Assistant instance.

The core path needs only ``pymodbus`` installed. Optional features pull in more:

  * ``--cache``  applies the production smoothing / daily-reset logic (pymodbus only).
  * ``--mqtt-*`` re-publishes via the real MQTT publisher (requires ``homeassistant``
    to be importable, because the entity descriptions live in HA modules).
  * ``--selftest`` runs entirely offline (no DTU): it parses a synthetic record and
    simulates a day of polling through the production cache, incl. the 22:00 reset.

Options may also be read from a TOML config file via ``--config`` (CLI flags take
precedence). See ``scripts/debug_dtu.example.toml`` for the format.

Examples
--------
  # Read a DTU once and print everything
  python scripts/debug_dtu.py --host 192.168.1.50

  # Poll every 30s, applying production smoothing, with pymodbus debug logging
  python scripts/debug_dtu.py --host 192.168.1.50 --interval 30 --cache --debug

  # Read all settings from a config file
  python scripts/debug_dtu.py --config scripts/debug_dtu.example.toml

  # Offline logic check, no hardware needed
  python scripts/debug_dtu.py --selftest
"""

from __future__ import annotations

import importlib.util
import logging
import struct
import sys
import time
import types
from datetime import datetime
from pathlib import Path

import configargparse

# --- load integration modules without triggering the package __init__ (which
# would import Home Assistant). A synthetic package with __path__ lets the
# modules' relative imports (``from .hoymiles import ...``) resolve normally.

_PKG = "hoymiles_solarpv_local"
_INTEGRATION_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "hoymiles_solarpv"
_SAMPLE_RECORD = struct.Struct(">B6sBHHHHHHIhHHHB7s")

_LOGGER = logging.getLogger("hoymiles_debug")


def _load(module: str) -> types.ModuleType:
    """
    Load ``<integration>/<module>.py`` as a submodule of a synthetic package.
    :param module: ``<integration>/<module>.py``
    :return: ``<integration>/<module>.py``
    """
    if _PKG not in sys.modules:
        pkg = types.ModuleType(_PKG)
        pkg.__path__ = [str(_INTEGRATION_DIR)]  # type: ignore[attr-defined]
        sys.modules[_PKG] = pkg
    full_name = f"{_PKG}.{module}"
    if full_name in sys.modules:
        return sys.modules[full_name]
    spec = importlib.util.spec_from_file_location(full_name, _INTEGRATION_DIR / f"{module}.py")
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = loaded
    spec.loader.exec_module(loaded)

    return loaded


def _print_plant(plant) -> None:
    """
    Helper: Pretty print plant information
    :param plant:
    """
    print(f"\nDTU {plant.dtu}")
    print(
        f"  plant: power={float(plant.pv_power):.1f} W  "
        f"today={plant.today_production} Wh  "
        f"total={plant.total_production} Wh  "
        f"alarm={plant.alarm_flag}"
    )
    if not plant.microinverter_data:
        print("  (no microinverters reported)")
        return
    header = (
        f"  {'serial':<14}{'port':>4}{'stat':>5}{'link':>5}"
        f"{'pv_V':>8}{'pv_A':>7}{'pv_W':>8}{'today':>7}{'total':>9}{'°C':>7}"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))
    for mi in plant.microinverter_data:
        print(
            f"  {mi.serial_number:<14}{mi.port_number:>4}{mi.operating_status:>5}"
            f"{mi.link_status:>5}{float(mi.pv_voltage):>8.1f}{float(mi.pv_current):>7.2f}"
            f"{float(mi.pv_power):>8.1f}{mi.today_production:>7}{mi.total_production:>9}"
            f"{float(mi.temperature):>7.1f}"
        )


def _run_live(args: configargparse.Namespace) -> int:
    """
    Run a live polling session
    :param args: parsed arguments
    :return: exit code
    """
    hoymiles = _load("hoymiles")
    client = hoymiles.HoymilesModbusTCP(
        host=args.host,
        port=args.port,
        microinverter_type=hoymiles.MicroinverterType(args.type),
        unit_id=args.unit_id,
        timeout=args.timeout,
        retries=args.retries,
    )

    cache = _load("production").ProductionCache() if args.cache else None
    publisher = _build_publisher(args)

    def one_poll() -> None:
        try:
            plant = client.get_plant_data()
        except hoymiles.HoymilesModbusError as err:
            _LOGGER.error("Failed to read DTU: %s", err)
            return
        if cache is not None:
            cache.process(plant, datetime.now().astimezone())
        _print_plant(plant)
        if publisher is not None:
            try:
                publisher.publish_plant_data(plant)
                _LOGGER.info("Published to MQTT broker %s:%s", args.mqtt_host, args.mqtt_port)
            except Exception as err:  # noqa: BLE001 - debugging aid
                _LOGGER.error("MQTT publish failed: %s", err)

    try:
        one_poll()
        while args.interval:
            time.sleep(args.interval)
            one_poll()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        if publisher is not None:
            publisher.close()

    return 0


def _build_publisher(args: configargparse.Namespace):
    """
    Build MQTT publisher
    :param args: parsed arguments
    :return: object of HoymilesMqttPublisher
    """
    if not args.mqtt_host:
        return None
    try:
        mqtt = _load("mqtt")
    except ImportError as err:
        _LOGGER.error(
            "MQTT publishing needs Home Assistant importable (%s). "
            "Install it with: pip install -r requirements_test.txt",
            err,
        )
        raise SystemExit(2) from err

    return mqtt.HoymilesMqttPublisher(
        host=args.mqtt_host,
        port=args.mqtt_port,
        username=args.mqtt_username,
        password=args.mqtt_password,
        topic_base=args.mqtt_topic,
    )


def _fake_record(today: int, total: int, status: int = 3) -> bytes:
    """
    offline self-test (no DTU)
    :param today:
    :param total:
    :param status:
    :return:
    """
    return _SAMPLE_RECORD.pack(
        1,
        b"\x11\x22\x33\x44\x55\x66",
        1,
        2450,
        50,
        2300,
        5000,
        1500,
        today,
        total,
        355,
        status,
        0,
        0,
        1,
        b"\x00" * 7,
    )


def _run_selftest() -> int:
    """
    self-test
    :return:
    """
    hoymiles = _load("hoymiles")
    production = _load("production")

    print("== Parsing a synthetic microinverter record ==")
    record = hoymiles.parse_microinverter_record(
        _fake_record(today=300, total=1000), hoymiles.MicroinverterType.MI
    )
    print(
        f"  serial={record.serial_number} pv_voltage={record.pv_voltage} "
        f"grid_freq={record.grid_frequency} today={record.today_production}"
    )

    print("\n== Simulating a day through the production cache ==")
    cache = production.ProductionCache()
    timeline = [
        (12, 300, 1000, 3, "midday"),
        (14, 290, 1000, 3, "dip -> clamped"),
        (20, 540, 1300, 3, "evening peak"),
        (22, 5, 1300, 3, "22:00 DTU reset"),
        (23, 12, 1320, 3, "after reset"),
    ]
    for hour, today, total, status, note in timeline:
        plant = hoymiles.PlantData(
            dtu="aabbccddeeff",
            microinverter_data=[
                hoymiles.parse_microinverter_record(
                    _fake_record(today, total, status), hoymiles.MicroinverterType.MI
                )
            ],
        )
        cache.process(plant, datetime(2026, 6, 9, hour, 0).astimezone())
        print(
            f"  {hour:02d}:00  raw_today={today:<5} -> cached_today={plant.today_production:<5} "
            f"total={plant.total_production:<6} ({note})"
        )
    print("\nSelf-test complete.")
    return 0


def _parse_args(argv: list[str]) -> configargparse.Namespace:
    """
    Argument parser

    Values may also be supplied through a TOML config file (``--config``) under a
    ``[debug_dtu]`` table, using the long option name as the key (dashes kept,
    e.g. ``unit-id``). Precedence is: command line > config file > defaults.

    :param argv: list of CLI arguments to parse
    :return: parsed arguments in namespace
    """
    parser = configargparse.ArgParser(
        description="Debug the Hoymiles SolarPV integration locally.",
        config_file_parser_class=configargparse.TomlConfigParser(["debug_dtu"]),
    )
    parser.add_argument("-c", "--config", is_config_file=True, help="Path to a TOML config file")
    parser.add_argument("--host", help="DTU host / IP address")
    parser.add_argument("--port", type=int, default=502, help="DTU Modbus TCP port")
    parser.add_argument("--type", choices=["MI", "HM"], default="MI", help="Microinverter family")
    parser.add_argument("--unit-id", type=int, default=1, help="Modbus unit/device ID")
    parser.add_argument("--timeout", type=float, default=3.0, help="Per-request timeout (s)")
    parser.add_argument("--retries", type=int, default=3, help="Max retries per request")
    parser.add_argument("--interval", type=int, default=0, help="Poll every N seconds (0 = once)")
    parser.add_argument("--cache", action="store_true", help="Apply production smoothing/reset")
    parser.add_argument("--mqtt-host", help="Re-publish to this MQTT broker (needs homeassistant)")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument("--mqtt-username")
    parser.add_argument("--mqtt-password")
    parser.add_argument("--mqtt-topic", default="homeassistant/hoymiles_solarpv")
    parser.add_argument("--debug", action="store_true", help="Enable pymodbus DEBUG logging")
    parser.add_argument("--selftest", action="store_true", help="Run offline logic check (no DTU)")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    """
    Console entry point
    :param argv: list of CLI arguments to parse
    :return: exit code
    """
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    if not args.debug:
        logging.getLogger("pymodbus").setLevel(logging.WARNING)

    if args.selftest:
        return _run_selftest()
    if not args.host:
        _LOGGER.error("Provide --host (or use --selftest for an offline check).")
        return 2

    return _run_live(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
