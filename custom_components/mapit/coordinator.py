"""Polls the last reported status of every vehicle in one request a minute, and the alerts
the Mapit app pushed when that status says there are new ones."""

import time
from collections import deque
from dataclasses import dataclass
from typing import Any

from aiomapit import (
    EventType,
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
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import ALERT_EVENT, DOMAIN, LOGGER, UPDATE_INTERVAL, VEHICLES_INTERVAL

type MapitConfigEntry = ConfigEntry[MapitCoordinator]

# Ids of the last alerts fired, kept to skip one delivered again.
SEEN_ALERTS = 200


def cursor_store(hass: HomeAssistant, entry_id: str) -> Store[dict[str, Any]]:
    """Where the alerts cursor and the ids of the last alerts fired survive restarts."""
    return Store(hass, 1, f"{DOMAIN}.{entry_id}.alerts")


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
        self._store = cursor_store(hass, entry.entry_id)
        self._alerts_cursor: str | None = None  # where /events goes on from; None: never read
        self._events_cursor: str | None = None  # the status's eventsCursor at the last read
        self._alerts_read = False
        self._alerts_off = False
        self._seen: deque[str] = deque(maxlen=SEEN_ALERTS)

    async def _async_setup(self) -> None:
        stored = (await self._store.async_load()) or {}
        self._alerts_cursor = stored.get("cursor")
        self._seen.extend(stored.get("ids", ()))

    async def _async_update_data(self) -> MapitData:
        try:
            statuses: dict[str, VehicleStatus] = {}
            cursor = None
            while True:
                page = (await self.client.get_statuses_page(cursor)).data
                statuses.update((s.vehicle_id, s) for s in page.items)
                if not (cursor := page.next_cursor):
                    break
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

        # Not on setup: entities and automations may not be loaded yet. The next poll reads them.
        if self.data is not None:
            await self._async_alerts(page.events_cursor)
            if self.data.vehicles.keys() != self._vehicles.keys():
                # A vehicle was added or removed: reload to add or drop its device.
                self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)
        return MapitData(dict(self._vehicles), statuses)

    async def _async_alerts(self, events_cursor: str | None) -> None:
        """Fire one alert event per new Mapit alert, after the stored cursor.

        Read once after start-up, then only when the status's eventsCursor changes. The first
        read ever only stores where to go on from, so old alerts are never replayed.
        """
        if self._alerts_off or (self._alerts_read and events_cursor == self._events_cursor):
            return
        cursor = self._alerts_cursor
        alerts = []
        try:
            while True:
                page = (await self.client.get_events_page(cursor)).data
                alerts.extend(page.items)
                cursor = page.next_cursor
                if not page.has_more:
                    break
        except MapitError as err:
            # The status is fine; alerts are retried on the next poll, from the same cursor.
            if err.status == 403:
                LOGGER.warning("This Mapit connection does not include alerts; not reading them")
                self._alerts_off = True
            else:
                LOGGER.debug("Reading Mapit alerts failed: %s", err)
            return
        new = []
        if self._alerts_cursor is not None:  # the first read ever fires nothing
            for alert in alerts:
                if alert.type is not EventType.UNKNOWN and alert.id not in self._seen:
                    self._seen.append(alert.id)
                    new.append(alert)
        self._events_cursor, self._alerts_read = events_cursor, True
        if new or cursor != self._alerts_cursor:
            self._alerts_cursor = cursor
            # Saved before firing: a crash in between drops these alerts, never fires them twice.
            await self._store.async_save({"cursor": cursor, "ids": list(self._seen)})
        devices = dr.async_get(self.hass)
        for alert in new:
            device = devices.async_get_device_by_identifier(
                (DOMAIN, alert.vehicle_id), self.config_entry.entry_id
            )
            self.hass.bus.async_fire(
                ALERT_EVENT,
                {
                    "device_id": device.id if device else None,
                    "type": alert.type.value,
                    "occurred_at": alert.occurred_at.isoformat(),
                    "notified_at": alert.notified_at.isoformat(),
                    "geofence": alert.geofence_name,
                },
            )
