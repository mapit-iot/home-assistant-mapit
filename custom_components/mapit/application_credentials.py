"""OAuth 2.1 with PKCE against Mapit's sign-in, for the built-in Home Assistant client."""

from typing import Any, override

from homeassistant.components.application_credentials import ClientCredential
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_oauth2_flow

from .const import AUTHORIZE_URL, RESOURCE, SCOPES, TOKEN_URL


class MapitImplementation(config_entry_oauth2_flow.LocalOAuth2ImplementationWithPkce):
    """PKCE flow that names the Mapit resource on every request."""

    @property
    @override
    def name(self) -> str:
        return "Mapit"

    @property
    @override
    def extra_authorize_data(self) -> dict[str, Any]:
        return {"scope": " ".join(SCOPES), "resource": RESOURCE, **super().extra_authorize_data}

    @override
    async def _token_request(self, data: dict) -> dict:
        # Mapit needs `resource` on the code exchange and on every refresh; Home Assistant's
        # refresh only sends grant_type, client_id and refresh_token.
        return await super()._token_request({**data, "resource": RESOURCE})


async def async_get_auth_implementation(
    hass: HomeAssistant, auth_domain: str, credential: ClientCredential
) -> config_entry_oauth2_flow.AbstractOAuth2Implementation:
    """Return the PKCE implementation (a fresh code verifier for each flow)."""
    return MapitImplementation(hass, auth_domain, credential.client_id, AUTHORIZE_URL, TOKEN_URL)
