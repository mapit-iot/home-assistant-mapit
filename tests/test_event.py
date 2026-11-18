"""Alerts: read when the status's eventsCursor changes, fired on the bus and the event entity."""

from datetime import timedelta
from http import HTTPStatus
from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, callback
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


@pytest.fixture(autouse=True)
def _just_after_alert(freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to("2026-11-18T08:02:00+00:00")


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
    assert hass_storage[_store_key(loaded_entry)]["data"] == {"cursor": "cur_1", "ids": []}

    # Same eventsCursor: no /events call.
    _answer(mapit_api, "ec_1", **{"cur_1": _page(next_cursor="cur_1")})
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
    assert hass_storage[_store_key(loaded_entry)]["data"] == {
        "cursor": "cur_3",
        "ids": ["evt_1", "evt_3"],
    }


async def test_restart_goes_on_from_the_stored_cursor_without_repeats(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    setup_credentials: None,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    hass_storage: dict[str, Any],
) -> None:
    """Alerts that came while Home Assistant was off are fired after a restart, once each.

    The store says evt_1 was fired before the crash, but Mapit delivers it again from the
    stored cursor: only evt_2 fires, and it is in the store before it is fired.
    """
    key = _store_key(config_entry)
    hass_storage[key] = {
        "version": 1,
        "minor_version": 1,
        "key": key,
        "data": {"cursor": "cur_5", "ids": ["evt_1"]},
    }
    second = {**ALERT, "id": "evt_2", "type": "geofence_exited"}
    _answer(aioclient_mock, None, cur_5=_page(ALERT, second, next_cursor="cur_6"))
    aioclient_mock.get(VEHICLES_URL, json=VEHICLES)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    stored_when_fired: list[dict[str, Any]] = []

    @callback
    def _read_store(_: Event) -> None:
        # Runs inside async_fire, so it sees the store as it was at that moment.
        stored_when_fired.append(hass_storage[key]["data"])

    hass.bus.async_listen(ALERT_EVENT, _read_store)
    fired = async_capture_events(hass, ALERT_EVENT)

    await _tick(hass, freezer)
    assert _events_cursors(aioclient_mock) == ["cur_5"]
    assert [e.data["type"] for e in fired] == ["geofence_exited"]
    assert stored_when_fired == [{"cursor": "cur_6", "ids": ["evt_1", "evt_2"]}]
    assert hass_storage[key]["data"] == {"cursor": "cur_6", "ids": ["evt_1", "evt_2"]}

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
    assert hass_storage[_store_key(loaded_entry)]["data"] == {"cursor": "cur_1", "ids": []}


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


async def test_stale_alerts_are_marked_seen_but_not_fired(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    loaded_entry: MockConfigEntry,
    mapit_api: AiohttpClientMocker,
    hass_storage: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """After an outage only alerts notified in the last 15 minutes fire."""
    caplog.set_level("DEBUG")
    fired = async_capture_events(hass, ALERT_EVENT)
    _answer(mapit_api, "ec_1", **{"": _page(next_cursor="cur_1")})
    await _tick(hass, freezer)

    old = {**ALERT, "id": "evt_old", "notifiedAt": "2026-11-18T07:48:00.000Z"}
    edge = {**ALERT, "id": "evt_edge", "notifiedAt": "2026-11-18T07:49:30.000Z"}
    fresh = {**ALERT, "id": "evt_fresh", "notifiedAt": "2026-11-18T08:03:00.000Z"}
    _answer(mapit_api, "ec_2", cur_1=_page(old, edge, fresh, next_cursor="cur_2"))
    await _tick(hass, freezer)

    assert [e.data["notified_at"] for e in fired] == [
        "2026-11-18T07:49:30+00:00",
        "2026-11-18T08:03:00+00:00",
    ]
    assert "Skipped 1 Mapit alerts" in caplog.text
    assert hass_storage[_store_key(loaded_entry)]["data"] == {
        "cursor": "cur_2",
        "ids": ["evt_old", "evt_edge", "evt_fresh"],
    }
