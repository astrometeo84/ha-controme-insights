---
name: ha-integration-dev
description: Conventions for building and testing the controme_insights Home Assistant custom integration (coordinators, config/options flow, entities, devices, repairs, diagnostics, services, translations, tests, HACS). Use whenever writing or reviewing integration code.
---

# Home Assistant integration conventions (controme_insights)

Reference: https://developers.home-assistant.io/ – check the current docs before using an API you
are unsure about; HA deprecates patterns regularly (e.g. `hass.data[DOMAIN]` → `entry.runtime_data`,
tuple `via_device` → `via_device_id`).

## Layout
```
custom_components/controme_insights/
  __init__.py        async_setup_entry / async_unload_entry, runtime_data dataclass
  manifest.json      domain, name "Controme Insights", config_flow, iot_class "local_polling",
                     requirements ["aiocontrome==X.Y.Z"], version, codeowners, documentation, issue_tracker
  const.py
  coordinator.py     one DataUpdateCoordinator per source (see CLAUDE.md for intervals)
  entity.py          base entity: device_info resolution (official room device or own device)
  config_flow.py     ConfigFlow + OptionsFlow (steps: connection, rooms, system sensors, gateways, writes)
  sensor.py  binary_sensor.py  number.py
  services.py + services.yaml   boost / set_room_offset / clear_room_offset (only if writes enabled)
  repairs.py         issues: sensor not transmitting, gateway offline, room_details unavailable,
                     gateway type unknown for floor
  diagnostics.py     async_get_config_entry_diagnostics with async_redact_data
  strings.json + translations/en.json + translations/de.json
tests/
  conftest.py        fixtures loaded from tests/fixtures/*.json, aioresponses / patched client
  test_config_flow.py test_sensor.py test_binary_sensor.py test_number.py test_services.py
  test_repairs.py test_diagnostics.py test_init.py
hacs.json
```

## Rules
- `has_entity_name = True`; names only via `translation_key` (+ `translation_placeholders` for
  room/output/sensor names). No hard-coded German strings in Python.
- Units/device classes: temperatures `UnitOfTemperature.CELSIUS` + `SensorDeviceClass.TEMPERATURE`;
  valve `PERCENTAGE` + `state_class MEASUREMENT`; offsets and deviations are temperature *differences* in K –
  do not give them the TEMPERATURE device class (HA would treat K as an absolute temperature and convert it);
  use no device class and unit "K"; timestamps `SensorDeviceClass.TIMESTAMP` with
  tz-aware datetimes; enums `SensorDeviceClass.ENUM` with `options`.
- `EntityCategory.DIAGNOSTIC` for diagnostic entities; `entity_registry_enabled_default=False` where
  the spec says "aus".
- Availability: an entity is unavailable only if *its* coordinator failed.
- Devices: room entities attach via `identifiers={("controme", f"room_{room_id}")}` if that device
  exists in the device registry, else own device `("controme_insights", f"{entry_id}_room_{room_id}")`.
  Gateway devices `("controme_insights", f"{entry_id}_gw_{floor_id}")` with `via_device_id` → house device.
- Entity IDs must not start with `controme_` (see CLAUDE.md) – device names drive entity IDs.
- Writes (API offset, boost, quickui) only when enabled in options; auto-renew the room offset every
  5 min while ≠ 0 (Controme drops it after 10 min); clear on unload.
- No blocking I/O; reuse `async_get_clientsession(hass)`.
- Repairs: `ir.async_create_issue(..., is_fixable=False, translation_key=..., translation_placeholders=...)`
  and delete the issue when the condition clears.
- Diagnostics: redact host, username, password, sensor IDs, MACs.

## Tests
- `pytest-homeassistant-custom-component` pinned to the HA version the user runs; Python version as
  required by that HA version.
- Snapshot tests (syrupy) for entity states are welcome.
- Config flow: every step, errors (cannot_connect, invalid_auth, api_disabled), abort on duplicate host,
  options flow round trip.
- Never perform real network I/O in tests.

## HACS
`hacs.json`: `{"name": "Controme Insights", "render_readme": true, "homeassistant": "<min version>"}`.
Releases are made by the user (see skill `release`).
