"""Polls the last reported status of every vehicle in one request a minute."""

import time
from dataclasses import dataclass

from aiomapit import (
    MapitAuthError,
    MapitClient,
    MapitError,
    MapitRateLimited,
    MapitScopeError,
    Vehicle,
    VehicleStatus,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, LOGGER, UPDATE_INTERVAL, VEHICLES_INTERVAL

type MapitConfigEntry = ConfigEntry[MapitCoordinator]


@dataclass(frozen=True, slots=True)
class MapitData:
    """Vehicles and their last reported status, by vehicle id."""

    vehicles: dict[str, Vehicle]
    statuses: dict[str, VehicleStatus]


class MapitCoordinator(DataUpdateCoordinator[MapitData]):
    """One /status call per cycle (a 304 when nothing changed); vehicles once an hour."""

    config_entry: MapitConfigEntry

    def __init__(self, hass: HomeAssistant, entry: MapitConfigEntry, client: MapitClient) -> None:
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
            always_update=False,
        )
        self.client = client
        self._vehicles: dict[str, Vehicle] = {}
        self._vehicles_at = 0.0

    async def _async_update_data(self) -> MapitData:
        try:
            statuses = {s.vehicle_id: s async for s in self.client.iter_statuses()}
            stale = time.monotonic() - self._vehicles_at > VEHICLES_INTERVAL.total_seconds()
            if stale or not statuses.keys() <= self._vehicles.keys():
                self._vehicles = {v.id: v async for v in self.client.iter_vehicles()}
                self._vehicles_at = time.monotonic()
        except MapitAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        except MapitScopeError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="location_required"
            ) from err
        except MapitRateLimited as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="rate_limited",
                retry_after=max(err.retry_after or 0, UPDATE_INTERVAL.total_seconds()),
            ) from err
        except MapitError as err:
            # aiomapit's messages name the "Mapit API", a word customers never see: log, not show.
            LOGGER.debug("Mapit update failed: %s", err)
            raise UpdateFailed(translation_domain=DOMAIN, translation_key="update_failed") from err

        if self.data is not None and self.data.vehicles.keys() != self._vehicles.keys():
            # A vehicle was added or removed: reload to add or drop its device.
            self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)
        return MapitData(dict(self._vehicles), statuses)
