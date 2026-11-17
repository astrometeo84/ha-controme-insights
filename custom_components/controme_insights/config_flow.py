"""Config flow for Controme Insights."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import probatio
from aiocontrome import (
    ContromeApiDisabledError,
    ContromeAuthError,
    ContromeClient,
    ContromeConnectionError,
    ContromeError,
    ContromeResponseError,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.util import dt as dt_util

from .const import CONF_HOUSE_ID, DOMAIN

_LOGGER = logging.getLogger(__name__)

_PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))

STEP_USER_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_HOST): str,
        probatio.Required(CONF_USERNAME): str,
        probatio.Required(CONF_PASSWORD): _PASSWORD,
    }
)


def _client(
    hass: HomeAssistant, host: str, username: str, password: str, house_id: int | None = None
) -> ContromeClient:
    return ContromeClient(
        async_get_clientsession(hass),
        host,
        timezone=dt_util.get_default_time_zone(),
        house_id=house_id,
        username=username,
        password=password,
    )


async def _validate(client: ContromeClient, house_id: int | None = None) -> int:
    """Check the credentials and return the house ID (detected unless ``house_id`` is given).

    ``room_details`` is the only read endpoint with authentication, so it verifies the
    credentials. If it fails for another reason (e.g. older firmware), setup continues: only
    the entities based on it will be unavailable.
    """
    if house_id is None:
        house_id = await client.detect_house_id()
    try:
        await client.get_room_details()
    except ContromeAuthError:
        raise
    except ContromeResponseError as err:
        _LOGGER.info("room_details/ not available, continuing without it: %s", err)
    return house_id


def _error_key(err: Exception) -> str:
    """Translation key of the form error for ``err``."""
    if isinstance(err, ContromeAuthError):
        return "invalid_auth"
    if isinstance(err, ContromeApiDisabledError):
        return "api_disabled"
    if isinstance(err, ContromeConnectionError):
        return "cannot_connect"
    if isinstance(err, ContromeError):
        return "no_house"
    _LOGGER.exception("Unexpected error while connecting to Controme")
    return "unknown"


class ContromeInsightsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the setup of Controme Insights."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Connection: host and credentials; the house ID is detected."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            client = _client(self.hass, host, user_input[CONF_USERNAME], user_input[CONF_PASSWORD])
            await self.async_set_unique_id(client.base_url)
            self._abort_if_unique_id_configured()
            try:
                house_id = await _validate(client)
            except Exception as err:  # mapped to a form error
                errors["base"] = _error_key(err)
            else:
                return self.async_create_entry(
                    title=f"Controme ({host})",
                    data={**user_input, CONF_HOST: host, CONF_HOUSE_ID: house_id},
                )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(STEP_USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Credentials were rejected (HTTP 401/403)."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for new credentials."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            client = _client(
                self.hass,
                entry.data[CONF_HOST],
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
                entry.data[CONF_HOUSE_ID],
            )
            try:
                await _validate(client, entry.data[CONF_HOUSE_ID])
            except Exception as err:  # mapped to a form error
                errors["base"] = _error_key(err)
            else:
                return self.async_update_reload_and_abort(entry, data_updates=user_input)
        schema = probatio.Schema(
            {
                probatio.Required(CONF_USERNAME, default=entry.data[CONF_USERNAME]): str,
                probatio.Required(CONF_PASSWORD): _PASSWORD,
            }
        )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=schema,
            errors=errors,
            description_placeholders={"host": entry.data[CONF_HOST]},
        )
