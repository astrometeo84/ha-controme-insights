"""Translation files stay consistent."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

COMPONENT = Path(__file__).parent.parent / "custom_components" / "controme_insights"


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _keys(data: Any, prefix: str = "") -> set[str]:
    if not isinstance(data, dict):
        return {prefix}
    return {key for name, value in data.items() for key in _keys(value, f"{prefix}.{name}")}


def test_strings_equal_english() -> None:
    assert _load(COMPONENT / "strings.json") == _load(COMPONENT / "translations" / "en.json")


def test_german_has_the_same_keys() -> None:
    english = _keys(_load(COMPONENT / "translations" / "en.json"))
    assert _keys(_load(COMPONENT / "translations" / "de.json")) == english
