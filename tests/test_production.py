"""Unit tests for the production cache (dip smoothing + daily rollover)."""

from __future__ import annotations

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


def test_total_dip_is_clamped_to_cached_max():
    """A lower total reading is replaced by the cached maximum."""
    cache = ProductionCache()
    cache.process(_plant(_mi("a", 1, today=50, total=1000)))

    plant = _plant(_mi("a", 1, today=60, total=800))  # glitch: total dropped
    cache.process(plant)
    assert plant.microinverter_data[0].total_production == 1000
    assert plant.total_production == 1000


def test_today_dip_is_clamped_within_day():
    """A small lower today reading during the day is clamped (treated as a glitch)."""
    cache = ProductionCache()
    cache.process(_plant(_mi("a", 1, today=500, total=1000)))

    plant = _plant(_mi("a", 1, today=480, total=1000))  # glitch
    cache.process(plant)
    assert plant.microinverter_data[0].today_production == 500
    assert plant.today_production == 500


def test_today_preserved_when_a_port_goes_idle():
    """A port going idle (sunset) must not drop the plant total -- no stair-step."""
    cache = ProductionCache()
    cache.process(
        _plant(
            _mi("a", 1, today=4000, total=9000),
            _mi("a", 2, today=5000, total=11000),
        )
    )

    # Port 2 stops (idle) while port 1 keeps producing; total must stay 9000.
    plant = _plant(
        _mi("a", 1, today=4100, total=9100),
        _mi("a", 2, today=0, total=0, status=0),
    )
    cache.process(plant)
    assert plant.today_production == 4100 + 5000  # port 2 retains its cached 5000


def test_daily_rollover_drops_today_in_one_clean_step():
    """When all operating ports roll over to ~0, today drops once to the new value."""
    cache = ProductionCache()
    cache.process(
        _plant(
            _mi("a", 1, today=4000, total=9000),
            _mi("a", 2, today=5000, total=11000),
        )
    )

    # DTU midnight rollover: every operating port resets to ~0 simultaneously.
    plant = _plant(
        _mi("a", 1, today=3, total=9000),
        _mi("a", 2, today=5, total=11000),
    )
    cache.process(plant)
    assert plant.today_production == 8  # 3 + 5, single clean step down from 9000
    # total is a lifetime counter and is unaffected by the daily rollover
    assert plant.total_production == 9000 + 11000


def test_single_port_glitch_to_zero_is_not_a_rollover():
    """One port glitching to ~0 (others unchanged) is smoothed, not treated as reset."""
    cache = ProductionCache()
    cache.process(
        _plant(
            _mi("a", 1, today=4000, total=9000),
            _mi("a", 2, today=5000, total=11000),
        )
    )

    plant = _plant(
        _mi("a", 1, today=0, total=9000),  # hard glitch on port 1 only
        _mi("a", 2, today=5100, total=11100),
    )
    cache.process(plant)
    # Port 1 clamped back to 4000, port 2 advanced to 5100.
    assert plant.microinverter_data[0].today_production == 4000
    assert plant.today_production == 4000 + 5100


def test_rollover_with_one_operating_port():
    """A lone operating port reporting ~0 against a real cached value rolls over."""
    cache = ProductionCache()
    cache.process(_plant(_mi("a", 1, today=4000, total=9000)))

    plant = _plant(_mi("a", 1, today=10, total=9000))
    cache.process(plant)
    assert plant.today_production == 10


def test_no_rollover_on_first_poll():
    """An empty cache (startup) is never mistaken for a rollover."""
    cache = ProductionCache()
    plant = _plant(_mi("a", 1, today=4000, total=9000))
    cache.process(plant)
    assert plant.today_production == 4000


def test_non_operating_port_keeps_cached_total():
    """A non-operating port does not overwrite the cached total with a stale value."""
    cache = ProductionCache()
    cache.process(_plant(_mi("a", 1, today=300, total=1000)))

    plant = _plant(_mi("a", 1, today=0, total=0, status=0))  # stale zeros
    cache.process(plant)
    assert plant.total_production == 1000


def test_aggregates_sum_across_ports():
    """Plant totals are the sum of all cached ports."""
    cache = ProductionCache()
    plant = _plant(
        _mi("a", 1, today=100, total=1000),
        _mi("b", 1, today=200, total=3000),
    )
    cache.process(plant)
    assert plant.today_production == 300
    assert plant.total_production == 4000
