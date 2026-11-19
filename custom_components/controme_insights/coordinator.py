"""Data update coordinators: one per Controme endpoint, each with its own interval."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta

from aiocontrome import (
    ContromeAuthError,
    ContromeClient,
    ContromeError,
    Fps,
    House,
    Output,
    RoomDetails,
    SystemInfo,
    UpcomingOffsets,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    TimestampDataUpdateCoordinator,
    UpdateFailed,
)

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


@dataclass
class ContromeRuntimeData:
    """Everything a config entry needs at runtime (``entry.runtime_data``)."""

    client: ContromeClient
    info: SystemInfo
    house: ContromeCoordinator[House]
    """``temps/``: floors, rooms, sensors."""
    outputs: ContromeCoordinator[tuple[Output, ...]]
    """``outs/``: valve outputs."""
    room_details: ContromeCoordinator[tuple[RoomDetails, ...]]
    """``room_details/`` (Basic Auth, undocumented): may fail on older firmware."""
    upcoming: ContromeCoordinator[UpcomingOffsets]
    fps: ContromeCoordinator[Mapping[int, Fps]]


type ContromeConfigEntry = ConfigEntry[ContromeRuntimeData]


class ContromeCoordinator[T](TimestampDataUpdateCoordinator[T]):
    """Polls one endpoint. Its entities become unavailable only if this endpoint fails.

    ``last_update_success_time`` is shown in the diagnostics.
    """

    config_entry: ContromeConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ContromeConfigEntry,
        *,
        name: str,
        interval: timedelta,
        fetch: Callable[[], Awaitable[T]],
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {name}",
            update_interval=interval,
        )
        self._fetch = fetch

    async def _async_update_data(self) -> T:
        try:
            return await self._fetch()
        except ContromeAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ContromeError as err:
            raise UpdateFailed(str(err)) from err
