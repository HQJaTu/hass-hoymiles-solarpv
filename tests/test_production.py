"""Unit tests for the production cache (dip smoothing + daily reset)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from custom_components.hoymiles_solarpv.hoymiles import MicroinverterData, PlantData
from custom_components.hoymiles_solarpv.production import ProductionCache


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


def test_daily_reset_at_22_clears_today():
    """When today drops for all ports at the reset hour, the cache resets to the new value."""
    cache = ProductionCache()
    cache.process(_plant(_mi("a", 1, today=500, total=1000)), _at(20))

    plant = _plant(_mi("a", 1, today=4, total=1000))  # DTU rolled over at 22:00
    cache.process(plant, _at(22))
    assert plant.today_production == 4
    assert plant.microinverter_data[0].today_production == 4


def test_reset_happens_only_once_per_day():
    """After the reset, a further dip the same day is clamped, not reset again."""
    cache = ProductionCache()
    cache.process(_plant(_mi("a", 1, today=500, total=1000)), _at(20))
    cache.process(_plant(_mi("a", 1, today=10, total=1000)), _at(22))  # reset -> today=10

    plant = _plant(_mi("a", 1, today=3, total=1000))  # later dip, same day
    cache.process(plant, _at(22))
    assert plant.today_production == 10  # clamped to post-reset max, no second reset


def test_no_reset_before_reset_hour():
    """An all-ports drop before 22:00 is treated as a glitch, not a reset."""
    cache = ProductionCache()
    cache.process(_plant(_mi("a", 1, today=500, total=1000)), _at(12))

    plant = _plant(_mi("a", 1, today=5, total=1000))
    cache.process(plant, _at(14))
    assert plant.today_production == 500  # clamped, no reset


def test_no_production_after_reset_hour_clears_today():
    """No operating ports past the reset hour clears the stale today total once."""
    cache = ProductionCache()
    cache.process(_plant(_mi("a", 1, today=500, total=1000)), _at(20))

    # After sundown the port is no longer operating; past 22:00 -> reset.
    plant = _plant(_mi("a", 1, today=0, total=1000, status=0))
    cache.process(plant, _at(23))
    assert plant.today_production == 0


def test_non_operating_port_keeps_cached_total():
    """A non-operating port does not overwrite the cached total with a stale value."""
    cache = ProductionCache()
    cache.process(_plant(_mi("a", 1, today=300, total=1000)), _at(12))

    plant = _plant(_mi("a", 1, today=0, total=0, status=0))  # stale zeros
    cache.process(plant, _at(13))
    assert plant.total_production == 1000


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


def test_new_day_allows_reset_again():
    """The reset can fire again on a subsequent day."""
    cache = ProductionCache()
    cache.process(_plant(_mi("a", 1, today=500, total=1000)), _at(20, day=8))
    cache.process(_plant(_mi("a", 1, today=8, total=1000)), _at(22, day=8))  # reset day 8

    # Next day builds up then resets again.
    cache.process(_plant(_mi("a", 1, today=400, total=1500)), _at(12, day=9))
    plant = _plant(_mi("a", 1, today=6, total=1500))
    cache.process(plant, _at(22, day=9))
    assert plant.today_production == 6
