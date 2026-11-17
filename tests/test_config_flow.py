"""Config flow: sign in with PKCE, one entry per account, reauth, and resource on refresh."""

from http import HTTPStatus
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_entry_oauth2_flow
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.mapit.const import CLIENT_ID, DOMAIN, RESOURCE, TOKEN_URL

from .conftest import ACCOUNT_ID, EMAIL, ME, ME_URL, SCOPE, STATUS_URL, token

REDIRECT = "https://example.com/auth/external/callback"


async def _sign_in(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    result: dict,
    me: dict | None = None,
    scope: str = SCOPE,
) -> dict:
    """Follow the external step: check the authorize URL, call back, exchange the code."""
    assert result["type"] is FlowResultType.EXTERNAL_STEP
    query = parse_qs(urlparse(result["url"]).query)
    assert query["client_id"] == [CLIENT_ID]
    assert query["resource"] == [RESOURCE]
    assert query["scope"] == ["mapit:read mapit:location:read offline_access"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"]
    assert query["redirect_uri"] == [REDIRECT]

    state = config_entry_oauth2_flow._encode_jwt(
        hass, {"flow_id": result["flow_id"], "redirect_uri": REDIRECT}
    )
    client = await hass_client_no_auth()
    resp = await client.get(f"/auth/external/callback?code=abcd&state={state}")
    assert resp.status == HTTPStatus.OK

    aioclient_mock.post(TOKEN_URL, json=token("access-new", scope=scope))
    aioclient_mock.get(ME_URL, json=ME if me is None else me)
    return await hass.config_entries.flow.async_configure(result["flow_id"])


def _token_posts(aioclient_mock: AiohttpClientMocker) -> list[dict]:
    return [data for method, url, data, _ in aioclient_mock.mock_calls if str(url) == TOKEN_URL]


@pytest.mark.usefixtures("current_request_with_host")
async def test_full_flow(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A new install registers the built-in client and links the account."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    with patch("custom_components.mapit.async_setup_entry", return_value=True):
        result = await _sign_in(hass, hass_client_no_auth, aioclient_mock, result)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == EMAIL
    assert result["result"].unique_id == ACCOUNT_ID
    assert result["data"]["token"]["access_token"] == "access-new"
    (exchange,) = _token_posts(aioclient_mock)
    assert exchange["grant_type"] == "authorization_code"
    assert exchange["client_id"] == CLIENT_ID
    assert exchange["resource"] == RESOURCE
    assert exchange["code_verifier"]
    assert "client_secret" not in exchange


@pytest.mark.usefixtures("current_request_with_host", "config_entry")
async def test_already_configured(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await _sign_in(hass, hass_client_no_auth, aioclient_mock, result)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.usefixtures("current_request_with_host")
async def test_account_unreadable(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    aioclient_mock.get(ME_URL, status=HTTPStatus.SERVICE_UNAVAILABLE)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await _sign_in(hass, hass_client_no_auth, aioclient_mock, result)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


@pytest.mark.usefixtures("current_request_with_host")
@pytest.mark.parametrize(
    ("me", "reason", "access_token"),
    [
        # The customer changed their email: still the same account.
        ({**ME, "email": "new@example.com"}, "reauth_successful", "access-new"),
        ({**ME, "id": "acc_other"}, "wrong_account", None),
    ],
)
async def test_reauth(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    me: dict,
    reason: str,
    access_token: str | None,
) -> None:
    """Signing in again updates the same entry; another account is refused."""
    old_token = config_entry.data["token"]["access_token"]
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    with patch("custom_components.mapit.async_setup_entry", return_value=True):
        result = await _sign_in(hass, hass_client_no_auth, aioclient_mock, result, me)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == reason
    assert config_entry.data["token"]["access_token"] == (access_token or old_token)
    assert config_entry.title == (me["email"] if access_token else EMAIL)


@pytest.mark.usefixtures("current_request_with_host")
@pytest.mark.parametrize("reauth", [False, True])
async def test_location_not_allowed(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
    reauth: bool,
) -> None:
    """Location is an unticked box at consent: without it, stop and say so (no reauth loop)."""
    if reauth:
        result = await config_entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    else:
        await hass.config_entries.async_remove(config_entry.entry_id)
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    old = dict(config_entry.data)
    result = await _sign_in(
        hass, hass_client_no_auth, aioclient_mock, result, scope="mapit:read offline_access"
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "location_required"
    assert not [u for _, u, _, _ in aioclient_mock.mock_calls if str(u) == ME_URL]
    assert config_entry.data == old
    assert len(hass.config_entries.async_entries(DOMAIN)) == (1 if reauth else 0)


@pytest.mark.usefixtures("current_request_with_host")
async def test_no_account_id(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A server without the account id cannot give a stable entry: do not create one."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    me = {"name": "Rider", "email": EMAIL}
    result = await _sign_in(hass, hass_client_no_auth, aioclient_mock, result, me)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


@pytest.mark.usefixtures("setup_credentials")
async def test_refresh_sends_resource(
    hass: HomeAssistant, config_entry: MockConfigEntry, mapit_api: AiohttpClientMocker
) -> None:
    """An expired access token is refreshed with `resource`, and the new one is used."""
    hass.config_entries.async_update_entry(
        config_entry, data={**config_entry.data, "token": token("access-old", expires_in=-60)}
    )
    mapit_api.post(TOKEN_URL, json=token("access-refreshed"))

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    (refresh,) = _token_posts(mapit_api)
    assert refresh == {
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "refresh_token": "refresh-1",
        "resource": RESOURCE,
    }
    assert config_entry.data["token"]["access_token"] == "access-refreshed"
    status_headers = next(h for _, url, _, h in mapit_api.mock_calls if str(url) == STATUS_URL)
    assert status_headers["Authorization"] == "Bearer access-refreshed"


@pytest.mark.usefixtures("setup_credentials")
async def test_refresh_rejected_starts_reauth(
    hass: HomeAssistant, config_entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    """A refresh session past its 30 days (or a year) asks the user to sign in again."""
    hass.config_entries.async_update_entry(
        config_entry, data={**config_entry.data, "token": token(expires_in=-60)}
    )
    aioclient_mock.post(TOKEN_URL, status=HTTPStatus.BAD_REQUEST, json={"error": "invalid_grant"})

    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    (flow,) = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert flow["context"]["source"] == "reauth"
