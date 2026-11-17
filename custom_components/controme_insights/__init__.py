"""Controme Insights: complements the official Controme integration."""

from __future__ import annotations

from aiocontrome import ContromeAuthError, ContromeClient, ContromeError
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .const import CONF_HOUSE_ID, FAST_INTERVAL, SLOW_INTERVAL
from .coordinator import ContromeConfigEntry, ContromeCoordinator, ContromeRuntimeData

PLATFORMS: list[Platform] = []


async def async_setup_entry(hass: HomeAssistant, entry: ContromeConfigEntry) -> bool:
    """Set up Controme Insights from a config entry."""
    client = ContromeClient(
        async_get_clientsession(hass),
        entry.data[CONF_HOST],
        timezone=dt_util.get_default_time_zone(),
        house_id=entry.data[CONF_HOUSE_ID],
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
    )
    try:
        info = await client.get_info()
    except ContromeAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except ContromeError as err:
        raise ConfigEntryNotReady(str(err)) from err

    data = ContromeRuntimeData(
        client=client,
        info=info,
        house=ContromeCoordinator(
            hass, entry, name="temps", interval=FAST_INTERVAL, fetch=client.get_house
        ),
        outputs=ContromeCoordinator(
            hass, entry, name="outs", interval=FAST_INTERVAL, fetch=client.get_outputs
        ),
        room_details=ContromeCoordinator(
            hass, entry, name="room_details", interval=FAST_INTERVAL, fetch=client.get_room_details
        ),
        upcoming=ContromeCoordinator(
            hass,
            entry,
            name="upcomingoffsets",
            interval=SLOW_INTERVAL,
            fetch=client.get_upcoming_offsets,
        ),
        fps=ContromeCoordinator(
            hass, entry, name="fps", interval=SLOW_INTERVAL, fetch=client.get_fps
        ),
    )
    # Required sources: without them setup fails and is retried.
    await data.house.async_config_entry_first_refresh()
    await data.outputs.async_config_entry_first_refresh()
    # Optional sources: if they fail, only their entities become unavailable.
    for optional in (data.room_details, data.upcoming, data.fps):
        await optional.async_refresh()

    entry.runtime_data = data
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ContromeConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
