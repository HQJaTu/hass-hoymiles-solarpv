"""
Production smoothing and daily-reset handling for Hoymiles DTU data.

Hoymiles DTUs have two quirks that this module compensates for:

1. They occasionally report a *lower* ``today``/``total`` production value than a
   previous reading (transient glitch). Left untouched this looks like a counter
   reset to Home Assistant's ``total_increasing`` statistics and produces false
   spikes on the Energy dashboard. We therefore keep a monotonic (max) cache per
   microinverter port and clamp dips back up to the cached value.

2. They reset the *today* production counter once a day at ``RESET_HOUR`` local
   time (not midnight). The monotonic cache above would otherwise pin ``today`` to
   the previous day's peak, so during that hour the today cache is dropped on every
   poll, letting it follow the DTU's counter back down to zero and up again.

This mirrors the proven behaviour of the upstream ``hoymiles_mqtt`` project: a
plain per-poll clear during the reset hour, rather than trying to *detect* the
reset (which is fragile — e.g. an evening with no operating inverters must not be
mistaken for a counter reset). The cache lives only in memory; it is rebuilt from
live DTU values after a Home Assistant restart, which also means a stuck value
self-heals on restart.
"""

from __future__ import annotations

import logging
from datetime import datetime

from .hoymiles import PlantData

_LOGGER = logging.getLogger(__name__)

# Local-time hour during which Hoymiles DTUs reset their *today* production
# counter. This matches the upstream project's value; the DTU does NOT reset at
# midnight. Clearing earlier (e.g. at sundown) would zero "today" before the DTU
# does and publish only a fraction of the day's production.
RESET_HOUR = 23

type _PortKey = tuple[str, int]


class ProductionCache:
    """
    Smooth production dips and follow the DTU's daily ``today`` reset.

    A single instance is kept per config entry and fed every poll via
    :meth:`process`, which mutates the given :class:`PlantData` in place.
    """

    def __init__(self, reset_hour: int = RESET_HOUR) -> None:
        """Initialize an empty cache."""
        self._reset_hour = reset_hour
        self._today: dict[_PortKey, int] = {}
        self._total: dict[_PortKey, int] = {}

    def process(self, plant_data: PlantData, now: datetime) -> None:
        """
        Clamp production dips, follow the daily reset and recompute totals.
        :param plant_data: freshly polled plant data; mutated in place.
        :param now: current local (timezone-aware) time, used for reset detection.
        """

        # During the DTU's reset hour, drop the today cache on every poll so it
        # tracks the DTU's counter back down to zero instead of staying pinned at
        # yesterday's peak. The total cache is cumulative and never cleared.
        if now.hour == self._reset_hour:
            self._clear_today()

        self._update_cache(plant_data)

        plant_data.today_production = sum(self._today.values())
        plant_data.total_production = sum(self._total.values())

    def _update_cache(self, plant_data: PlantData) -> None:
        """
        Update the monotonic per-port today/total caches from a poll.

        Every port in the poll gets a cache entry (so the plant sum never silently
        drops a port), but values are only updated for operating ports. A reading
        below the cached maximum is treated as a transient fault and clamped up.

        :param plant_data: freshly polled plant data
        """
        for microinverter in plant_data.microinverter_data:
            key = (microinverter.serial_number, microinverter.port_number)
            self._today.setdefault(key, 0)
            self._total.setdefault(key, 0)

            if microinverter.operating_status <= 0:
                # Non-operating port: keep its last good cached value.
                continue

            if microinverter.today_production >= self._today[key]:
                self._today[key] = microinverter.today_production
            else:
                _LOGGER.warning(
                    "Today production for %s port %d dropped (%d < cached %d); using cached value",
                    microinverter.serial_number,
                    microinverter.port_number,
                    microinverter.today_production,
                    self._today[key],
                )
                microinverter.today_production = self._today[key]

            if microinverter.total_production >= self._total[key]:
                self._total[key] = microinverter.total_production
            else:
                _LOGGER.warning(
                    "Total production for %s port %d dropped (%d < cached %d); using cached value",
                    microinverter.serial_number,
                    microinverter.port_number,
                    microinverter.total_production,
                    self._total[key],
                )
                microinverter.total_production = self._total[key]

    def _clear_today(self) -> None:
        _LOGGER.debug("Clearing today production cache (DTU reset hour)")
        self._today = {}
