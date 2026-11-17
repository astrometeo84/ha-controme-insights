"""Constants for Controme Insights."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "controme_insights"

CONF_HOUSE_ID: Final = "house_id"

FAST_INTERVAL: Final = timedelta(seconds=60)
"""outs, temps, room_details."""
SLOW_INTERVAL: Final = timedelta(minutes=5)
"""upcomingoffsets, fps."""
