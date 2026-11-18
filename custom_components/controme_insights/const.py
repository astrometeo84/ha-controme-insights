"""Constants for Controme Insights."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "controme_insights"

CONF_HOUSE_ID: Final = "house_id"

# Options (entry.options), set in the config flow and changeable in the options flow.
CONF_ROOMS: Final = "rooms"
"""Room IDs that get entities."""
CONF_SYSTEM_SENSORS: Final = "system_sensors"
"""Sensor IDs of the selected system sensors."""
CONF_GATEWAYS: Final = "gateways"
"""List of gateways: ``{"name": str, "floors": [floor_id, ...], "type": <gateway type>}``.

The first floor ID identifies the gateway (device identifier)."""
CONF_WRITE_OFFSET: Final = "write_offset"
"""API offset and boost enabled."""
CONF_WRITE_QUICKUI: Final = "write_quickui"
"""Quick operation (temporary target temperature) enabled."""

GATEWAY_NAME: Final = "name"
GATEWAY_FLOORS: Final = "floors"
GATEWAY_TYPE: Final = "type"

GATEWAY_TYPE_POSITION: Final = "position"
"""FBH-Gateway PRO 0-10 V (valve position 0-100 %); same value as ``OutputType.POSITION``."""
GATEWAY_TYPE_RELAY: Final = "relay"
"""FBH-Gateway Standard / Mini-Gateway (on/off); same value as ``OutputType.RELAY``."""
GATEWAY_TYPE_AUTO: Final = "auto"
"""Detect from the reported values (a value > 1 means position)."""
GATEWAY_TYPES: Final = (GATEWAY_TYPE_POSITION, GATEWAY_TYPE_RELAY, GATEWAY_TYPE_AUTO)

FAST_INTERVAL: Final = timedelta(seconds=60)
"""outs, temps, room_details."""
SLOW_INTERVAL: Final = timedelta(minutes=5)
"""upcomingoffsets, fps."""
