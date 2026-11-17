"""Sensors from the last reported status of each vehicle."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from aiomapit import DeviceState, Vehicle
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricPotential,
    UnitOfLength,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import MapitConfigEntry, MapitCoordinator
from .entity import MapitEntity

PARALLEL_UPDATES = 0

# Device statuses Mapit reports; anything else shows as unknown.
STATUSES = ["at_rest", "moving", "buzz", "no_comms", "hibernation", "hibernation_requested"]

type Value = str | float | datetime | None


@dataclass(frozen=True, kw_only=True)
class MapitSensorDescription(SensorEntityDescription):
    """``state_fn`` reads the reported state; ``vehicle_fn`` reads the vehicle record."""

    state_fn: Callable[[DeviceState], Value] | None = None
    vehicle_fn: Callable[[Vehicle], Value] | None = None


def _status(state: DeviceState) -> str | None:
    value = (state.status or "").lower()
    return value if value in STATUSES else None


SENSORS = (
    MapitSensorDescription(
        key="status",
        translation_key="status",
        device_class=SensorDeviceClass.ENUM,
        options=STATUSES,
        state_fn=_status,
    ),
    MapitSensorDescription(
        key="last_location",
        translation_key="last_location",
        device_class=SensorDeviceClass.TIMESTAMP,
        state_fn=lambda s: s.last_location_at,
    ),
    MapitSensorDescription(
        key="last_communication",
        translation_key="last_communication",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        state_fn=lambda s: s.last_communication_at,
    ),
    # The tracker's own battery, not the vehicle's: the Mapit app calls it "Mapit battery".
    MapitSensorDescription(
        key="battery",
        translation_key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        state_fn=lambda s: s.battery_percent,
    ),
    # Mapit reports millivolts; shown in volts. 0 is normal while stopped, and trackers without a
    # CAN reading send 12000 only to say external power is connected: off by default.
    MapitSensorDescription(
        key="voltage",
        translation_key="voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        entity_registry_enabled_default=False,
        native_unit_of_measurement=UnitOfElectricPotential.MILLIVOLT,
        suggested_unit_of_measurement=UnitOfElectricPotential.VOLT,
        suggested_display_precision=1,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        state_fn=lambda s: s.voltage,
    ),
    MapitSensorDescription(
        key="odometer",
        translation_key="odometer",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        suggested_display_precision=0,
        # Editable km can decrease; TOTAL_INCREASING would read that as a meter reset.
        state_class=SensorStateClass.TOTAL,
        vehicle_fn=lambda v: v.km,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MapitConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the sensors of every vehicle."""
    coordinator = entry.runtime_data
    async_add_entities(
        MapitSensor(coordinator, vid, description)
        for vid in coordinator.data.vehicles
        for description in SENSORS
    )


class MapitSensor(MapitEntity, SensorEntity):
    """A value from the last report or the vehicle record."""

    entity_description: MapitSensorDescription

    def __init__(
        self, coordinator: MapitCoordinator, vehicle_id: str, description: MapitSensorDescription
    ) -> None:
        super().__init__(coordinator, vehicle_id, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Value:
        if self.entity_description.vehicle_fn:
            return self.entity_description.vehicle_fn(self.vehicle)
        state = self.state_data
        return (
            self.entity_description.state_fn(state)
            if state and self.entity_description.state_fn
            else None
        )
