"""Last reported position of each vehicle."""

from homeassistant.components.device_tracker import TrackerEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import MapitConfigEntry
from .entity import MapitEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MapitConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add one tracker per vehicle."""
    coordinator = entry.runtime_data
    async_add_entities(
        MapitTracker(coordinator, vid, "location") for vid in coordinator.data.vehicles
    )


class MapitTracker(MapitEntity, TrackerEntity):
    """Where the tracker last reported a position (see the Last location sensor for when)."""

    _attr_name = None

    @property
    def latitude(self) -> float | None:
        return self.state_data.latitude if self.state_data else None

    @property
    def longitude(self) -> float | None:
        return self.state_data.longitude if self.state_data else None
