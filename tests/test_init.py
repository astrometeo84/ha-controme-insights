"""Setup and unload tests."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest
from aiocontrome import ContromeAuthError, ContromeConnectionError, ContromeNotFoundError
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.controme_insights.const import DOMAIN

from .conftest import assert_no_credentials


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _reauth_flows(hass: HomeAssistant) -> list[object]:
    return [
        flow
        for flow in hass.config_entries.flow.async_progress()
        if flow["handler"] == DOMAIN and flow["context"]["source"] == SOURCE_REAUTH
    ]


async def test_setup_and_unload(
    hass: HomeAssistant, mock_client: MagicMock, config_entry: MockConfigEntry
) -> None:
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED

    data = config_entry.runtime_data
    assert data.info.branch == "uiv2"
    assert len(data.house.data.rooms) > 0
    assert len(data.outputs.data) > 0
    assert len(data.room_details.data) > 0
    assert data.upcoming.data.houses
    assert len(data.fps.data) == 11

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_and_polling_never_verify_credentials(
    hass: HomeAssistant, mock_client: MagicMock, config_entry: MockConfigEntry
) -> None:
    # verify_credentials() is a POST to a write endpoint: only the flows may call it.
    await _setup(hass, config_entry)
    data = config_entry.runtime_data
    for coordinator in (data.house, data.outputs, data.room_details, data.upcoming, data.fps):
        await coordinator.async_refresh()
    assert mock_client.get_house.await_count >= 2  # polled again
    mock_client.verify_credentials.assert_not_awaited()


@pytest.mark.parametrize("method", ["get_info", "get_house", "get_outputs"])
async def test_required_source_failure_retries_setup(
    hass: HomeAssistant, mock_client: MagicMock, config_entry: MockConfigEntry, method: str
) -> None:
    getattr(mock_client, method).side_effect = ContromeConnectionError("Timeout")
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


@pytest.mark.parametrize("method", ["get_room_details", "get_upcoming_offsets", "get_fps"])
async def test_optional_source_failure_keeps_entry_loaded(
    hass: HomeAssistant, mock_client: MagicMock, config_entry: MockConfigEntry, method: str
) -> None:
    getattr(mock_client, method).side_effect = ContromeNotFoundError("HTTP 404", status=404)
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    data = config_entry.runtime_data
    coordinators = {
        "get_room_details": data.room_details,
        "get_upcoming_offsets": data.upcoming,
        "get_fps": data.fps,
    }
    assert coordinators[method].last_update_success is False
    assert data.house.last_update_success is True


async def test_auth_error_on_info_starts_reauth(
    hass: HomeAssistant, mock_client: MagicMock, config_entry: MockConfigEntry
) -> None:
    mock_client.get_info.side_effect = ContromeAuthError("HTTP 401", status=401)
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    assert len(_reauth_flows(hass)) == 1


async def test_auth_error_on_room_details_starts_reauth(
    hass: HomeAssistant, mock_client: MagicMock, config_entry: MockConfigEntry
) -> None:
    # The tested firmware does not check credentials on reads (live test 2026-11-20); firmware
    # that does answers 401/403 even after aiocontrome's Basic Auth retry → reauth.
    mock_client.get_room_details.side_effect = ContromeAuthError("HTTP 403", status=403)
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    assert len(_reauth_flows(hass)) == 1


@pytest.mark.parametrize(
    ("error", "state"),
    [
        (ContromeAuthError("HTTP 401", status=401), ConfigEntryState.SETUP_ERROR),
        (
            ContromeConnectionError("Timeout requesting http://controme.test/"),
            ConfigEntryState.SETUP_RETRY,
        ),
    ],
)
async def test_setup_failure_does_not_leak_credentials(
    hass: HomeAssistant,
    mock_client: MagicMock,
    config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
    error: Exception,
    state: ConfigEntryState,
) -> None:
    caplog.set_level(logging.DEBUG)
    mock_client.get_info.side_effect = error
    await _setup(hass, config_entry)
    assert config_entry.state is state
    assert config_entry.reason is not None
    assert_no_credentials(config_entry.reason)
    assert_no_credentials(caplog.text)


async def test_coordinator_failure_does_not_leak_credentials(
    hass: HomeAssistant,
    mock_client: MagicMock,
    config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    mock_client.get_room_details.side_effect = ContromeAuthError("HTTP 403", status=403)
    await _setup(hass, config_entry)
    assert config_entry.runtime_data.room_details.last_update_success is False
    assert_no_credentials(caplog.text)
