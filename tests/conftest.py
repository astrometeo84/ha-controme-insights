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

from custom_components.controme_insights.const import CONF_HOUSE_ID, DOMAIN

FIXTURES = Path(__file__).parent / "fixtures"
TZ = ZoneInfo("Europe/Berlin")

HOST = "controme.test"
BASE_URL = f"http://{HOST}"
ENTRY_DATA = {
    CONF_HOST: HOST,
    CONF_USERNAME: "user",
    CONF_PASSWORD: "secret",
    CONF_HOUSE_ID: 1,
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
        domain=DOMAIN, title=f"Controme ({HOST})", data=ENTRY_DATA, unique_id=BASE_URL
    )
