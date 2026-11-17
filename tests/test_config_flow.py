"""Config flow tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiocontrome import (
    ContromeApiDisabledError,
    ContromeAuthError,
    ContromeConnectionError,
    ContromeError,
    ContromeNotFoundError,
)
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.controme_insights.const import CONF_HOUSE_ID, DOMAIN

from .conftest import ENTRY_DATA, HOST

USER_INPUT = {CONF_HOST: f" {HOST} ", CONF_USERNAME: "user", CONF_PASSWORD: "secret"}


@pytest.fixture(autouse=True)
def mock_setup_entry() -> Generator[AsyncMock]:
    """Test the flow alone: do not set up the created entry."""
    with patch(
        "custom_components.controme_insights.async_setup_entry", return_value=True
    ) as setup_entry:
        yield setup_entry


async def _start(hass: HomeAssistant) -> str:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}
    return str(result["flow_id"])


async def test_user_flow_creates_entry(hass: HomeAssistant, mock_client: MagicMock) -> None:
    mock_client.detect_house_id.return_value = 2
    flow_id = await _start(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"Controme ({HOST})"
    assert result["data"] == {**ENTRY_DATA, CONF_HOUSE_ID: 2}  # host is stripped
    assert result["result"].unique_id == "http://controme.test"
    mock_client.get_room_details.assert_awaited_once()  # verifies the credentials


async def test_room_details_unavailable_does_not_block_setup(
    hass: HomeAssistant, mock_client: MagicMock
) -> None:
    # Older firmware without the undocumented endpoint: continue without it.
    mock_client.get_room_details.side_effect = ContromeNotFoundError("HTTP 404", status=404)
    flow_id = await _start(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize(
    ("method", "error", "key"),
    [
        ("get_room_details", ContromeAuthError("HTTP 401", status=401), "invalid_auth"),
        ("detect_house_id", ContromeConnectionError("Timeout"), "cannot_connect"),
        ("detect_house_id", ContromeApiDisabledError("disabled"), "api_disabled"),
        ("detect_house_id", ContromeError("No house with rooms found"), "no_house"),
        ("detect_house_id", RuntimeError("boom"), "unknown"),
    ],
)
async def test_user_flow_errors_and_recovery(
    hass: HomeAssistant, mock_client: MagicMock, method: str, error: Exception, key: str
) -> None:
    getattr(mock_client, method).side_effect = error
    flow_id = await _start(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": key}

    getattr(mock_client, method).side_effect = None
    result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_duplicate_host_aborts(
    hass: HomeAssistant, mock_client: MagicMock, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    flow_id = await _start(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    mock_client.detect_house_id.assert_not_awaited()


async def test_reauth_updates_credentials(
    hass: HomeAssistant, mock_client: MagicMock, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    assert result["description_placeholders"]["host"] == HOST

    mock_client.get_room_details.side_effect = ContromeAuthError("HTTP 403", status=403)
    new = {CONF_USERNAME: "user2", CONF_PASSWORD: "new"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], new)
    assert result["errors"] == {"base": "invalid_auth"}

    mock_client.get_room_details.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], new)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data == {**ENTRY_DATA, **new}
    mock_client.detect_house_id.assert_not_awaited()  # house ID of the entry is kept
