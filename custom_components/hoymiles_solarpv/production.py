"""
Production smoothing and daily-reset handling for Hoymiles DTU data.

A microinverter's ``today`` / ``total`` production registers are **cumulative**:
within a day they can only ever increase (a cloud lowers instantaneous *power*,
never the accumulated Wh). The only time ``today`` decreases is the DTU's once-a-day
rollover, when every port resets to ~0 simultaneously. ``total`` is a lifetime
counter and never resets.

Two quirks need compensating for:

1. The DTU occasionally reports a momentarily *lower* value (a transient glitch on
   a single port). Left untouched this looks like a counter reset to consumers
   (Home Assistant statistics, Grafana ``rate()``) and produces false spikes. We
   keep a monotonic (max) cache per port and clamp such dips back up.

2. The DTU's daily ``today`` rollover. Because the registers are cumulative, *any*
   genuine decrease across **all** operating ports at once is the rollover — never
   noise. We detect that and drop the today cache in a single clean step so the
   published value falls to ~0 exactly once, instead of stair-stepping (which a
   clock-based per-poll clear used to cause, warping ``rate()`` badly).

The cache lives only in memory and is rebuilt from live DTU values after a Home
Assistant restart.
"""

from __future__ import annotations

import logging

from .hoymiles import PlantData

_LOGGER = logging.getLogger(__name__)

type _PortKey = tuple[str, int]


class ProductionCache:
    """
    Smooth production dips and follow the DTU's daily ``today`` rollover.

    A single instance is kept per config entry and fed every poll via
    :meth:`process`, which mutates the given :class:`PlantData` in place.
    """

    def __init__(self) -> None:
        """Initialize an empty cache."""
        self._today: dict[_PortKey, int] = {}
        self._total: dict[_PortKey, int] = {}

    def process(self, plant_data: PlantData) -> None:
        """
        Clamp production dips, follow the daily reset and recompute plant totals.

        :param plant_data: freshly polled plant data; mutated in place.
        """
        self._update_cache(plant_data)

        plant_data.today_production = sum(self._today.values())
        plant_data.total_production = sum(self._total.values())

    def _update_cache(self, plant_data: PlantData) -> None:
        """
        Update the monotonic per-port today/total caches from a poll.

        Every port in the poll gets a cache entry (so the plant sum never silently
        drops a port), but values are only updated for operating ports. A reading
        below the cached maximum is treated as a transient fault and clamped up,
        unless it is the DTU's daily rollover (handled atomically first).

        :param plant_data: freshly polled plant data
        """
        operating = [mi for mi in plant_data.microinverter_data if mi.operating_status > 0]

        if self._is_daily_reset(operating):
            _LOGGER.info("Detected Hoymiles daily today-production rollover; resetting today cache")
            self._today = {}

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

    def _is_daily_reset(self, operating: list) -> bool:
        """
        Return True if the DTU has rolled its daily ``today`` counters over.

        The rollover zeroes every port at once, so it is recognised when *every*
        operating port that previously had real production now reports well under
        half of its cached value. A single glitching port (others unchanged) does
        not qualify — that is smoothed as a dip instead.

        :param operating: microinverter records with ``operating_status > 0``
        """
        relevant = [
            microinverter
            for microinverter in operating
            if self._today.get((microinverter.serial_number, microinverter.port_number), 0) > 0
        ]
        if not relevant:
            return False
        return all(
            microinverter.today_production * 2
            < self._today[(microinverter.serial_number, microinverter.port_number)]
            for microinverter in relevant
        )
