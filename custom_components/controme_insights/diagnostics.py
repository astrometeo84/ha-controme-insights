"""Diagnostics download: entry, system info, coordinator status and data, all redacted.

Host, username and password are removed from the entry; sensor IDs, MACs and IP addresses are
replaced by ``aiocontrome.redact`` in one call over options, info and data, so the same sensor
gets the same placeholder everywhere. Error texts additionally lose host and credentials.
"""

from __future__ import annotations

import dataclasses
import html
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from urllib.parse import quote, quote_plus

from aiocontrome import REDACTED, redact
from aiocontrome.client import basic_auth_header
from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .coordinator import ContromeConfigEntry, ContromeCoordinator

TO_REDACT = {CONF_HOST, CONF_USERNAME, CONF_PASSWORD}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ContromeConfigEntry
) -> dict[str, Any]:
    """Return the redacted diagnostics of a config entry."""
    data = entry.runtime_data
    coordinators: dict[str, ContromeCoordinator[Any]] = {
        "temps": data.house,
        "outs": data.outputs,
        "room_details": data.room_details,
        "upcomingoffsets": data.upcoming,
        "fps": data.fps,
    }
    scrub = _Scrubber(entry, data.client.base_url)
    redacted = redact(
        {
            "options": dict(entry.options),
            "info": _plain(data.info),
            "data": {name: _plain(c.data) for name, c in coordinators.items()},
        }
    )
    return {
        "entry": {
            "title": REDACTED,
            "version": entry.version,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": redacted["options"],
        },
        "info": redacted["info"],
        "coordinators": {
            name: _status(coordinator, scrub) for name, coordinator in coordinators.items()
        },
        "data": redacted["data"],
    }


class _Scrubber:
    """Removes host and credentials of the entry from error texts.

    Base URL, host and the password in the forms ``aiocontrome`` redacts (raw, HTML-escaped,
    URL-encoded, Basic Auth token with and without ``Basic ``) are replaced anywhere, longest
    first; the username only as a whole word, so a short name does not destroy the text. Empty
    values are skipped.
    """

    def __init__(self, entry: ContromeConfigEntry, base_url: str) -> None:
        host = str(entry.data.get(CONF_HOST) or "")
        username = str(entry.data.get(CONF_USERNAME) or "")
        password = str(entry.data.get(CONF_PASSWORD) or "")
        values = {base_url, host}
        if password:
            values |= {password, html.escape(password), quote(password), quote_plus(password)}
            if ":" not in username:
                header = basic_auth_header(username, password)
                values |= {header, header.removeprefix("Basic ")}
        self._literals = sorted((v for v in values if v), key=len, reverse=True)
        self._username = re.compile(rf"(?<!\w){re.escape(username)}(?!\w)") if username else None

    def __call__(self, text: str) -> str:
        for literal in self._literals:
            text = text.replace(literal, REDACTED)
        if self._username is not None:
            text = self._username.sub(REDACTED, text)
        cleaned: str = redact(text)
        return cleaned


def _status(coordinator: ContromeCoordinator[Any], scrub: _Scrubber) -> dict[str, Any]:
    error = coordinator.last_exception
    return {
        "last_update_success": coordinator.last_update_success,
        "last_update_success_time": _plain(coordinator.last_update_success_time),
        "last_exception": None if error is None else scrub(f"{type(error).__name__}: {error}"),
    }


def _plain(value: Any) -> Any:
    """Convert aiocontrome models into JSON-like data that ``redact`` can walk through."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _plain(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value
