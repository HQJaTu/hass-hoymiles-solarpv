"""Production smoothing and daily-reset handling for Hoymiles DTU data.

Hoymiles DTUs have two quirks that this module compensates for:

1. They occasionally report a *lower* ``today``/``total`` production value than a
   previous reading (transient glitch). Left untouched this looks like a counter
   reset to Home Assistant's ``total_increasing`` statistics and produces false
   spikes on the Energy dashboard. We therefore keep a monotonic (max) cache per
   microinverter port and clamp dips back up to the cached value.

2. They reset the *today* production counter at ~22:00 local time (not midnight).
   The monotonic cache above would otherwise suppress this legitimate drop, so we
   explicitly detect the daily reset around that hour and clear the today cache
   exactly once per day, letting the counter legitimately fall back to zero.

The cache lives only in memory; it is rebuilt from live DTU values after a Home
Assistant restart, which also means a stuck value self-heals on restart.
"""

from __future__ import annotations

import logging
from datetime import date, datetime

from .hoymiles import PlantData

_LOGGER = logging.getLogger(__name__)

# Hour of the day (local time) around which Hoymiles DTUs reset the today counter.
RESET_HOUR = 22

type _PortKey = tuple[str, int]


class ProductionCache:
    """Smooth production dips and handle the ~22:00 daily reset.

    A single instance is kept per config entry and fed every poll via
    :meth:`process`, which mutates the given :class:`PlantData` in place.
    """

    def __init__(self, reset_hour: int = RESET_HOUR) -> None:
        """Initialize an empty cache."""
        self._reset_hour = reset_hour
        self._today: dict[_PortKey, int] = {}
        self._total: dict[_PortKey, int] = {}
        self._last_reset_date: date | None = None

    def process(self, plant_data: PlantData, now: datetime) -> None:
        """Clamp production dips, handle the daily reset and recompute totals.

        Arguments:
            plant_data: freshly polled plant data; mutated in place.
            now: current local (timezone-aware) time, used for reset detection.

        """
        today_candidates = self._update_total_and_collect_today(plant_data)
        self._handle_daily_reset(today_candidates, now)
        self._update_today(plant_data)

        plant_data.today_production = sum(self._today.values())
        plant_data.total_production = sum(self._total.values())

    def _update_total_and_collect_today(self, plant_data: PlantData) -> dict[_PortKey, int]:
        """Clamp total production and return today candidates for operating ports."""
        today_candidates: dict[_PortKey, int] = {}
        for microinverter in plant_data.microinverter_data:
            if microinverter.operating_status <= 0:
                # A non-operating port reports stale/zero values; skip it so the
                # last good cached value is retained.
                continue
            key = (microinverter.serial_number, microinverter.port_number)

            cached_total = self._total.get(key, 0)
            if microinverter.total_production >= cached_total:
                self._total[key] = microinverter.total_production
            else:
                _LOGGER.warning(
                    "Total production for %s port %d dropped (%d < cached %d); using cached value",
                    microinverter.serial_number,
                    microinverter.port_number,
                    microinverter.total_production,
                    cached_total,
                )
                microinverter.total_production = cached_total

            today_candidates[key] = microinverter.today_production
        return today_candidates

    def _handle_daily_reset(self, today_candidates: dict[_PortKey, int], now: datetime) -> None:
        """Clear the today cache once per day around the DTU reset hour."""
        if self._already_reset_today(now) or not self._in_reset_window(now):
            return

        if not today_candidates:
            # No operating ports (e.g. after sundown). If we are past the reset
            # hour and have not reset yet today, do it now.
            self._clear_today(now)
            return

        # All operating ports report a value below the cached one: the DTU has
        # rolled the today counter over. (A genuine production drop cannot make
        # every port decrease at once while still operating.)
        dropped = sum(
            1 for key, value in today_candidates.items() if value < self._today.get(key, 0)
        )
        if self._today and dropped == len(today_candidates):
            _LOGGER.info("Detected Hoymiles daily today-production reset")
            self._clear_today(now)

    def _update_today(self, plant_data: PlantData) -> None:
        """Clamp today production for operating ports to its monotonic max."""
        for microinverter in plant_data.microinverter_data:
            if microinverter.operating_status <= 0:
                continue
            key = (microinverter.serial_number, microinverter.port_number)
            cached_today = self._today.get(key, 0)
            if microinverter.today_production >= cached_today:
                self._today[key] = microinverter.today_production
            else:
                _LOGGER.warning(
                    "Today production for %s port %d dropped (%d < cached %d); using cached value",
                    microinverter.serial_number,
                    microinverter.port_number,
                    microinverter.today_production,
                    cached_today,
                )
                microinverter.today_production = cached_today

    def _in_reset_window(self, now: datetime) -> bool:
        return now.hour >= self._reset_hour

    def _already_reset_today(self, now: datetime) -> bool:
        return self._last_reset_date == now.date()

    def _clear_today(self, now: datetime) -> None:
        _LOGGER.debug("Clearing today production cache")
        self._today = {}
        self._last_reset_date = now.date()
