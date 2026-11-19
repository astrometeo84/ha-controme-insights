"""Diagnostics tests: everything secret or identifying is redacted."""

from __future__ import annotations

import json
import re
from typing import Any
from unittest.mock import MagicMock

from aiocontrome import REDACTED, ContromeConnectionError
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.controme_insights.const import (
    CONF_GATEWAYS,
    CONF_HOUSE_ID,
    CONF_ROOMS,
    CONF_SYSTEM_SENSORS,
)
from custom_components.controme_insights.diagnostics import async_get_config_entry_diagnostics

from .conftest import (
    BASE_URL,
    ENTRY_OPTIONS,
    HOST,
    SYSTEM_SENSORS,
    TEST_PASSWORD,
    TEST_USER,
    assert_no_credentials,
)

SENSOR_ID = re.compile(r"[0-9a-f]{2}(?:_[0-9a-f]{2}){7}", re.IGNORECASE)
MAC = re.compile(r"[0-9a-f]{2}(?::[0-9a-f]{2}){3,5}", re.IGNORECASE)


async def _diagnostics(hass: HomeAssistant, entry: MockConfigEntry) -> dict[str, Any]:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return await async_get_config_entry_diagnostics(hass, entry)


def _assert_redacted(diagnostics: dict[str, Any]) -> str:
    text = json.dumps(diagnostics)  # also proves it is plain JSON
    assert_no_credentials(text)
    assert HOST not in text
    assert SENSOR_ID.search(text) is None
    assert MAC.search(text) is None
    return text


async def test_diagnostics_are_redacted(
    hass: HomeAssistant, mock_client: MagicMock, config_entry: MockConfigEntry
) -> None:
    diagnostics = await _diagnostics(hass, config_entry)
    _assert_redacted(diagnostics)

    entry = diagnostics["entry"]
    assert entry["title"] == REDACTED
    assert entry["data"] == {
        CONF_HOST: REDACTED,
        CONF_USERNAME: REDACTED,
        CONF_PASSWORD: REDACTED,
        CONF_HOUSE_ID: 1,
    }
    # Options keep their structure; only the sensor IDs become placeholders.
    options = entry["options"]
    assert options[CONF_ROOMS] == ENTRY_OPTIONS[CONF_ROOMS]
    assert options[CONF_GATEWAYS] == ENTRY_OPTIONS[CONF_GATEWAYS]
    assert len(options[CONF_SYSTEM_SENSORS]) == len(SYSTEM_SENSORS)
    assert all(s.startswith("**") for s in options[CONF_SYSTEM_SENSORS])

    # Same placeholder for the same sensor in options and data.
    temps = json.dumps(diagnostics["data"]["temps"])
    assert all(placeholder in temps for placeholder in options[CONF_SYSTEM_SENSORS])

    assert diagnostics["info"]["branch"] == "uiv2"
    assert set(diagnostics["coordinators"]) == {
        "temps",
        "outs",
        "room_details",
        "upcomingoffsets",
        "fps",
    }
    for status in diagnostics["coordinators"].values():
        assert status["last_update_success"] is True
        assert status["last_update_success_time"] is not None
        assert status["last_exception"] is None
    assert diagnostics["data"]["temps"]["floors"]


async def test_diagnostics_error_text_is_scrubbed(
    hass: HomeAssistant, mock_client: MagicMock, config_entry: MockConfigEntry
) -> None:
    # Defence in depth: even if an error text carried host or credentials, they are removed.
    mock_client.get_room_details.side_effect = ContromeConnectionError(
        f"Error requesting {BASE_URL}/get/json/v1/1/room_details/: "
        f"{TEST_USER} {TEST_PASSWORD} 192.0.2.10 username"
    )
    diagnostics = await _diagnostics(hass, config_entry)
    _assert_redacted(diagnostics)
    status = diagnostics["coordinators"]["room_details"]
    assert status["last_update_success"] is False
    assert status["last_update_success_time"] is None
    assert status["last_exception"] == (
        f"UpdateFailed: Error requesting {REDACTED}/get/json/v1/1/room_details/: "
        f"{REDACTED} {REDACTED} {REDACTED} username"
    )
    assert diagnostics["data"]["room_details"] is None
