"""Config flow for Mapit: sign in with Mapit (OAuth 2.1 + PKCE), and sign in again when needed."""

import logging
from collections.abc import Mapping
from typing import Any, override

from aiomapit import MapitClient, MapitError
from homeassistant.components.application_credentials import (
    ClientCredential,
    async_import_client_credential,
)
from homeassistant.config_entries import SOURCE_REAUTH, ConfigFlowResult
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CLIENT_ID, DOMAIN, LOCATION_SCOPE, LOGGER


class MapitFlowHandler(config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN):
    """Link a Mapit account."""

    DOMAIN = DOMAIN

    @property
    @override
    def logger(self) -> logging.Logger:
        return LOGGER

    @override
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Register the built-in client first: a new install has not run async_setup yet."""
        await async_import_client_credential(
            self.hass, DOMAIN, ClientCredential(CLIENT_ID, "", "Mapit")
        )
        return await super().async_step_user(user_input)

    @override
    async def async_oauth_create_entry(self, data: dict[str, Any]) -> ConfigFlowResult:
        """Name the entry after the account, one entry per account."""
        # Location is an opt-in box at consent; without it every poll would ask to sign in again.
        if LOCATION_SCOPE not in data["token"].get("scope", "").split():
            return self.async_abort(reason="location_required")
        client = MapitClient(
            data["token"]["access_token"], session=async_get_clientsession(self.hass)
        )
        try:
            account = (await client.get_me()).data
        except MapitError as err:
            LOGGER.debug("Could not read the Mapit account: %s", err)
            return self.async_abort(reason="cannot_connect")
        if not account.id:
            LOGGER.debug("Mapit returned no account id")
            return self.async_abort(reason="cannot_connect")

        # The account id, not the email, which the customer can change.
        await self.async_set_unique_id(account.id)
        if self.source == SOURCE_REAUTH:
            self._abort_if_unique_id_mismatch(reason="wrong_account")
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(), title=account.email, data=data
            )
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=account.email, data=data)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """The Mapit connection expired or was removed."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask before opening the Mapit sign-in again."""
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm")
        return await self.async_step_user()
