"""Base entity: one device per vehicle."""

from aiomapit import DeviceState, Vehicle
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MapitCoordinator


class MapitEntity(CoordinatorEntity[MapitCoordinator]):
    """An entity of one vehicle."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: MapitCoordinator, vehicle_id: str, key: str) -> None:
        super().__init__(coordinator)
        self.vehicle_id = vehicle_id
        self._attr_unique_id = f"{vehicle_id}_{key}"
        vehicle = coordinator.data.vehicles[vehicle_id]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, vehicle_id)},
            name=vehicle.name or vehicle.registration_number or vehicle.model or "Mapit",
            model=vehicle.model,
            configuration_url="https://app.mapit.me",
        )

    @property
    def vehicle(self) -> Vehicle:
        return self.coordinator.data.vehicles[self.vehicle_id]

    @property
    def state_data(self) -> DeviceState | None:
        """What the tracker last reported; None when Mapit shows no data for this vehicle."""
        status = self.coordinator.data.statuses.get(self.vehicle_id)
        return status.state if status else None

    @property
    def available(self) -> bool:
        return super().available and self.vehicle_id in self.coordinator.data.vehicles
