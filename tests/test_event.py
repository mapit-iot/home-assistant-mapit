"""Alerts: read when the status's eventsCursor changes, fired on the bus and the event entity."""

from datetime import timedelta
from http import HTTPStatus
from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.mapit.const import ALERT_EVENT, DOMAIN

from .conftest import EVENTS_URL, HONDA, STATUS, STATUS_URL, VEHICLES, VEHICLES_URL, VESPA

ALERT: dict[str, Any] = {
    "id": "evt_1",
    "type": "geofence_entered",
    "vehicleId": VESPA,
    "occurredAt": "2026-11-18T08:01:12.000Z",
    "notifiedAt": "2026-11-18T08:01:30.000Z",
    "geofence": {"name": "Home"},
}


def _store_key(entry: MockConfigEntry) -> str:
    return f"{DOMAIN}.{entry.entry_id}.alerts"


def _events_cursors(mock: AiohttpClientMocker) -> list[str | None]:
    """The cursor of every /events call, in order."""
    return [
        url.query.get("cursor")
        for _, url, _, _ in mock.mock_calls
        if str(url).startswith(EVENTS_URL)
    ]


def _answer(mock: AiohttpClientMocker, events_cursor: str | None, **events: Any) -> None:
    """Status with this eventsCursor; ``events`` maps a cursor ("" for none) to a page or status."""
    mock.clear_requests()
    mock.get(STATUS_URL, json={**STATUS, "eventsCursor": events_cursor})
    for cursor, answer in events.items():
        url = f"{EVENTS_URL}?cursor={cursor}" if cursor else EVENTS_URL
        if isinstance(answer, HTTPStatus):
            headers = {"WWW-Authenticate": 'Bearer error="insufficient_scope"'}
            mock.get(url, status=answer, headers=headers)
        else:
            mock.get(url, json=answer)


def _page(*alerts: dict[str, Any], next_cursor: str, has_more: bool = False) -> dict[str, Any]:
    return {"events": list(alerts), "nextCursor": next_cursor, "hasMore": has_more}


async def _tick(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.tick(timedelta(seconds=61))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_first_install_replays_nothing_then_fires_new_alerts(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    loaded_entry: MockConfigEntry,
    mapit_api: AiohttpClientMocker,
    hass_storage: dict[str, Any],
) -> None:
    fired = async_capture_events(hass, ALERT_EVENT)
    assert _events_cursors(mapit_api) == []  # not during setup

    # The first read ever only stores where to go on from.
    _answer(mapit_api, "ec_1", **{"": _page(ALERT, next_cursor="cur_1")})
    await _tick(hass, freezer)
    assert _events_cursors(mapit_api) == [None]
    assert fired == []
    assert hass.states.get("event.vespa_alert").state == STATE_UNKNOWN
    assert hass_storage[_store_key(loaded_entry)]["data"] == {"cursor": "cur_1"}

    # Same eventsCursor: no /events call.
    _answer(mapit_api, "ec_1")
    await _tick(hass, freezer)
    assert _events_cursors(mapit_api) == []

    # New alerts, over two pages; a type this version does not know is skipped.
    future = {**ALERT, "id": "evt_2", "type": "tow_detected", "geofence": None}
    ride = {**ALERT, "id": "evt_3", "type": "movement_detected", "vehicleId": HONDA}
    del ride["geofence"]
    _answer(
        mapit_api,
        "ec_2",
        cur_1=_page(ALERT, future, next_cursor="cur_2", has_more=True),
        cur_2=_page(ride, next_cursor="cur_3"),
    )
    await _tick(hass, freezer)
    assert _events_cursors(mapit_api) == ["cur_1", "cur_2"]

    devices = dr.async_get(hass)
    vespa = devices.async_get_device_by_identifier((DOMAIN, VESPA), loaded_entry.entry_id)
    honda = devices.async_get_device_by_identifier((DOMAIN, HONDA), loaded_entry.entry_id)
    assert [e.data for e in fired] == [
        {
            "device_id": vespa.id,
            "type": "geofence_entered",
            "occurred_at": "2026-11-18T08:01:12+00:00",
            "notified_at": "2026-11-18T08:01:30+00:00",
            "geofence": "Home",
        },
        {
            "device_id": honda.id,
            "type": "movement_detected",
            "occurred_at": "2026-11-18T08:01:12+00:00",
            "notified_at": "2026-11-18T08:01:30+00:00",
            "geofence": None,
        },
    ]
    state = hass.states.get("event.vespa_alert")
    assert state.state != STATE_UNKNOWN
    assert (state.attributes["event_type"], state.attributes["geofence"]) == (
        "geofence_entered",
        "Home",
    )
    assert "movement_detected" in state.attributes["event_types"]
    assert hass.states.get("event.honda_alert").attributes["event_type"] == "movement_detected"
    assert hass_storage[_store_key(loaded_entry)]["data"] == {"cursor": "cur_3"}


async def test_restart_goes_on_from_the_stored_cursor(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    setup_credentials: None,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    hass_storage: dict[str, Any],
) -> None:
    """Alerts that came while Home Assistant was off are fired on the first poll after setup."""
    key = _store_key(config_entry)
    hass_storage[key] = {"version": 1, "minor_version": 1, "key": key, "data": {"cursor": "cur_5"}}
    _answer(aioclient_mock, None, cur_5=_page(ALERT, next_cursor="cur_6"))
    aioclient_mock.get(VEHICLES_URL, json=VEHICLES)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    fired = async_capture_events(hass, ALERT_EVENT)

    await _tick(hass, freezer)
    assert _events_cursors(aioclient_mock) == ["cur_5"]
    assert [e.data["type"] for e in fired] == ["geofence_entered"]
    assert hass_storage[key]["data"] == {"cursor": "cur_6"}

    await hass.config_entries.async_remove(config_entry.entry_id)
    await hass.async_block_till_done()
    assert key not in hass_storage


async def test_errors_retry_from_the_same_cursor(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    loaded_entry: MockConfigEntry,
    mapit_api: AiohttpClientMocker,
    hass_storage: dict[str, Any],
) -> None:
    """A failed /events call leaves the status alone and is retried on the next poll."""
    _answer(mapit_api, "ec_1", **{"": HTTPStatus.BAD_GATEWAY})
    await _tick(hass, freezer)
    assert _events_cursors(mapit_api) == [None]
    assert hass.states.get("sensor.vespa_status").state == "at_rest"
    assert _store_key(loaded_entry) not in hass_storage

    _answer(mapit_api, "ec_1", **{"": _page(next_cursor="cur_1")})
    await _tick(hass, freezer)
    assert _events_cursors(mapit_api) == [None]
    assert hass_storage[_store_key(loaded_entry)]["data"] == {"cursor": "cur_1"}


async def test_no_alerts_permission_logs_once(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    loaded_entry: MockConfigEntry,
    mapit_api: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _answer(mapit_api, "ec_1", **{"": HTTPStatus.FORBIDDEN})
    await _tick(hass, freezer)
    assert _events_cursors(mapit_api) == [None]
    _answer(mapit_api, "ec_2", **{"": HTTPStatus.FORBIDDEN})
    await _tick(hass, freezer)

    assert _events_cursors(mapit_api) == []  # not asked again
    assert caplog.text.count("does not include alerts") == 1
    assert hass.states.get("sensor.vespa_status").state == "at_rest"
    assert not hass.config_entries.flow.async_progress_by_handler(DOMAIN)
