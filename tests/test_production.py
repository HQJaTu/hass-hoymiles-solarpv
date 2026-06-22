"""Unit tests for the production cache (dip smoothing + daily reset)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from custom_components.hoymiles_solarpv.hoymiles import MicroinverterData, PlantData
from custom_components.hoymiles_solarpv.production import RESET_HOUR, ProductionCache


def _mi(serial: str, port: int, today: int, total: int, status: int = 1) -> MicroinverterData:
    """Build a microinverter record with only the production-relevant fields set."""
    return MicroinverterData(
        data_type=1,
        serial_number=serial,
        port_number=port,
        pv_voltage=Decimal(0),
        pv_current=Decimal(0),
        grid_voltage=Decimal(0),
        grid_frequency=Decimal(0),
        pv_power=Decimal(0),
        today_production=today,
        total_production=total,
        temperature=Decimal(0),
        operating_status=status,
        alarm_code=0,
        alarm_count=0,
        link_status=1,
    )


def _plant(*microinverters: MicroinverterData) -> PlantData:
    return PlantData(dtu="aabbccddeeff", microinverter_data=list(microinverters))


def _at(hour: int, day: int = 8) -> datetime:
    return datetime(2026, 6, day, hour, 0, tzinfo=timezone.utc)


def test_total_dip_is_clamped_to_cached_max():
    """A lower total reading is replaced by the cached maximum."""
    cache = ProductionCache()

    plant = _plant(_mi("a", 1, today=50, total=1000))
    cache.process(plant, _at(12))
    assert plant.total_production == 1000

    plant = _plant(_mi("a", 1, today=60, total=800))  # glitch: total dropped
    cache.process(plant, _at(12))
    assert plant.microinverter_data[0].total_production == 1000
    assert plant.total_production == 1000


def test_today_dip_is_clamped_within_day():
    """A lower today reading during the day is clamped to the cached maximum."""
    cache = ProductionCache()
    cache.process(_plant(_mi("a", 1, today=500, total=1000)), _at(12))

    plant = _plant(_mi("a", 1, today=480, total=1000))  # glitch
    cache.process(plant, _at(13))
    assert plant.microinverter_data[0].today_production == 500
    assert plant.today_production == 500


def test_today_preserved_in_evening_when_inverters_idle():
    """Regression: idle inverters in the evening must not zero today early.

    The DTU resets its counter at RESET_HOUR (23:00), not at sundown. If panels
    stop producing at, say, 22:00, the day's accumulated total must remain until
    the DTU itself rolls over -- otherwise only a fraction is published.
    """
    cache = ProductionCache()
    cache.process(_plant(_mi("a", 1, today=4800, total=10000)), _at(15))

    # Evening, before the reset hour, no operating ports (sun down).
    plant = _plant(_mi("a", 1, today=0, total=10000, status=0))
    cache.process(plant, _at(22))
    assert plant.today_production == 4800  # preserved, NOT a fraction


def test_no_reset_before_reset_hour():
    """A dip before the reset hour is treated as a glitch, not a reset."""
    cache = ProductionCache()
    cache.process(_plant(_mi("a", 1, today=500, total=1000)), _at(12))

    plant = _plant(_mi("a", 1, today=5, total=1000))
    cache.process(plant, _at(14))
    assert plant.today_production == 500  # clamped, no reset


def test_reset_hour_follows_dtu_counter_down():
    """During the reset hour the today cache follows the DTU's reset value."""
    cache = ProductionCache()
    cache.process(_plant(_mi("a", 1, today=4800, total=10000)), _at(15))

    # At 23:00 the DTU has rolled its today counter over; a little new production.
    plant = _plant(_mi("a", 1, today=20, total=10000))
    cache.process(plant, _at(RESET_HOUR))
    assert plant.today_production == 20
    assert plant.microinverter_data[0].today_production == 20


def test_reset_hour_with_no_production_zeroes_today():
    """During the reset hour with nothing producing, today drops to zero."""
    cache = ProductionCache()
    cache.process(_plant(_mi("a", 1, today=4800, total=10000)), _at(15))

    plant = _plant(_mi("a", 1, today=0, total=10000, status=0))
    cache.process(plant, _at(RESET_HOUR))
    assert plant.today_production == 0
    assert plant.total_production == 10000  # total is never cleared


def test_today_accumulates_again_after_reset_hour():
    """After the reset hour, the next day's production accumulates normally."""
    cache = ProductionCache()
    cache.process(_plant(_mi("a", 1, today=4800, total=10000)), _at(15, day=8))
    cache.process(_plant(_mi("a", 1, today=30, total=10000)), _at(RESET_HOUR, day=8))

    plant = _plant(_mi("a", 1, today=1200, total=11200))
    cache.process(plant, _at(8, day=9))
    assert plant.today_production == 1200


def test_non_operating_port_keeps_cached_total():
    """A non-operating port does not overwrite the cached total with a stale value."""
    cache = ProductionCache()
    cache.process(_plant(_mi("a", 1, today=300, total=1000)), _at(12))

    plant = _plant(_mi("a", 1, today=0, total=0, status=0))  # stale zeros
    cache.process(plant, _at(13))
    assert plant.total_production == 1000


def test_idle_port_still_counted_in_plant_sum():
    """A port that goes idle keeps contributing its cached value to the plant sum."""
    cache = ProductionCache()
    cache.process(
        _plant(
            _mi("a", 1, today=1000, total=5000),
            _mi("a", 2, today=1500, total=6000),
        ),
        _at(12),
    )

    # Port 2 goes idle; port 1 keeps producing.
    plant = _plant(
        _mi("a", 1, today=1100, total=5100),
        _mi("a", 2, today=0, total=0, status=0),
    )
    cache.process(plant, _at(13))
    assert plant.today_production == 1100 + 1500  # port 2 retains its cached 1500
    assert plant.total_production == 5100 + 6000


def test_aggregates_sum_across_ports():
    """Plant totals are the sum of all cached ports."""
    cache = ProductionCache()
    plant = _plant(
        _mi("a", 1, today=100, total=1000),
        _mi("b", 1, today=200, total=3000),
    )
    cache.process(plant, _at(12))
    assert plant.today_production == 300
    assert plant.total_production == 4000
