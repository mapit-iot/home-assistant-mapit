"""Setup, polling (304 and rate limits), entities and diagnostics."""

from datetime import timedelta
from http import HTTPStatus

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.mapit import async_remove_config_entry_device
from custom_components.mapit.const import DOMAIN

from .conftest import STATUS, STATUS_URL, VEHICLES, VEHICLES_URL


def _calls(aioclient_mock: AiohttpClientMocker, url: str) -> list[dict]:
    return [headers for _, u, _, headers in aioclient_mock.mock_calls if str(u) == url]


async def _tick(hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


@pytest.mark.usefixtures("enable_all_entities")
async def test_entities(hass: HomeAssistant, loaded_entry: MockConfigEntry) -> None:
    """One device per vehicle; values are the last report, with its times."""
    assert loaded_entry.state is ConfigEntryState.LOADED

    tracker = hass.states.get("device_tracker.vespa")
    assert tracker.state == "not_home"
    assert tracker.attributes["latitude"] == 41.39
    assert tracker.attributes["longitude"] == 2.17
    assert tracker.attributes["source_type"] == "gps"
    assert hass.states.get("sensor.vespa_status").state == "at_rest"
    assert hass.states.get("sensor.vespa_last_location").state == "2026-11-11T14:10:31+00:00"
    assert hass.states.get("sensor.vespa_last_communication").state == "2026-11-11T15:34:15+00:00"
    assert hass.states.get("sensor.vespa_mapit_battery").state == "100"
    voltage = hass.states.get("sensor.vespa_vehicle_voltage")
    assert (voltage.state, voltage.attributes["unit_of_measurement"]) == ("12.0", "V")
    odometer = hass.states.get("sensor.vespa_odometer")
    assert (odometer.state, odometer.attributes["unit_of_measurement"]) == ("12345.6", "km")

    # A cancelled subscription: Mapit shows no position, but the vehicle is still there.
    assert hass.states.get("device_tracker.honda").state == STATE_UNKNOWN
    assert hass.states.get("sensor.honda_status").state == STATE_UNKNOWN
    assert hass.states.get("sensor.honda_odometer").state == "3359"

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, "veh_vespa"), loaded_entry.entry_id
    )
    assert (device.name, device.model) == ("Vespa", "GTS 300")


async def test_voltage_off_by_default(hass: HomeAssistant, loaded_entry: MockConfigEntry) -> None:
    """Trackers without a CAN reading send a fixed 12000 mV, so voltage starts disabled."""
    entry = er.async_get(hass).async_get("sensor.vespa_vehicle_voltage")
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get("sensor.vespa_vehicle_voltage") is None


async def test_unload(hass: HomeAssistant, loaded_entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(loaded_entry.entry_id)
    assert loaded_entry.state is ConfigEntryState.NOT_LOADED


async def test_one_status_call_and_304(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    loaded_entry: MockConfigEntry,
    mapit_api: AiohttpClientMocker,
) -> None:
    """Each minute is one /status call with the last tag; a 304 keeps the last values."""
    assert len(_calls(mapit_api, STATUS_URL)) == 1
    assert len(_calls(mapit_api, VEHICLES_URL)) == 1

    mapit_api.clear_requests()
    mapit_api.get(STATUS_URL, status=HTTPStatus.NOT_MODIFIED)
    await _tick(hass, freezer, 30)
    assert mapit_api.call_count == 0
    await _tick(hass, freezer, 31)

    (headers,) = _calls(mapit_api, STATUS_URL)
    assert headers["If-None-Match"] == 'W/"status-1"'
    assert mapit_api.call_count == 1  # vehicles are read once an hour
    assert hass.states.get("sensor.vespa_status").state == "at_rest"
    assert hass.states.get("device_tracker.vespa").attributes["latitude"] == 41.39


async def test_rate_limited_backs_off(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    loaded_entry: MockConfigEntry,
    mapit_api: AiohttpClientMocker,
) -> None:
    """A 429 waits for Retry-After before the next call, and never polls faster than 60 s."""
    mapit_api.clear_requests()
    mapit_api.get(STATUS_URL, status=HTTPStatus.TOO_MANY_REQUESTS, headers={"Retry-After": "300"})
    await _tick(hass, freezer, 61)
    assert mapit_api.call_count == 1
    assert hass.states.get("sensor.vespa_status").state == STATE_UNAVAILABLE

    await _tick(hass, freezer, 120)
    assert mapit_api.call_count == 1

    mapit_api.clear_requests()
    mapit_api.get(STATUS_URL, json=STATUS)
    await _tick(hass, freezer, 200)
    assert mapit_api.call_count == 1
    assert hass.states.get("sensor.vespa_status").state == "at_rest"


@pytest.mark.parametrize(
    ("status", "headers"),
    [
        (HTTPStatus.UNAUTHORIZED, {}),
        (HTTPStatus.FORBIDDEN, {"WWW-Authenticate": 'Bearer error="insufficient_scope"'}),
    ],
)
async def test_rejected_token_starts_reauth(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    loaded_entry: MockConfigEntry,
    mapit_api: AiohttpClientMocker,
    status: HTTPStatus,
    headers: dict[str, str],
) -> None:
    """A removed connection or a withdrawn location consent asks to sign in again."""
    mapit_api.clear_requests()
    mapit_api.get(STATUS_URL, status=status, headers=headers)
    await _tick(hass, freezer, 61)

    (flow,) = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert flow["context"]["source"] == "reauth"


async def test_setup_retries_when_mapit_is_down(
    hass: HomeAssistant,
    setup_credentials: None,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    aioclient_mock.get(STATUS_URL, status=HTTPStatus.BAD_GATEWAY)
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_new_vehicle_reloads(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    loaded_entry: MockConfigEntry,
    mapit_api: AiohttpClientMocker,
) -> None:
    """A vehicle added to the account gets its device without a restart."""
    new = {"id": "veh_new", "name": "Scooter", "products": [], "km": 1}
    status = {"vehicleId": "veh_new", "state": None, "reason": "no_linked_device"}
    mapit_api.clear_requests()
    mapit_api.get(STATUS_URL, json={**STATUS, "vehicles": [*STATUS["vehicles"], status]})
    mapit_api.get(VEHICLES_URL, json={**VEHICLES, "vehicles": [*VEHICLES["vehicles"], new]})
    await _tick(hass, freezer, 61)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert hass.states.get("sensor.scooter_odometer").state == "1"


async def test_diagnostics_redacted(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, loaded_entry: MockConfigEntry
) -> None:
    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, loaded_entry)
    text = str(diagnostics)
    for secret in ("access-1", "refresh-1", "rider@example.com", "41.39", "2.17", "Vespa"):
        assert secret not in text
    assert diagnostics["statuses"][0]["state"]["status"] == "AT_REST"
    assert diagnostics["vehicles"][0]["km"] == 12345.6


async def test_only_gone_vehicles_can_be_deleted(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    registry = dr.async_get(hass)
    vespa = registry.async_get_device_by_identifier((DOMAIN, "veh_vespa"), loaded_entry.entry_id)
    gone = registry.async_get_or_create(
        config_entry_id=loaded_entry.entry_id, identifiers={(DOMAIN, "veh_gone")}
    )
    assert not await async_remove_config_entry_device(hass, loaded_entry, vespa)
    assert await async_remove_config_entry_device(hass, loaded_entry, gone)
