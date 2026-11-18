"""Options flow tests: every menu item round trip on a running entry."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from aiocontrome.parsers import parse_temps
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.controme_insights.const import (
    CONF_GATEWAYS,
    CONF_ROOMS,
    CONF_SYSTEM_SENSORS,
    CONF_WRITE_OFFSET,
    CONF_WRITE_QUICKUI,
    DOMAIN,
)

from .conftest import ENTRY_DATA, ENTRY_OPTIONS, SYSTEM_SENSORS, TZ, load_fixture


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


async def _open(hass: HomeAssistant, entry: MockConfigEntry, item: str) -> dict[str, Any]:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": item}
    )
    assert result["type"] is FlowResultType.FORM
    return dict(result)


def _entry(changes: dict[str, Any]) -> MockConfigEntry:
    return MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, options={**ENTRY_OPTIONS, **changes})


def _default(result: Any, key: str) -> Any:
    for marker in result["data_schema"].schema:
        if marker == key:
            return marker.default() if callable(marker.default) else None
    raise KeyError(key)


async def _finish(
    hass: HomeAssistant, entry: MockConfigEntry, result: Any, user_input: dict[str, Any]
) -> None:
    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED  # reloaded


async def test_menu(
    hass: HomeAssistant, mock_client: MagicMock, config_entry: MockConfigEntry
) -> None:
    await _setup(hass, config_entry)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["menu_options"] == ["rooms", "system_sensors", "gateways", "writes"]


async def test_menu_without_system_sensors_and_outputs(
    hass: HomeAssistant, mock_client: MagicMock, config_entry: MockConfigEntry
) -> None:
    temps = [floor for floor in load_fixture("temps.json") if floor["id"] != 8]
    mock_client.get_house.return_value = parse_temps(temps, house_id=1, tz=TZ)
    mock_client.get_outputs.return_value = ()
    await _setup(hass, config_entry)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["menu_options"] == ["rooms", "writes"]


async def test_not_loaded_aborts(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_loaded"


async def test_rooms(
    hass: HomeAssistant, mock_client: MagicMock, config_entry: MockConfigEntry
) -> None:
    await _setup(hass, config_entry)
    result = await _open(hass, config_entry, "rooms")
    assert _default(result, CONF_ROOMS) == [str(r) for r in ENTRY_OPTIONS[CONF_ROOMS]]
    await _finish(hass, config_entry, result, {CONF_ROOMS: ["19", "26"]})
    assert config_entry.options == {**ENTRY_OPTIONS, CONF_ROOMS: [19, 26]}


async def test_rooms_drop_unknown_ids_and_default_without_option(
    hass: HomeAssistant, mock_client: MagicMock
) -> None:
    options = {k: v for k, v in ENTRY_OPTIONS.items() if k != CONF_ROOMS}
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, options=options)
    await _setup(hass, entry)
    result = await _open(hass, entry, "rooms")
    assert "26" not in _default(result, CONF_ROOMS)  # no option yet → controlled rooms


async def test_system_sensors(hass: HomeAssistant, mock_client: MagicMock) -> None:
    config_entry = _entry({CONF_SYSTEM_SENSORS: ["gone", SYSTEM_SENSORS[0]]})
    await _setup(hass, config_entry)
    result = await _open(hass, config_entry, "system_sensors")
    assert _default(result, CONF_SYSTEM_SENSORS) == [SYSTEM_SENSORS[0]]  # unknown ID dropped
    await _finish(hass, config_entry, result, {CONF_SYSTEM_SENSORS: SYSTEM_SENSORS[1:]})
    assert config_entry.options[CONF_SYSTEM_SENSORS] == SYSTEM_SENSORS[1:]


async def test_gateways_prefilled_from_current_config(
    hass: HomeAssistant, mock_client: MagicMock
) -> None:
    gateways = [
        {"name": "Gateway oben", "floors": [1, 5], "type": "relay"},
        {"name": "Gateway EG", "floors": [6], "type": "auto"},
    ]
    config_entry = _entry({CONF_GATEWAYS: gateways})
    await _setup(hass, config_entry)
    result = await _open(hass, config_entry, "gateways")
    assert result["step_id"] == "gateway"
    assert _default(result, "floors") == ["1", "5"]
    assert _default(result, "name") == "Gateway oben"
    assert _default(result, "type") == "relay"

    # Split the shared gateway: the old suggestion no longer fits for the rest.
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"floors": ["1"], "name": "Gateway DG", "type": "position"}
    )
    assert _default(result, "floors") == ["6"]  # Gateway EG still fits
    assert _default(result, "name") == "Gateway EG"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"floors": ["6"], "name": "Gateway EG", "type": "auto"}
    )
    assert _default(result, "floors") == ["5"]  # fresh suggestion
    assert _default(result, "name") == "Gateway 1. OG"
    assert _default(result, "type") == "position"  # 12 % seen

    await _finish(
        hass, config_entry, result, {"floors": ["5"], "name": "Gateway OG", "type": "position"}
    )
    assert config_entry.options[CONF_GATEWAYS] == [
        {"name": "Gateway DG", "floors": [1], "type": "position"},
        {"name": "Gateway EG", "floors": [6], "type": "auto"},
        {"name": "Gateway OG", "floors": [5], "type": "position"},
    ]


async def test_gateway_error(
    hass: HomeAssistant, mock_client: MagicMock, config_entry: MockConfigEntry
) -> None:
    await _setup(hass, config_entry)
    result = await _open(hass, config_entry, "gateways")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"floors": [], "name": "x", "type": "auto"}
    )
    assert result["errors"] == {"base": "no_floors"}


async def test_writes(
    hass: HomeAssistant, mock_client: MagicMock, config_entry: MockConfigEntry
) -> None:
    await _setup(hass, config_entry)
    result = await _open(hass, config_entry, "writes")
    assert _default(result, CONF_WRITE_OFFSET) is False
    await _finish(hass, config_entry, result, {CONF_WRITE_OFFSET: True, CONF_WRITE_QUICKUI: True})
    assert config_entry.options[CONF_WRITE_OFFSET] is True
    assert config_entry.options[CONF_WRITE_QUICKUI] is True
