"""Config flow tests."""

from __future__ import annotations

import html
import logging
from collections.abc import Generator
from typing import Any, cast
from unittest.mock import ANY, AsyncMock, MagicMock, patch
from urllib.parse import quote, quote_plus

import pytest
from aiocontrome import (
    ContromeApiDisabledError,
    ContromeAuthError,
    ContromeConnectionError,
    ContromeError,
    ContromeNotFoundError,
    ContromeResponseError,
    SensorConnection,
)
from aiocontrome.parsers import parse_outs, parse_temps
from homeassistant.config_entries import SOURCE_IGNORE, SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.controme_insights import config_flow
from custom_components.controme_insights.config_flow import _sensor_label
from custom_components.controme_insights.const import (
    CONF_GATEWAYS,
    CONF_HOUSE_ID,
    CONF_ROOMS,
    CONF_SYSTEM_SENSORS,
    CONF_WRITE_OFFSET,
    CONF_WRITE_QUICKUI,
    DOMAIN,
)

from .conftest import (
    CONTROLLED_ROOMS,
    ENTRY_DATA,
    ENTRY_OPTIONS,
    HOST,
    SYSTEM_SENSORS,
    TEST_PASSWORD,
    TEST_USER,
    TZ,
    assert_no_credentials,
    load_fixture,
)

USER_INPUT = {CONF_HOST: f" {HOST} ", CONF_USERNAME: TEST_USER, CONF_PASSWORD: TEST_PASSWORD}
NEW_CREDENTIALS = {CONF_USERNAME: "user-test-2", CONF_PASSWORD: "pw-test-SECRET-2"}
# room_details/ answers that cannot be evaluated: setup fails closed (nothing is saved).
ROOM_DETAILS_INVALID = [
    pytest.param(ContromeNotFoundError("HTTP 404", status=404), id="404"),
    pytest.param(ContromeResponseError("Invalid JSON from …: <html>", status=200), id="html_200"),
    pytest.param(ContromeResponseError("HTTP 500", status=500), id="500"),
    # A debug page echoing the entered passwords in every form: must reach neither log nor form.
    pytest.param(
        ContromeResponseError(
            "HTTP 500: "
            + " ".join(
                form
                for password in (TEST_PASSWORD, NEW_CREDENTIALS[CONF_PASSWORD])
                for form in (password, html.escape(password), quote(password), quote_plus(password))
            )
            + f" user={TEST_USER}",
            status=500,
        ),
        id="500_echoing_credentials",
    ),
]


def _assert_no_secret_leak(caplog: pytest.LogCaptureFixture, result: Any) -> None:
    """Neither log nor form result contain a password that was entered in the flow."""
    assert_no_credentials(caplog.text)
    assert NEW_CREDENTIALS[CONF_PASSWORD] not in caplog.text
    assert TEST_PASSWORD not in repr(result)
    assert NEW_CREDENTIALS[CONF_PASSWORD] not in repr(result)


def _assert_client_created(host: str, house_id: int | None, credentials: dict[str, str]) -> None:
    """The flow built its client with exactly these values (the patched class records it)."""
    client_class = cast(MagicMock, vars(config_flow)["ContromeClient"])  # patched in conftest
    client_class.assert_called_with(
        ANY,
        host,
        timezone=ANY,
        house_id=house_id,
        username=credentials[CONF_USERNAME],
        password=credentials[CONF_PASSWORD],
    )


WRITES_OFF = {CONF_WRITE_OFFSET: False, CONF_WRITE_QUICKUI: False}


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


def _default(result: Any, key: str) -> Any:
    """Default value of field ``key`` in a form result; ``None`` if it has none."""
    for marker in result["data_schema"].schema:
        if marker == key:
            return marker.default() if callable(marker.default) else None
    raise KeyError(key)


def _suggested(result: Any, key: str) -> Any:
    """Suggested value of field ``key`` in a form result; ``None`` if it has none."""
    for marker in result["data_schema"].schema:
        if marker == key:
            return (marker.description or {}).get("suggested_value")
    raise KeyError(key)


def _options(result: Any, key: str) -> list[Any]:
    """Options of the select selector ``key`` in a form result."""
    for marker, selector in result["data_schema"].schema.items():
        if marker == key:
            return list(selector.config["options"])
    raise KeyError(key)


def _gateway(floors: list[int], name: str, gateway_type: str) -> dict[str, Any]:
    return {"floors": [str(f) for f in floors], "name": name, "type": gateway_type}


async def _connect(hass: HomeAssistant) -> dict[str, Any]:
    """Run the connection step; return the rooms form."""
    flow_id = await _start(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "rooms"
    return dict(result)


async def _to_gateways(hass: HomeAssistant) -> dict[str, Any]:
    """Accept the defaults for rooms and system sensors; return the first gateway form."""
    result = await _connect(hass)
    flow_id = result["flow_id"]
    rooms = _default(result, CONF_ROOMS)
    result = await hass.config_entries.flow.async_configure(flow_id, {CONF_ROOMS: rooms})
    sensors = _default(result, CONF_SYSTEM_SENSORS)
    result = await hass.config_entries.flow.async_configure(flow_id, {CONF_SYSTEM_SENSORS: sensors})
    assert result["step_id"] == "gateway"
    return dict(result)


async def test_full_flow_creates_entry(hass: HomeAssistant, mock_client: MagicMock) -> None:
    mock_client.detect_house_id.return_value = 2
    result = await _connect(hass)
    flow_id = result["flow_id"]
    mock_client.get_room_details.assert_awaited_once()  # verifies the credentials

    # Rooms: all listed, rooms without control (hk_verteiler, 26) deselected.
    assert [o["value"] for o in _options(result, CONF_ROOMS)][-1] == "26"
    assert _options(result, CONF_ROOMS)[0]["label"] == "Dachgeschoss · Büro"
    assert _default(result, CONF_ROOMS) == [str(r) for r in CONTROLLED_ROOMS]
    result = await hass.config_entries.flow.async_configure(flow_id, {CONF_ROOMS: ["1", "19"]})

    # System sensors: only sensors of rooms without control, all preselected.
    assert result["step_id"] == "system_sensors"
    assert [o["value"] for o in _options(result, CONF_SYSTEM_SENSORS)] == SYSTEM_SENSORS
    labels = [o["label"] for o in _options(result, CONF_SYSTEM_SENSORS)]
    assert labels[2] == "eg_hkv_vl · 23.5 °C · 1-Wire"
    assert labels[3].endswith("· virtual / foreign system")
    assert _default(result, CONF_SYSTEM_SENSORS) == SYSTEM_SENSORS
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_SYSTEM_SENSORS: SYSTEM_SENSORS[:3]}
    )

    # Gateway 1: Dachgeschoss, only zeros so far → type not prefilled.
    assert result["step_id"] == "gateway"
    assert result["description_placeholders"]["number"] == "1"
    floors = result["description_placeholders"]["floors"]
    assert "- Dachgeschoss: only 0/1 so far, cannot be detected" in floors
    assert "- 1. OG: valve positions seen (PRO 0-10 V)" in floors
    assert "Keller" not in floors  # no outputs
    assert _default(result, "floors") == ["1"]
    assert _default(result, "name") == "Gateway Dachgeschoss"
    assert _default(result, "type") is None
    with pytest.raises(InvalidData):  # type must be chosen
        await hass.config_entries.flow.async_configure(
            flow_id, {"floors": ["1"], "name": "Gateway DG"}
        )
    result = await hass.config_entries.flow.async_configure(
        flow_id, _gateway([1], "Gateway DG", "position")
    )

    # Gateway 2: 1. OG reported 12 % → PRO prefilled.
    assert result["description_placeholders"]["number"] == "2"
    assert _default(result, "floors") == ["5"]
    assert _default(result, "type") == "position"
    result = await hass.config_entries.flow.async_configure(
        flow_id, _gateway([5], "Gateway OG", "position")
    )

    # Gateway 3: EG → afterwards all floors are assigned.
    result = await hass.config_entries.flow.async_configure(
        flow_id, _gateway([6], "Gateway EG", "auto")
    )
    assert result["step_id"] == "writes"
    assert _default(result, CONF_WRITE_OFFSET) is False
    assert _default(result, CONF_WRITE_QUICKUI) is False
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_WRITE_OFFSET: True, CONF_WRITE_QUICKUI: False}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"Controme ({HOST})"
    assert result["data"] == {**ENTRY_DATA, CONF_HOUSE_ID: 2}  # host is stripped
    assert result["options"] == {
        CONF_ROOMS: [1, 19],
        CONF_SYSTEM_SENSORS: SYSTEM_SENSORS[:3],
        CONF_GATEWAYS: [
            {"name": "Gateway DG", "floors": [1], "type": "position"},
            {"name": "Gateway OG", "floors": [5], "type": "position"},
            {"name": "Gateway EG", "floors": [6], "type": "auto"},
        ],
        CONF_WRITE_OFFSET: True,
        CONF_WRITE_QUICKUI: False,
    }
    assert result["result"].unique_id == "http://controme.test"


async def test_floors_can_share_a_gateway(hass: HomeAssistant, mock_client: MagicMock) -> None:
    result = await _to_gateways(hass)
    flow_id = result["flow_id"]
    # Order of the floors follows Controme, not the selection.
    result = await hass.config_entries.flow.async_configure(
        flow_id, _gateway([5, 1], " Gateway oben ", "position")
    )
    assert result["description_placeholders"]["number"] == "2"
    assert [o["value"] for o in _options(result, "floors")] == ["6"]
    result = await hass.config_entries.flow.async_configure(
        flow_id, _gateway([6], "Gateway EG", "relay")
    )
    result = await hass.config_entries.flow.async_configure(flow_id, WRITES_OFF)
    assert result["options"][CONF_GATEWAYS] == [
        {"name": "Gateway oben", "floors": [1, 5], "type": "position"},
        {"name": "Gateway EG", "floors": [6], "type": "relay"},
    ]


@pytest.mark.parametrize(
    ("user_input", "error"),
    [
        ({"floors": [], "name": "Gateway DG", "type": "auto"}, "no_floors"),
        ({"floors": ["1"], "name": "   ", "type": "auto"}, "no_name"),
    ],
)
async def test_gateway_errors_keep_the_input(
    hass: HomeAssistant, mock_client: MagicMock, user_input: dict[str, Any], error: str
) -> None:
    result = await _to_gateways(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input)
    assert result["step_id"] == "gateway"
    assert result["errors"] == {"base": error}
    assert result["description_placeholders"]["number"] == "1"
    # The entered values are suggested again.
    for marker in result["data_schema"].schema:
        if marker == "name":
            assert marker.description == {"suggested_value": user_input["name"]}


async def test_relay_floor_detected_as_unknown(hass: HomeAssistant, mock_client: MagicMock) -> None:
    # Relay gateways only report 0/1: the type cannot be detected, only EG has outputs.
    mock_client.get_outputs.return_value = parse_outs(load_fixture("synthetic_outs_relay.json"))
    result = await _to_gateways(hass)
    assert result["description_placeholders"]["floors"] == (
        "- EG: only 0/1 so far, cannot be detected"
    )
    assert _default(result, "type") is None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _gateway([6], "Gateway EG", "relay")
    )
    assert result["step_id"] == "writes"


async def test_steps_skipped_without_system_sensors_and_outputs(
    hass: HomeAssistant, mock_client: MagicMock
) -> None:
    temps = [floor for floor in load_fixture("temps.json") if floor["id"] != 8]  # no Keller
    mock_client.get_house.return_value = parse_temps(temps, house_id=1, tz=TZ)
    mock_client.get_outputs.return_value = ()
    result = await _connect(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_ROOMS: []})
    assert result["step_id"] == "writes"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], WRITES_OFF)
    assert result["options"] == {
        CONF_ROOMS: [],
        CONF_SYSTEM_SENSORS: [],
        CONF_GATEWAYS: [],
        **WRITES_OFF,
    }


def test_sensor_label_without_value_and_unknown_connection() -> None:
    rooms = {
        room.id: room for room in parse_temps(load_fixture("temps.json"), house_id=1, tz=TZ).rooms
    }
    humidity = next(
        s for s in rooms[16].sensors if s.connection is SensorConnection.ONEWIRE_HUMIDITY
    )
    assert _sensor_label(humidity, {}).split(" · ")[1].endswith(" %")
    radio = rooms[24].sensors[0]  # Vorratsraum: radio sensor without current value
    assert _sensor_label(radio, {}) == "keller_vorratsraum · - · radio_sensor"


@pytest.mark.parametrize("error", ROOM_DETAILS_INVALID)
async def test_user_flow_fails_closed_on_unusable_room_details(
    hass: HomeAssistant,
    mock_client: MagicMock,
    caplog: pytest.LogCaptureFixture,
    error: Exception,
) -> None:
    # Also 404 (e.g. older firmware without the undocumented endpoint): the credentials cannot
    # be verified, so nothing is created.
    caplog.set_level(logging.DEBUG)
    mock_client.get_room_details.side_effect = error
    flow_id = await _start(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "room_details_invalid"}
    assert _suggested(result, CONF_PASSWORD) is None
    assert hass.config_entries.async_entries(DOMAIN) == []
    _assert_no_secret_leak(caplog, result)

    # The form can be submitted again and succeeds once room_details/ answers.
    mock_client.get_room_details.side_effect = None
    result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
    assert result["step_id"] == "rooms"


@pytest.mark.parametrize(
    ("method", "error", "key"),
    [
        ("get_room_details", ContromeAuthError("HTTP 401", status=401), "invalid_auth"),
        ("detect_house_id", ContromeConnectionError("Timeout"), "cannot_connect"),
        ("detect_house_id", ContromeApiDisabledError("disabled"), "api_disabled"),
        ("detect_house_id", ContromeError("No house with rooms found"), "no_house"),
        ("detect_house_id", RuntimeError("boom"), "unknown"),
        ("get_house", ContromeConnectionError("Timeout"), "cannot_connect"),
        ("get_outputs", ContromeConnectionError("Timeout"), "cannot_connect"),
    ],
)
async def test_user_flow_errors_and_recovery(
    hass: HomeAssistant,
    mock_client: MagicMock,
    caplog: pytest.LogCaptureFixture,
    method: str,
    error: Exception,
    key: str,
) -> None:
    caplog.set_level(logging.DEBUG)
    getattr(mock_client, method).side_effect = error
    flow_id = await _start(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": key}
    # Host and username are suggested again, the password never.
    assert _suggested(result, CONF_HOST) == USER_INPUT[CONF_HOST]
    assert _suggested(result, CONF_USERNAME) == TEST_USER
    assert _suggested(result, CONF_PASSWORD) is None
    assert TEST_PASSWORD not in repr(result)
    assert_no_credentials(caplog.text)

    getattr(mock_client, method).side_effect = None
    result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
    assert result["step_id"] == "rooms"


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
    hass: HomeAssistant,
    mock_client: MagicMock,
    config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    assert result["description_placeholders"]["host"] == HOST

    assert _suggested(result, CONF_PASSWORD) is None
    assert _default(result, CONF_PASSWORD) is None  # the stored password is never prefilled

    mock_client.get_room_details.side_effect = ContromeAuthError("HTTP 403", status=403)
    new = NEW_CREDENTIALS
    result = await hass.config_entries.flow.async_configure(result["flow_id"], new)
    assert result["errors"] == {"base": "invalid_auth"}
    assert _suggested(result, CONF_PASSWORD) is None
    assert new[CONF_PASSWORD] not in repr(result)

    mock_client.get_room_details.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], new)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data == {**ENTRY_DATA, **new}
    mock_client.detect_house_id.assert_not_awaited()  # house ID of the entry is kept
    _assert_client_created(HOST, 1, new)  # stored host and house, new credentials
    assert_no_credentials(caplog.text)
    assert new[CONF_PASSWORD] not in caplog.text


@pytest.mark.parametrize("error", ROOM_DETAILS_INVALID)
async def test_reauth_fails_closed_on_unusable_room_details(
    hass: HomeAssistant,
    mock_client: MagicMock,
    config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
    error: Exception,
) -> None:
    caplog.set_level(logging.DEBUG)
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reauth_flow(hass)
    mock_client.get_room_details.side_effect = error
    result = await hass.config_entries.flow.async_configure(result["flow_id"], NEW_CREDENTIALS)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "room_details_invalid"}
    assert _suggested(result, CONF_PASSWORD) is None
    assert config_entry.data == ENTRY_DATA  # nothing saved
    _assert_no_secret_leak(caplog, result)

    mock_client.get_room_details.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], NEW_CREDENTIALS)
    assert result["reason"] == "reauth_successful"
    assert config_entry.data == {**ENTRY_DATA, **NEW_CREDENTIALS}


# --- Reconfigure ----------------------------------------------------------------------------

NEW_HOST = "192.0.2.20"


def _entry(*, title: str = f"Controme ({HOST})", rooms: list[int] | None = None) -> MockConfigEntry:
    options = dict(ENTRY_OPTIONS) if rooms is None else {**ENTRY_OPTIONS, CONF_ROOMS: rooms}
    return MockConfigEntry(
        domain=DOMAIN,
        title=title,
        data=ENTRY_DATA,
        options=options,
        unique_id=f"http://{HOST}",
    )


async def _start_reconfigure(hass: HomeAssistant, entry: MockConfigEntry) -> dict[str, Any]:
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert result["description_placeholders"] == {"house_id": "1"}
    # Host and username are suggested, the stored password never.
    assert _suggested(result, CONF_HOST) == HOST
    assert _suggested(result, CONF_USERNAME) == TEST_USER
    assert _suggested(result, CONF_PASSWORD) is None
    assert TEST_PASSWORD not in repr(result)
    return dict(result)


async def _reconfigure(
    hass: HomeAssistant, entry: MockConfigEntry, mock_client: MagicMock, host: str
) -> Any:
    result = await _start_reconfigure(hass, entry)
    mock_client.base_url = f"http://{host}"
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: f" {host} ", **NEW_CREDENTIALS}
    )


async def test_reconfigure_new_ip_address(
    hass: HomeAssistant,
    mock_client: MagicMock,
    config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    result = await _reconfigure(hass, config_entry, mock_client, NEW_HOST)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.unique_id == f"http://{NEW_HOST}"
    assert config_entry.title == f"Controme ({NEW_HOST})"  # generated title follows the host
    assert config_entry.data == {CONF_HOST: NEW_HOST, **NEW_CREDENTIALS, CONF_HOUSE_ID: 1}
    assert config_entry.options == ENTRY_OPTIONS  # options are kept
    mock_client.get_room_details.assert_awaited_once()  # credentials verified on the device
    mock_client.detect_house_id.assert_not_awaited()  # the stored house ID is checked instead
    _assert_client_created(NEW_HOST, 1, NEW_CREDENTIALS)  # new address, stored house
    assert_no_credentials(caplog.text)
    assert NEW_CREDENTIALS[CONF_PASSWORD] not in caplog.text


async def test_reconfigure_same_host_new_credentials(
    hass: HomeAssistant, mock_client: MagicMock
) -> None:
    config_entry = _entry(title="My heating")  # renamed by the user: kept
    result = await _reconfigure(hass, config_entry, mock_client, HOST)
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.unique_id == f"http://{HOST}"
    assert config_entry.title == "My heating"
    assert config_entry.data == {**ENTRY_DATA, **NEW_CREDENTIALS}


@pytest.mark.parametrize(
    "house",
    [
        pytest.param(ContromeNotFoundError("HTTP 404", status=404), id="house_id_missing"),
        # Synthetic: the answer to an unknown house ID is not recorded (404 and [] handled).
        pytest.param(parse_temps([], house_id=1, tz=TZ), id="house_without_rooms"),
    ],
)
async def test_reconfigure_house_not_found_aborts(
    hass: HomeAssistant, mock_client: MagicMock, config_entry: MockConfigEntry, house: Any
) -> None:
    if isinstance(house, Exception):
        mock_client.get_house.side_effect = house
    else:
        mock_client.get_house.return_value = house
    result = await _reconfigure(hass, config_entry, mock_client, NEW_HOST)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_device"
    assert config_entry.data == ENTRY_DATA
    assert config_entry.unique_id == f"http://{HOST}"


async def test_reconfigure_house_without_rooms_aborts_without_selection(
    hass: HomeAssistant, mock_client: MagicMock
) -> None:
    # No room selected: an empty house must still count as "not the same system".
    mock_client.get_house.return_value = parse_temps([], house_id=1, tz=TZ)
    config_entry = _entry(rooms=[])
    result = await _reconfigure(hass, config_entry, mock_client, NEW_HOST)
    assert result["reason"] == "wrong_device"
    assert config_entry.data == ENTRY_DATA


async def test_reconfigure_no_selected_room_found_aborts(
    hass: HomeAssistant, mock_client: MagicMock
) -> None:
    config_entry = _entry(rooms=[998, 999])
    result = await _reconfigure(hass, config_entry, mock_client, NEW_HOST)
    assert result["reason"] == "wrong_device"
    assert config_entry.data == ENTRY_DATA


async def test_reconfigure_without_selected_rooms_needs_any_room(
    hass: HomeAssistant, mock_client: MagicMock
) -> None:
    config_entry = _entry(rooms=[])
    result = await _reconfigure(hass, config_entry, mock_client, NEW_HOST)
    assert result["reason"] == "reconfigure_successful"


async def test_reconfigure_address_of_other_entry_aborts(
    hass: HomeAssistant, mock_client: MagicMock, config_entry: MockConfigEntry
) -> None:
    MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id=f"http://{NEW_HOST}").add_to_hass(
        hass
    )
    result = await _reconfigure(hass, config_entry, mock_client, NEW_HOST)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert config_entry.data == ENTRY_DATA
    mock_client.get_room_details.assert_not_awaited()  # aborted before contacting the device


async def test_reconfigure_address_of_ignored_entry_aborts(
    hass: HomeAssistant, mock_client: MagicMock, config_entry: MockConfigEntry
) -> None:
    MockConfigEntry(
        domain=DOMAIN, source=SOURCE_IGNORE, data={}, unique_id=f"http://{NEW_HOST}"
    ).add_to_hass(hass)
    result = await _reconfigure(hass, config_entry, mock_client, NEW_HOST)
    assert result["reason"] == "already_configured"
    assert config_entry.data == ENTRY_DATA
    mock_client.get_room_details.assert_not_awaited()  # aborted before contacting the device


@pytest.mark.parametrize("error", ROOM_DETAILS_INVALID)
async def test_reconfigure_fails_closed_on_unusable_room_details(
    hass: HomeAssistant,
    mock_client: MagicMock,
    config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
    error: Exception,
) -> None:
    # Checked before the house: even 404 shows room_details_invalid, not wrong_device.
    caplog.set_level(logging.DEBUG)
    mock_client.get_room_details.side_effect = error
    result = await _reconfigure(hass, config_entry, mock_client, NEW_HOST)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "room_details_invalid"}
    assert _suggested(result, CONF_PASSWORD) is None
    assert config_entry.data == ENTRY_DATA
    mock_client.get_house.assert_not_awaited()
    _assert_no_secret_leak(caplog, result)

    mock_client.get_room_details.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: NEW_HOST, **NEW_CREDENTIALS}
    )
    assert result["reason"] == "reconfigure_successful"


@pytest.mark.parametrize(
    ("method", "error", "key"),
    [
        ("get_room_details", ContromeAuthError("HTTP 401", status=401), "invalid_auth"),
        ("get_room_details", ContromeConnectionError("Timeout"), "cannot_connect"),
        ("get_house", ContromeApiDisabledError("disabled"), "api_disabled"),
        # Not a 404: e.g. another HTTP server at the new address → form error, no abort.
        ("get_house", ContromeResponseError("Invalid JSON from …", status=200), "no_house"),
        ("get_house", RuntimeError("boom"), "unknown"),
        ("get_outputs", ContromeConnectionError("Timeout"), "cannot_connect"),
    ],
)
async def test_reconfigure_errors_and_recovery(
    hass: HomeAssistant,
    mock_client: MagicMock,
    config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
    method: str,
    error: Exception,
    key: str,
) -> None:
    caplog.set_level(logging.DEBUG)
    getattr(mock_client, method).side_effect = error
    result = await _reconfigure(hass, config_entry, mock_client, NEW_HOST)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": key}
    assert _suggested(result, CONF_HOST) == f" {NEW_HOST} "
    assert _suggested(result, CONF_USERNAME) == NEW_CREDENTIALS[CONF_USERNAME]
    assert _suggested(result, CONF_PASSWORD) is None
    assert NEW_CREDENTIALS[CONF_PASSWORD] not in repr(result)
    assert config_entry.data == ENTRY_DATA  # nothing saved
    if key == "unknown":  # logged with traceback: still no credentials in it
        assert "Traceback" in caplog.text
        assert_no_credentials(caplog.text)
        assert NEW_CREDENTIALS[CONF_PASSWORD] not in caplog.text

    getattr(mock_client, method).side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: NEW_HOST, **NEW_CREDENTIALS}
    )
    assert result["reason"] == "reconfigure_successful"
    assert_no_credentials(caplog.text)
    assert NEW_CREDENTIALS[CONF_PASSWORD] not in caplog.text
