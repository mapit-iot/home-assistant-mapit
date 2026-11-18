"""One event entity per vehicle: the alerts the Mapit app pushed."""

from typing import Any

from aiomapit import EventType
from homeassistant.components.event import EventEntity
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import ALERT_EVENT
from .coordinator import MapitConfigEntry, MapitCoordinator
from .entity import MapitEntity

PARALLEL_UPDATES = 0

EVENT_TYPES = [t.value for t in EventType if t is not EventType.UNKNOWN]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MapitConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the alert entity of every vehicle."""
    coordinator = entry.runtime_data
    async_add_entities(MapitAlert(coordinator, vid) for vid in coordinator.data.vehicles)


class MapitAlert(MapitEntity, EventEntity):
    """The last alert of the vehicle, from the coordinator's alert events."""

    _attr_translation_key = "alert"
    _attr_event_types = EVENT_TYPES

    def __init__(self, coordinator: MapitCoordinator, vehicle_id: str) -> None:
        super().__init__(coordinator, vehicle_id, "alert")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._device_id = self.registry_entry.device_id if self.registry_entry else None
        self.async_on_remove(
            self.hass.bus.async_listen(ALERT_EVENT, self._alert, self._for_this_vehicle)
        )

    @callback
    def _for_this_vehicle(self, data: dict[str, Any]) -> bool:
        return self._device_id is not None and data["device_id"] == self._device_id

    @callback
    def _alert(self, event: Event[dict[str, Any]]) -> None:
        data = event.data
        self._trigger_event(
            data["type"],
            {
                "occurred_at": data["occurred_at"],
                "notified_at": data["notified_at"],
                "geofence": data["geofence"],
            },
        )
        self.async_write_ha_state()
