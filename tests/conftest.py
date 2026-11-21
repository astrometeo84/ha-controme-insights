"""Shared fixtures. No network: the aiocontrome client is replaced by a mock that returns the
models parsed from the recorded fixtures in ``tests/fixtures``."""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from aiocontrome.parsers import (
    parse_fps,
    parse_info,
    parse_outs,
    parse_room_details,
    parse_temps,
    parse_upcoming_offsets,
)
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.controme_insights.const import (
    CONF_GATEWAYS,
    CONF_HOUSE_ID,
    CONF_ROOMS,
    CONF_SYSTEM_SENSORS,
    CONF_WRITE_OFFSET,
    CONF_WRITE_QUICKUI,
    DOMAIN,
)

FIXTURES = Path(__file__).parent / "fixtures"
TZ = ZoneInfo("Europe/Berlin")

HOST = "controme.test"
BASE_URL = f"http://{HOST}"
# Obviously fake credentials, so a search for them in logs, errors and diagnostics is unambiguous.
TEST_USER = "user-test"
TEST_PASSWORD = "pw-test-SECRET"
ENTRY_DATA = {
    CONF_HOST: HOST,
    CONF_USERNAME: TEST_USER,
    CONF_PASSWORD: TEST_PASSWORD,
    CONF_HOUSE_ID: 1,
}


def assert_no_credentials(text: str) -> None:
    """Assert that ``text`` (log, error message, diagnostics) contains no credentials."""
    assert TEST_PASSWORD not in text
    assert TEST_USER not in text


# Floors in the fixtures: 1 Dachgeschoss, 5 1. OG, 6 EG (with outputs), 8 Keller (none).
CONTROLLED_ROOMS = [1, 14, 16, 17, 18, 15, 19, 20, 23, 24]
SYSTEM_SENSORS = [
    "28_00_00_00_00_00_16_00",
    "28_00_00_00_00_00_17_00",
    "28_00_00_00_00_00_18_00",
    "12_00_00_00_00_00_00_0c",
]
ENTRY_OPTIONS = {
    CONF_ROOMS: CONTROLLED_ROOMS,
    CONF_SYSTEM_SENSORS: SYSTEM_SENSORS,
    CONF_GATEWAYS: [
        {"name": "Gateway DG", "floors": [1], "type": "position"},
        {"name": "Gateway OG", "floors": [5], "type": "position"},
        {"name": "Gateway EG", "floors": [6], "type": "position"},
    ],
    CONF_WRITE_OFFSET: False,
    CONF_WRITE_QUICKUI: False,
}


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Allow loading custom_components/controme_insights in every test."""


@pytest.fixture
def mock_client() -> Generator[MagicMock]:
    """Replace ``ContromeClient`` in the integration and in the config flow."""
    client = MagicMock()
    client.base_url = BASE_URL
    client.detect_house_id = AsyncMock(return_value=1)
    client.verify_credentials = AsyncMock(return_value=None)
    client.get_info = AsyncMock(return_value=parse_info(load_fixture("info.json"), TZ))
    client.get_house = AsyncMock(
        return_value=parse_temps(load_fixture("temps.json"), house_id=1, tz=TZ)
    )
    client.get_outputs = AsyncMock(return_value=parse_outs(load_fixture("outs_pro_a.json")))
    client.get_room_details = AsyncMock(
        return_value=parse_room_details(load_fixture("room_details_morning.json"), TZ)
    )
    client.get_upcoming_offsets = AsyncMock(
        return_value=parse_upcoming_offsets(load_fixture("upcomingoffsets.json"), TZ)
    )
    client.get_fps = AsyncMock(return_value=parse_fps(load_fixture("fps.json"), TZ))
    with (
        patch("custom_components.controme_insights.ContromeClient", return_value=client),
        patch(
            "custom_components.controme_insights.config_flow.ContromeClient",
            return_value=client,
        ),
    ):
        yield client


@pytest.fixture
def config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"Controme ({HOST})",
        data=ENTRY_DATA,
        options=ENTRY_OPTIONS,
        unique_id=BASE_URL,
    )
