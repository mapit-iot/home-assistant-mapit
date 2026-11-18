"""Constants for the Mapit integration."""

import logging
from datetime import timedelta

DOMAIN = "mapit"
LOGGER = logging.getLogger(__package__)

# A public client built into Mapit: no secret; its only redirect is my.home-assistant.io.
CLIENT_ID = "home-assistant"
AUTHORIZE_URL = "https://login.mapit.me/oauth/authorize"
TOKEN_URL = "https://login.mapit.me/oauth/token"
RESOURCE = "https://api.mapit.me/v1"
LOCATION_SCOPE = "mapit:location:read"
SCOPES = ("mapit:read", LOCATION_SCOPE, "offline_access")

# Mapit allows 30 requests a minute per token and asks integrations to poll at most once a minute.
UPDATE_INTERVAL = timedelta(seconds=60)
VEHICLES_INTERVAL = timedelta(hours=1)

# Fired on the event bus once per Mapit alert.
ALERT_EVENT = f"{DOMAIN}_alert"
