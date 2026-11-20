"""Diagnostics tests: everything secret or identifying is redacted."""

from __future__ import annotations

import base64
import html
import json
import re
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock
from urllib.parse import quote, quote_plus

import pytest
from aiocontrome import REDACTED, ContromeConnectionError
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.controme_insights.const import (
    CONF_GATEWAYS,
    CONF_HOUSE_ID,
    CONF_ROOMS,
    CONF_SYSTEM_SENSORS,
    DOMAIN,
)
from custom_components.controme_insights.diagnostics import (
    _Scrubber,
    async_get_config_entry_diagnostics,
)

from .conftest import (
    BASE_URL,
    ENTRY_DATA,
    ENTRY_OPTIONS,
    HOST,
    SYSTEM_SENSORS,
    TEST_PASSWORD,
    TEST_USER,
    assert_no_credentials,
)

SENSOR_ID = re.compile(r"[0-9a-f]{2}(?:_[0-9a-f]{2}){7}", re.IGNORECASE)
MAC = re.compile(r"[0-9a-f]{2}(?::[0-9a-f]{2}){3,5}", re.IGNORECASE)
IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
SPECIAL_PASSWORD = "pw&test+SECRET%"
"""Changes under HTML escaping and URL encoding."""


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
    assert IPV4.search(text) is None
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
    assert options[CONF_SYSTEM_SENSORS] == [
        "**onewire_temperature_1**",
        "**onewire_temperature_2**",
        "**onewire_temperature_3**",
        "**virtual_1**",
    ]

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
        assert datetime.fromisoformat(status["last_update_success_time"]).tzinfo is not None
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


async def test_diagnostics_platform_is_registered(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    mock_client: MagicMock,
    config_entry: MockConfigEntry,
) -> None:
    # Through Home Assistant's diagnostics component, as the "Download diagnostics" button.
    assert await async_setup_component(hass, "diagnostics", {})
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, config_entry)
    _assert_redacted(diagnostics)
    assert diagnostics["entry"]["title"] == REDACTED


async def test_diagnostics_scrub_encoded_password_forms(
    hass: HomeAssistant, mock_client: MagicMock
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=f"Controme ({HOST})",
        data={**ENTRY_DATA, CONF_PASSWORD: SPECIAL_PASSWORD},
        options=ENTRY_OPTIONS,
        unique_id=BASE_URL,
    )
    token = base64.b64encode(f"{TEST_USER}:{SPECIAL_PASSWORD}".encode()).decode()
    forms = [
        SPECIAL_PASSWORD,
        html.escape(SPECIAL_PASSWORD),
        quote(SPECIAL_PASSWORD),
        quote_plus(SPECIAL_PASSWORD),
        f"Basic {token}",
        token,
    ]
    mock_client.get_fps.side_effect = ContromeConnectionError("echo: " + " | ".join(forms))
    diagnostics = await _diagnostics(hass, entry)
    text = _assert_redacted(diagnostics)
    for form in forms:
        assert form not in text
    assert diagnostics["coordinators"]["fps"]["last_exception"] == (
        "UpdateFailed: echo: " + " | ".join([REDACTED] * len(forms))
    )


@pytest.mark.parametrize(
    ("username", "password", "text", "expected"),
    [
        pytest.param("", "", "user-test pw-test-SECRET", "user-test pw-test-SECRET", id="empty"),
        pytest.param(
            "", "pw-test-SECRET", "pw-test-SECRET user", f"{REDACTED} user", id="no_username"
        ),
        pytest.param(
            "u:x",
            "pw-test-SECRET",
            "u:x pw-test-SECRET",
            f"{REDACTED} {REDACTED}",
            id="username_with_colon",
        ),
    ],
)
def test_scrubber_edge_cases(username: str, password: str, text: str, expected: str) -> None:
    # Empty values are skipped; a colon in the username prevents a Basic Auth token.
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: "controme.test", CONF_USERNAME: username, CONF_PASSWORD: password},
    )
    assert _Scrubber(entry, "http://controme.test")(text) == expected
