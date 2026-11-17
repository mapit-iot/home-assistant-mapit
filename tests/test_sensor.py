"""Status sensor states and their translations."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.mapit.sensor import STATUSES, _status

TRANSLATIONS = Path("custom_components/mapit/translations")


@pytest.mark.parametrize("raw", ["TILT_DETECTED", "AT_REST", "Hibernation_Requested"])
def test_known_status(raw: str) -> None:
    assert _status(SimpleNamespace(status=raw)) == raw.lower()


@pytest.mark.parametrize("raw", ["SOMETHING_NEW", "", None])
def test_other_status_is_unknown(raw: str | None) -> None:
    assert _status(SimpleNamespace(status=raw)) is None


@pytest.mark.parametrize("lang", ["en", "es", "pt"])
def test_every_status_is_translated(lang: str) -> None:
    states = json.loads((TRANSLATIONS / f"{lang}.json").read_text())["entity"]["sensor"]["status"]
    assert set(states["state"]) == set(STATUSES)
