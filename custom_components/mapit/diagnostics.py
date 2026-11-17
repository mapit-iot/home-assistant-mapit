"""Diagnostics for Mapit, without tokens, positions or vehicle names."""

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .coordinator import MapitConfigEntry

TO_REDACT = {
    "access_token",
    "refresh_token",
    "latitude",
    "longitude",
    "name",
    "registration_number",
    "unique_id",
    "title",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: MapitConfigEntry
) -> dict[str, Any]:
    """Return the entry and the last data, redacted."""
    data = entry.runtime_data.data
    return async_redact_data(
        {
            "entry": entry.as_dict(),
            "vehicles": [asdict(v) for v in data.vehicles.values()],
            "statuses": [asdict(s) for s in data.statuses.values()],
        },
        TO_REDACT,
    )
