"""The Mapit integration."""

from aiomapit import MapitClient
from homeassistant.components.application_credentials import (
    ClientCredential,
    async_import_client_credential,
)
from homeassistant.const import Platform
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .const import CLIENT_ID, DOMAIN
from .coordinator import MapitConfigEntry, MapitCoordinator

PLATFORMS = [Platform.DEVICE_TRACKER, Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the built-in Home Assistant client, so the user never enters credentials."""
    await async_import_client_credential(hass, DOMAIN, ClientCredential(CLIENT_ID, "", "Mapit"))
    return True


async def async_setup_entry(hass: HomeAssistant, entry: MapitConfigEntry) -> bool:
    """Set up Mapit from a config entry."""
    try:
        implementation = await config_entry_oauth2_flow.async_get_config_entry_implementation(
            hass, entry
        )
    except config_entry_oauth2_flow.ImplementationUnavailableError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN, translation_key="implementation_unavailable"
        ) from err
    session = config_entry_oauth2_flow.OAuth2Session(hass, entry, implementation)

    async def access_token() -> str:
        await session.async_ensure_token_valid()
        return str(session.token["access_token"])

    version = (await async_get_integration(hass, DOMAIN)).version
    client = MapitClient(
        access_token,
        session=async_get_clientsession(hass),
        user_agent=f"HomeAssistant/{HA_VERSION} home-assistant-mapit/{version}",
    )
    coordinator = MapitCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MapitConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: MapitConfigEntry, device: DeviceEntry
) -> bool:
    """Let the user delete a vehicle that is no longer on the Mapit account."""
    vehicles = entry.runtime_data.data.vehicles
    return not any(domain == DOMAIN and vid in vehicles for domain, vid in device.identifiers)
