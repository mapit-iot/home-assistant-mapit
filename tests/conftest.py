"""Fixtures: a linked Mapit account and the Mapit endpoints, mocked at the HTTP level."""

import time
from collections.abc import Generator
from typing import Any
from unittest.mock import PropertyMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.mapit.const import DOMAIN, RESOURCE

STATUS_URL = f"{RESOURCE}/status"
VEHICLES_URL = f"{RESOURCE}/vehicles"
ME_URL = f"{RESOURCE}/me"
EMAIL = "rider@example.com"
ACCOUNT_ID = "acc_rider"
ME = {"id": ACCOUNT_ID, "name": "Rider", "email": EMAIL}
SCOPE = "mapit:read mapit:location:read offline_access"
VESPA = "veh_vespa"
HONDA = "veh_honda"

VEHICLES: dict[str, Any] = {
    "vehicles": [
        {
            "id": VESPA,
            "name": "Vespa",
            "model": "GTS 300",
            "km": 12345.6,
            "products": ["Mapit Connect"],
            "cancelled": False,
            "blockedByTransfer": False,
        },
        {
            "id": HONDA,
            "name": "Honda",
            "model": None,
            "km": 3359,
            "products": ["Honda Mapit"],
            "cancelled": True,
            "blockedByTransfer": False,
        },
    ],
    "nextCursor": None,
}

STATUS: dict[str, Any] = {
    "vehicles": [
        {
            "vehicleId": VESPA,
            "state": {
                "status": "AT_REST",
                "batteryPercent": 100,
                "voltage": 12000,
                "latitude": 41.39,
                "longitude": 2.17,
                "lastCommunicationAt": "2026-11-11T15:34:15.000000Z",
                "lastLocationAt": "2026-11-11T14:10:31.000000Z",
            },
            "source": "last_reported_device_state",
            "fetchedAt": "2026-11-17T10:00:00.000Z",
        },
        {"vehicleId": HONDA, "state": None, "reason": "subscription_cancelled"},
    ],
    "nextCursor": None,
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components/mapit."""


@pytest.fixture
def enable_all_entities() -> Generator[None]:
    """Create the entities that are disabled by default too."""
    with patch(
        "homeassistant.helpers.entity.Entity.entity_registry_enabled_default",
        PropertyMock(return_value=True),
    ):
        yield


@pytest.fixture
async def setup_credentials(hass: HomeAssistant) -> None:
    """Run async_setup, which registers the built-in client."""
    assert await async_setup_component(hass, "application_credentials", {})
    assert await async_setup_component(hass, DOMAIN, {})


def token(access: str = "access-1", expires_in: float = 900, scope: str = SCOPE) -> dict[str, Any]:
    return {
        "access_token": access,
        "refresh_token": "refresh-1",
        "token_type": "Bearer",
        "expires_in": expires_in,
        "expires_at": time.time() + expires_in,
        "scope": scope,
    }


@pytest.fixture
def config_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=EMAIL,
        unique_id=ACCOUNT_ID,
        data={"auth_implementation": DOMAIN, "token": token()},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def mapit_api(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    aioclient_mock.get(STATUS_URL, json=STATUS, headers={"ETag": 'W/"status-1"'})
    aioclient_mock.get(VEHICLES_URL, json=VEHICLES, headers={"ETag": 'W/"vehicles-1"'})
    return aioclient_mock


@pytest.fixture
async def loaded_entry(
    hass: HomeAssistant,
    setup_credentials: None,
    config_entry: MockConfigEntry,
    mapit_api: AiohttpClientMocker,
) -> MockConfigEntry:
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry
