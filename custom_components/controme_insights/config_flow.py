"""Config flow and options flow for Controme Insights.

Setup: connection → rooms → system sensors → gateways (one form per gateway until every floor
with outputs is assigned) → write functions. The options flow offers the same steps (except the
connection) in a menu; each one is saved on its own and reloads the entry.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

import probatio
from aiocontrome import (
    ContromeApiDisabledError,
    ContromeAuthError,
    ContromeClient,
    ContromeConnectionError,
    ContromeError,
    ContromeNotFoundError,
    ContromeResponseError,
    House,
    Output,
    OutputType,
    OutputTypeDetector,
    Sensor,
    SensorConnection,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.helpers.translation import async_get_translations
from homeassistant.util import dt as dt_util

from .const import (
    CONF_GATEWAYS,
    CONF_HOUSE_ID,
    CONF_ROOMS,
    CONF_SYSTEM_SENSORS,
    CONF_WRITE_OFFSET,
    CONF_WRITE_QUICKUI,
    DOMAIN,
    GATEWAY_FLOORS,
    GATEWAY_NAME,
    GATEWAY_TYPE,
    GATEWAY_TYPE_POSITION,
    GATEWAY_TYPES,
)

_LOGGER = logging.getLogger(__name__)

_PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))

STEP_USER_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_HOST): str,
        probatio.Required(CONF_USERNAME): str,
        probatio.Required(CONF_PASSWORD): _PASSWORD,
    }
)

MENU_ROOMS = "rooms"
MENU_SYSTEM_SENSORS = "system_sensors"
MENU_GATEWAYS = "gateways"
MENU_WRITES = "writes"


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


async def _connect(client: ContromeClient) -> tuple[int, House, tuple[Output, ...]]:
    """Validate a new connection: house ID, credentials, house and outputs."""
    house_id = await _validate(client)
    return house_id, await client.get_house(), await client.get_outputs()


class _WrongDevice(Exception):
    """The address answers, but not with the Controme system of the entry."""


async def _check_same_system(client: ContromeClient, house_id: int, rooms: Iterable[int]) -> None:
    """Plausibility check instead of a serial number (the API reports none).

    The stored house ID must exist at the address and contain at least one of the selected
    rooms (any room if none is selected). Credentials and API are verified as in the setup.
    """
    await _validate(client, house_id)
    try:
        house = await client.get_house()
    except ContromeNotFoundError as err:
        raise _WrongDevice from err
    await client.get_outputs()
    found = {room.id for room in house.rooms}
    selected = set(rooms)
    if not found or (selected and not found & selected):
        raise _WrongDevice


def _title(host: str) -> str:
    return f"Controme ({host})"


def _without_password(user_input: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Values to suggest again after a form error: never the password."""
    if user_input is None:
        return None
    return {key: value for key, value in user_input.items() if key != CONF_PASSWORD}


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


async def _selector_labels(hass: HomeAssistant, key: str) -> dict[str, str]:
    """Translated option labels of selector ``key`` (``selector.<key>.options``)."""
    translations = await async_get_translations(hass, hass.config.language, "selector", [DOMAIN])
    prefix = f"component.{DOMAIN}.selector.{key}.options."
    return {k.removeprefix(prefix): v for k, v in translations.items() if k.startswith(prefix)}


def _multi_select(options: list[SelectOptionDict]) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(options=options, multiple=True, mode=SelectSelectorMode.LIST)
    )


def _ints(values: Iterable[str]) -> list[int]:
    return [int(value) for value in values]


# --- Discovery ------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Discovery:
    """What the Controme system reports: the basis for every selection step."""

    house: House
    outputs: tuple[Output, ...]

    def floor_name(self, floor_id: int) -> str:
        return next((f.name for f in self.house.floors if f.id == floor_id), str(floor_id))

    def gateway_floors(self) -> list[int]:
        """Floors with outputs, in Controme order."""
        with_outputs = {output.floor_id for output in self.outputs}
        return [floor.id for floor in self.house.floors if floor.id in with_outputs]

    def detected_type(self, floor_id: int) -> OutputType:
        detector = OutputTypeDetector()
        detector.observe_outputs(self.outputs)
        return detector.type_for(floor_id)

    def default_rooms(self) -> list[int]:
        return [room.id for room in self.house.rooms if room.is_controlled]

    def system_sensors(self) -> tuple[Sensor, ...]:
        return self.house.system_sensors


# --- Step helpers shared by the config flow and the options flow ------------------------------


def _rooms_schema(discovery: _Discovery, selected: Iterable[int]) -> probatio.Schema:
    known = {room.id for room in discovery.house.rooms}
    options = [
        SelectOptionDict(
            value=str(room.id), label=f"{discovery.floor_name(room.floor_id)} · {room.name}"
        )
        for room in discovery.house.rooms
    ]
    default = [str(room_id) for room_id in selected if room_id in known]
    return probatio.Schema({probatio.Required(CONF_ROOMS, default=default): _multi_select(options)})


def _sensor_label(sensor: Sensor, connections: Mapping[str, str]) -> str:
    unit = "%" if sensor.connection is SensorConnection.ONEWIRE_HUMIDITY else "°C"
    value = "-" if sensor.value is None else f"{sensor.value:.1f} {unit}"
    connection = connections.get(sensor.connection.value, sensor.connection.value)
    return f"{sensor.description} · {value} · {connection}"


async def _system_sensors_schema(
    hass: HomeAssistant, discovery: _Discovery, selected: Iterable[str]
) -> probatio.Schema:
    connections = await _selector_labels(hass, "connection")
    sensors = discovery.system_sensors()
    options = [
        SelectOptionDict(value=sensor.id, label=_sensor_label(sensor, connections))
        for sensor in sensors
    ]
    known = {sensor.id for sensor in sensors}
    default = [sensor_id for sensor_id in selected if sensor_id in known]
    return probatio.Schema(
        {probatio.Required(CONF_SYSTEM_SENSORS, default=default): _multi_select(options)}
    )


def _writes_schema(options: Mapping[str, Any]) -> probatio.Schema:
    return probatio.Schema(
        {
            probatio.Required(
                CONF_WRITE_OFFSET, default=options.get(CONF_WRITE_OFFSET, False)
            ): BooleanSelector(),
            probatio.Required(
                CONF_WRITE_QUICKUI, default=options.get(CONF_WRITE_QUICKUI, False)
            ): BooleanSelector(),
        }
    )


@dataclass
class _GatewayLoop:
    """Assigns the floors with outputs to gateways, one form per gateway.

    The API never names gateways and output numbers restart per gateway; the default is one
    gateway per floor, and several floors may share one.
    """

    discovery: _Discovery
    previous: list[dict[str, Any]]
    """Gateways configured before (options flow): used as suggestions while they still fit."""
    unassigned: list[int]
    gateways: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def start(
        cls, discovery: _Discovery, previous: Iterable[Mapping[str, Any]] = ()
    ) -> _GatewayLoop:
        return cls(discovery, [dict(gw) for gw in previous], discovery.gateway_floors())

    @property
    def done(self) -> bool:
        return not self.unassigned

    def suggestion(self) -> dict[str, Any]:
        """Floors, name and type to prefill; type is ``None`` if it cannot be detected."""
        for gateway in self.previous:
            floors = gateway.get(GATEWAY_FLOORS) or []
            if floors and set(floors) <= set(self.unassigned):
                return {
                    GATEWAY_FLOORS: list(floors),
                    GATEWAY_NAME: gateway.get(GATEWAY_NAME, ""),
                    GATEWAY_TYPE: gateway.get(GATEWAY_TYPE),
                }
        floor_id = self.unassigned[0]
        detected = self.discovery.detected_type(floor_id)
        return {
            GATEWAY_FLOORS: [floor_id],
            GATEWAY_NAME: f"Gateway {self.discovery.floor_name(floor_id)}",
            GATEWAY_TYPE: GATEWAY_TYPE_POSITION if detected is OutputType.POSITION else None,
        }

    def schema(self) -> probatio.Schema:
        suggestion = self.suggestion()
        floors = [
            SelectOptionDict(value=str(floor_id), label=self.discovery.floor_name(floor_id))
            for floor_id in self.unassigned
        ]
        gateway_type = suggestion[GATEWAY_TYPE]
        type_key = (
            probatio.Required(GATEWAY_TYPE, default=gateway_type)
            if gateway_type in GATEWAY_TYPES
            else probatio.Required(GATEWAY_TYPE)
        )
        return probatio.Schema(
            {
                probatio.Required(
                    GATEWAY_FLOORS, default=[str(f) for f in suggestion[GATEWAY_FLOORS]]
                ): _multi_select(floors),
                probatio.Required(GATEWAY_NAME, default=suggestion[GATEWAY_NAME]): TextSelector(),
                type_key: SelectSelector(
                    SelectSelectorConfig(
                        options=list(GATEWAY_TYPES),
                        translation_key="gateway_type",
                        mode=SelectSelectorMode.LIST,
                    )
                ),
            }
        )

    async def placeholders(self, hass: HomeAssistant) -> dict[str, str]:
        labels = await _selector_labels(hass, "detection")
        lines = []
        for floor_id in self.unassigned:
            detected = self.discovery.detected_type(floor_id).value
            lines.append(
                f"- {self.discovery.floor_name(floor_id)}: {labels.get(detected, detected)}"
            )
        return {"number": str(len(self.gateways) + 1), "floors": "\n".join(lines)}

    def add(self, user_input: Mapping[str, Any]) -> str | None:
        """Add a gateway from the form input; return an error key if the input is invalid."""
        floors = _ints(user_input[GATEWAY_FLOORS])
        name = str(user_input[GATEWAY_NAME]).strip()
        if not floors or not set(floors) <= set(self.unassigned):
            return "no_floors"
        if not name:
            return "no_name"
        ordered = [floor_id for floor_id in self.unassigned if floor_id in floors]
        self.gateways.append(
            {GATEWAY_NAME: name, GATEWAY_FLOORS: ordered, GATEWAY_TYPE: user_input[GATEWAY_TYPE]}
        )
        self.unassigned = [floor_id for floor_id in self.unassigned if floor_id not in floors]
        return None


# --- Config flow ------------------------------------------------------------------------------


class ContromeInsightsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the setup of Controme Insights."""

    VERSION = 1

    _data: dict[str, Any]
    _options: dict[str, Any]
    _discovery: _Discovery
    _gateways: _GatewayLoop

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> ContromeInsightsOptionsFlow:
        """Options flow: change the selections made during setup."""
        return ContromeInsightsOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Connection: host and credentials; the house ID is detected."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            client = _client(self.hass, host, user_input[CONF_USERNAME], user_input[CONF_PASSWORD])
            await self.async_set_unique_id(client.base_url)
            self._abort_if_unique_id_configured()
            try:
                house_id, house, outputs = await _connect(client)
            except Exception as err:  # mapped to a form error
                errors["base"] = _error_key(err)
            else:
                self._data = {**user_input, CONF_HOST: host, CONF_HOUSE_ID: house_id}
                self._options = {}
                self._discovery = _Discovery(house, outputs)
                return await self.async_step_rooms()
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA, _without_password(user_input)
            ),
            errors=errors,
        )

    async def async_step_rooms(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Rooms that get entities; rooms without control are deselected."""
        if user_input is not None:
            self._options[CONF_ROOMS] = _ints(user_input[CONF_ROOMS])
            return await self.async_step_system_sensors()
        return self.async_show_form(
            step_id="rooms",
            data_schema=_rooms_schema(self._discovery, self._discovery.default_rooms()),
        )

    async def async_step_system_sensors(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Sensors that serve no room; skipped if there are none."""
        sensors = self._discovery.system_sensors()
        if user_input is not None or not sensors:
            selected = user_input[CONF_SYSTEM_SENSORS] if user_input else []
            self._options[CONF_SYSTEM_SENSORS] = list(selected)
            self._gateways = _GatewayLoop.start(self._discovery)
            return await self.async_step_gateway()
        schema = await _system_sensors_schema(self.hass, self._discovery, [s.id for s in sensors])
        return self.async_show_form(step_id="system_sensors", data_schema=schema)

    async def async_step_gateway(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """One gateway: its floors, name and type. Repeats until every floor is assigned."""
        errors: dict[str, str] = {}
        if user_input is not None and (error := self._gateways.add(user_input)):
            errors["base"] = error
        else:
            user_input = None  # next gateway: fresh form
        if self._gateways.done:
            self._options[CONF_GATEWAYS] = self._gateways.gateways
            return await self.async_step_writes()
        return self.async_show_form(
            step_id="gateway",
            data_schema=self.add_suggested_values_to_schema(self._gateways.schema(), user_input),
            description_placeholders=await self._gateways.placeholders(self.hass),
            errors=errors,
        )

    async def async_step_writes(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Write functions (API offset/boost, quick operation); off by default."""
        if user_input is not None:
            self._options.update(user_input)
            return self.async_create_entry(
                title=_title(self._data[CONF_HOST]), data=self._data, options=self._options
            )
        return self.async_show_form(step_id="writes", data_schema=_writes_schema({}))

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

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change host (e.g. a new IP address) and credentials; the password is entered again.

        The API reports no serial number, so the new address is accepted if it holds the stored
        house with at least one of the selected rooms. The unique ID follows the new address.
        """
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            house_id = entry.data[CONF_HOUSE_ID]
            client = _client(
                self.hass, host, user_input[CONF_USERNAME], user_input[CONF_PASSWORD], house_id
            )
            unique_id = client.base_url
            if any(
                other.unique_id == unique_id and other.entry_id != entry.entry_id
                for other in self._async_current_entries(include_ignore=True)
            ):
                return self.async_abort(reason="already_configured")
            try:
                await _check_same_system(client, house_id, entry.options.get(CONF_ROOMS, []))
            except _WrongDevice:
                return self.async_abort(reason="wrong_device")
            except Exception as err:  # mapped to a form error
                errors["base"] = _error_key(err)
            else:
                # Keep a title the user has renamed; follow the host in the generated one.
                title = (
                    _title(host) if entry.title == _title(entry.data[CONF_HOST]) else entry.title
                )
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=unique_id,
                    title=title,
                    data_updates={**user_input, CONF_HOST: host},
                )
        suggested = _without_password(user_input) or {
            CONF_HOST: entry.data[CONF_HOST],
            CONF_USERNAME: entry.data[CONF_USERNAME],
        }
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(STEP_USER_SCHEMA, suggested),
            errors=errors,
            description_placeholders={"house_id": str(entry.data[CONF_HOUSE_ID])},
        )


# --- Options flow -----------------------------------------------------------------------------


class ContromeInsightsOptionsFlow(OptionsFlowWithReload):
    """Change rooms, system sensors, gateways and write functions; reloads after saving."""

    _discovery: _Discovery
    _gateways: _GatewayLoop

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Menu of the settings; uses the data of the running entry (no extra requests)."""
        entry = self.config_entry
        if entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")
        data = entry.runtime_data
        self._discovery = _Discovery(data.house.data, data.outputs.data)
        menu = [MENU_ROOMS]
        if self._discovery.system_sensors():
            menu.append(MENU_SYSTEM_SENSORS)
        if self._discovery.gateway_floors():
            menu.append(MENU_GATEWAYS)
        menu.append(MENU_WRITES)
        return self.async_show_menu(step_id="init", menu_options=menu)

    def _save(self, changes: Mapping[str, Any]) -> ConfigFlowResult:
        return self.async_create_entry(data={**self.config_entry.options, **changes})

    async def async_step_rooms(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Rooms that get entities."""
        if user_input is not None:
            return self._save({CONF_ROOMS: _ints(user_input[CONF_ROOMS])})
        selected = self.config_entry.options.get(CONF_ROOMS, self._discovery.default_rooms())
        return self.async_show_form(
            step_id="rooms", data_schema=_rooms_schema(self._discovery, selected)
        )

    async def async_step_system_sensors(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Sensors that serve no room."""
        if user_input is not None:
            return self._save({CONF_SYSTEM_SENSORS: list(user_input[CONF_SYSTEM_SENSORS])})
        selected = self.config_entry.options.get(CONF_SYSTEM_SENSORS, [])
        schema = await _system_sensors_schema(self.hass, self._discovery, selected)
        return self.async_show_form(step_id="system_sensors", data_schema=schema)

    async def async_step_gateways(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Assign all floors again, prefilled with the current gateways."""
        self._gateways = _GatewayLoop.start(
            self._discovery, self.config_entry.options.get(CONF_GATEWAYS, [])
        )
        return await self.async_step_gateway()

    async def async_step_gateway(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """One gateway: its floors, name and type. Repeats until every floor is assigned."""
        errors: dict[str, str] = {}
        if user_input is not None and (error := self._gateways.add(user_input)):
            errors["base"] = error
        else:
            user_input = None
        if self._gateways.done:
            return self._save({CONF_GATEWAYS: self._gateways.gateways})
        return self.async_show_form(
            step_id="gateway",
            data_schema=self.add_suggested_values_to_schema(self._gateways.schema(), user_input),
            description_placeholders=await self._gateways.placeholders(self.hass),
            errors=errors,
        )

    async def async_step_writes(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Write functions (API offset/boost, quick operation)."""
        if user_input is not None:
            return self._save(user_input)
        return self.async_show_form(
            step_id="writes", data_schema=_writes_schema(self.config_entry.options)
        )
