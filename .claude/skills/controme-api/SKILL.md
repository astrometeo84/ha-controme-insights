---
name: controme-api
description: Reference for the Controme Smart-Heat local HTTP API (NOVA 27) – endpoints, response shapes, firmware quirks and the recorded fixtures. Use whenever writing, parsing, testing or reviewing code that talks to Controme.
---

# Controme local HTTP API – reference

Official docs: https://support.controme.com/api/ (documented endpoints).
Source of truth for shapes and quirks below: the recorded fixtures in `tests/fixtures/`
(real system, Smart-Heat NOVA 27, branch `uiv2`, 2026-11-13, pseudonymized).

**Never call a real Controme system.** Development and tests use the fixtures and mocked HTTP via a
local aiohttp test server on 127.0.0.1 instead of `aioresponses` (fixture `controme_server` in
`tests/conftest.py`; it serves fixtures per endpoint and simulates 401/403/404/timeout/broken JSON).
The dev container has no route to the home network by design.

## Basics

- Base URL: `http://<host>/` – HTTP only on the local Mini-Server (no TLS).
- House ID `h`: usually `1` (auto-detect: first ID whose `temps/` contains rooms).
  **Live test 2026-11-20 (one-house system, not recorded as fixture):** `temps/` and
  `room_details/` with `h = 99` return the same data as house 1. Open: whether the ID is ignored
  or falls back to the only house, and how systems with several houses behave. Consequence: the
  house ID is **no** device or plausibility check, and auto-detect always finds `1` here.
- Read endpoints under `get/json/v1/{h}/…` need **no auth – including `room_details`**.
  ~~`room_details` needs Basic Auth~~ – **refuted by the live test 2026-11-20** (not recorded as
  fixture): without
  credentials, with a wrong and with the right password it answered 200 with the same data
  (compared with a local diff script; only measurements and timestamps differed). Basic Auth is
  accepted but not checked. No tested read endpoint checks the credentials (`room_details/` tested
  with wrong, missing and correct password; other read endpoints only without credentials);
  write calls do (see below).
- Write endpoints under `set/json/v1/{h}/…` are POST with form fields incl. `user` and `password`
  (see "Write endpoints" below; parameters from the official docs, never guess).
- Trailing slash matters on some endpoints – always request with trailing slash.
- 404 for an **unknown route** returns a huge Django debug HTML page (~240 kB, lists all server
  routes). `roomoffset/` with an unknown room (only `99999` tested) answers 404 with an **empty**
  body instead (see below).
  **Never log full error bodies**; log status + first 200 chars at most.

## Read endpoints

| Endpoint | Auth | Fixture(s) | Shape |
|---|---|---|---|
| `info/` | no | `info.json` | `{repo, branch, sw-date, commit, hw, os, services-paket, app-compatibility, fbi}` |
| `rooms/` | no | – | floors → `raeume` (id, name) |
| `temps/` | no | `temps.json` | floors → `raeume` with `sensoren`, offsets, scene info |
| `outs/` | no | `outs_pro_a.json`, `outs_pro_b.json` | floors → `raeume` → `ausgang: {"<n>": value}` |
| `rltemps/{room}/` | no | `rltemps_<id>.json` | list of return-flow sensors |
| `room_details/` | no (~~Basic Auth~~, refuted 2026-11-20: accepted, not checked) | `room_details_*.json` | floors → `rooms` (camelCase, rich) – undocumented, used by the official HA integration |
| `upcomingoffsets/` | no | `upcomingoffsets.json` | houses/rooms → module → `[[iso_time, id|null, kind], …]` |
| `fps/` | no | `fps.json` | `{"<fps_id>": {...}}` |
| `vtr/`, `wetter_pro/` | no | `vtr_empty.json`, `wetter_pro_empty.json` | `{}` when not configured; shape with data unknown → client passes the object through deep-frozen (`get_vtr`, `get_weather_pro`), no model |
| `roomoffsets/` | no | `roomoffsets_empty.json`, `roomoffsets_api.json`, `roomoffsets_after_house.json` | **Does not list API offsets**: stayed `[]` after `offset=0` (= remove, recorded) and also while room and house offsets were active (live test 2026-11-17, not recorded → `synthetic_roomoffsets_active.json`, marked synthetic). Read API offsets from `room_details/` → `offsets["api"]` instead. What `roomoffsets/` lists otherwise is unknown |

## Write endpoints (official docs)

POST, form-encoded. Every request contains `user` and `password` (plain HTTP, no TLS on the
Mini-Server → local network only). Wrong credentials → **403 with an empty `text/html` body**.
Credentials are checked by write calls; no tested read endpoint checks them (`room_details/`
tested with wrong, missing and correct password; other read endpoints only without credentials;
live test 2026-11-20, see "Basics").

**Checking credentials without effect (live test 2026-11-20, not recorded as fixture):**
`roomoffset/99999/` (room does not exist) with `offset=0.00`:
- right credentials → **404 with an empty `text/html` body** (no Django debug page),
- wrong credentials → **403 with an empty body**.

The server checks the credentials **before** the room, so such a call verifies the credentials.
No effect observed: before/after comparison of `room_details/` around the live suite run on
2026-11-20 showed only measurement changes, no change under offsets. It is still a POST to a
write endpoint. Only tested with room `99999`.

Success (live test 2026-11-15, fixtures `write/*.txt`): **HTTP 200 with an empty `text/html` body**
for `soll`, `roomoffset`, `houseoffset`; `ziel` answers with JSON
`{"duration": 30, "full_expire_time": "YYYY-MM-DD HH:MM", "temperature": 19.0, "time": "HH:MM"}`.
The client treats HTTP 2xx as success and ignores the body.
The docs document **no value ranges**; aiocontrome deliberately does not range-check (cooling,
offsets) – plausibility limits belong to the caller.

| Client method | Endpoint | Extra fields |
|---|---|---|
| `set_setpoint` | `soll/{room}/` | `soll` (decimal) |
| `set_target` | `ziel/{room}/` | `ziel` (decimal), `duration` (minutes or `default`) – **required**, fails without |
| `set_scene` | `temperaturszenen/{scene}/` | optional `duration` (minutes or `default` → temporary and fixed; without → permanent until next manual/program switch), optional `room_id` (without → **all rooms**) |
| `set_default_duration` | `quickui/` | `duration` (default for temporary API commands and Quick-UI) |
| `set_operating_mode` | `rooms/{room}/` or `rooms/` (all rooms) | `action=betriebsart`, `value` ∈ `heating`, `cooling`, `off`, `on` |
| `set_room_offset` | `roomoffset/{room}/` | `offset` (decimal), `offset_name` (string); value lives only **10 min** in a cache → refresh regularly |
| `set_house_offset` | `houseoffset/` | **undocumented** – the docs end after the endpoint name; fields assumed like `roomoffset` (`offset`, `offset_name`). Live test: accepted with HTTP 200 for `offset=0` (= remove); the effect of a non-zero offset is **not yet verified** |

- Not live-tested yet: `set_scene`, `set_default_duration`, `set_operating_mode` (they change state
  visibly; only the maintainer may test them live).
- Decimals are sent with a dot and two decimals (`21.50`).
- Never log or raise with the password; error bodies are redacted (a Django debug page may echo
  POST data).

## Quirks (all observed on real data)

### outs
- Keys can have a **leading space**: `{" 2": 0, "3": 0}` → strip keys.
- Values depend on the gateway type:
  - **FBH-Gateway PRO 0–10 V**: valve position **0–100** (seen: 12, 29).
  - **Relay gateways** (FBH-Gateway Standard, Mini-Gateway): **0/1 only** – 1 means fully open.
    A single value cannot tell the type apart (1 could be 1 %). See flame4ever issue #33.
  - → output type is configured per floor/gateway; auto-detect = "ever saw a value > 1 on this floor".
- Output numbers **restart per gateway** (here: one gateway per floor) → key by (floor, room, output).
- Rooms without outputs: `ausgang: {}`.
- The API never names the gateway of an output.

### temps
- `sensoren[].wert` is a number **or a dict** for radio multi-sensors:
  `{"Status": null, "Helligkeit": null, "Bewegung": null, "Temperatur": 18.8, "Relative Luftfeuchte": null}`
  – most fields are always null; only use non-null values.
- `letzte_uebertragung`: `"dd.mm.yyyy HH:MM"` (local time) **or `null`**. `null` = "no current
  value", **not** "never transmitted". Remember the last seen time yourself.
- `luftfeuchte`: number **or a German string** (`"kein Sensor vorhanden"`, `"kein aktueller Wert vorhanden"`).
- `temperatur` can be `null`; floats can be long (`18.823529411764707`).
- `raumtemperatursensor: true` marks the room sensor; others are return/humidity/system sensors.
- System sensors live in pseudo rooms without control (here `hk_verteiler`: flow temps per floor,
  DHW from a heat pump via Modbus).
- Temporary mode (after `set-ziel`, fixture `temps_temporary_mode.json`): `is_temporary_mode: true`,
  `mode_end_datetime: "YYYY-MM-DD HH:MM"` (local time; `""` otherwise), `remaining_time` becomes an
  **int in seconds** (`""` otherwise). `current_temperaturszene_name` keeps the scene name.

### rltemps
- `letzte_uebertragung` uses a **different format**: `"HH:MM:SS dd.mm.yyyy"`.
- `ausgang` is always `null` here – do not rely on it.
- Redundant with `temps` (prefer `temps`).

### room_details (no auth checked, see "Basics")
- `skip_loops=true` makes no difference here; `heatingLoops` is always `[]`.
- `sensors` and `unassignedReturnSensors` are empty – return sensors come only from `temps`.
- `offsets`: dict of source → `{"raum": float, "haus": float}`; the set of sources **varies per room**
  (e.g. `Kalender` only in some rooms, `Geolocation` missing in others) – accept any key.
- `offsets["api"]` is the **only place API offsets show up** (`roomoffsets/` stays `[]`). Shape:
  `{}` before any API offset; `{"haus": x}` once a house offset was set; the key `"raum"` appears only
  once a room offset was set and stays (with `0.0`) after a reset with 0. A missing side counts as 0.
  Fixture `room_details_api_offset_active.json` (room 23: `{"raum": 1.0, "haus": 0.0}`, others
  `{"haus": 0.0}`).
- `totalOffset` is the sum of all sources **including the API offset**, and
  `targetTemperature = setpoint + totalOffset` (room 23: Wetter −0.4 + api 1.0 = 0.6; 18.8 → 19.4).
- `dominantOffsetSource` values seen: `wetter`, `fps`, `fenster_offen`, `luftfeuchte`, and `null`
  (fixture `room_details_temporary_mode.json`; pass unknown values through). It **ignores the API
  offset** (stays `wetter` although api +1 K is the largest source).
- Window-open detection: `offsets["Fenster-offen-Erkennung"].raum == -10.0` while open
  (detected ≤ 10 min after opening, removed ≤ 10 min after closing; fixtures `room_details_window_*`).
- `sceneControl` can be `null` (rooms without schedule). `sceneControl.ownSchedule == true` →
  room decoupled from the heating program (fixture `room_details_own_schedule*`, Wohnzimmer).
- `sceneControl.smartTiming`: `null` or `{zeit, text, zustand, temperatur}`; `zustand` seen:
  `rechtzeitig`, `vorheizen`.
- `sceneControl.nextDueTimeRelative` is **unreliable** (stayed constant between polls) → use `nextDueTime`
  (`"YYYY-MM-DD HH:MM"`, local time).
- `timer` may show `active: true` with an end date in the past and `running: false` – treat
  `running` as the truth.
- `operatingMode`: `"Heating"` (others possible).
- `gatewayOfflineMinutes`: `null` or minutes.
- Temporary mode (after `set-ziel`, fixture `room_details_temporary_mode.json`): `isTemporaryMode: true`,
  `activeMode` = `{activated_mode_id: -1, mod: "quickui", activated_mode_text: "<end HH:MM>",
  use_offsets: false, priority: 2}`; `sceneControl.currentSceneName` becomes `null`,
  `afterTimerSceneName`/`afterTimerTemperature` name the scene that follows, `modeEndDatetime`
  `"YYYY-MM-DD HH:MM"`, `remainingTime` a **string** `"HH:MM:SS"` (unlike `temps`), `originalDuration`
  in minutes. `remainingTime` rather reflects the original duration than the time left → use
  `modeEndDatetime` for the end of the temporary mode.
- Fixture `room_details_window_0_closed_pv_boost.json` contains an active PV boost (FPS offsets +2…+5 K).

### upcomingoffsets
- Timestamps ISO 8601 with offset (`2026-11-13T18:30:00.684+01:00`).
- Entry kinds seen: `mode-change` (id = target scene), `ending-list` (id null, end of horizon).

### fps
- Dict keyed by FPS id (string). `mode`: `output` (0/1 or numeric) or `offset` (K).
- `value`/`last_value`, `formula`, `evaluated` (variables M1…, A1…, V1…), `variables_details`
  (names of inputs), `user_variables` (sliders with min/max), `override_*` (manual mode),
  `last_evaluated_at` (ISO, UTC).
- Read-only: there is no documented write endpoint for FPS.

### Internal API `/api/v1/…`
- Exists on NOVA 27 but is **disabled by default** (`{"error": "api_disabled", …}`, fixture
  `apiv1_disabled.json`). **Do not use it and never enable it** (enabling is a write).

## Sensor ID formats (connection type)

| Pattern | Connection |
|---|---|
| `28_xx_xx_xx_xx_xx_xx_xx` | 1-Wire temperature (DS18B20) |
| `26_xx_…` | 1-Wire humidity (DS2438) |
| `aa:bb:cc:dd:ee:ff` (6 bytes) | Controme room controller (radio) |
| `aa:bb:cc:dd` (4 bytes) | Controme radio sensor |
| `12_00_00_00_00_00_00_xx` + foreign name (e.g. `ISG_…`) | virtual / foreign system (Modbus/UniConnect) |

## Pseudonymization of fixtures
Room/person names, MACs and 1-Wire IDs are replaced consistently (e.g. `02:00:00:00:00:01`,
`28_00_00_00_00_00_05_00`). Scene names with initials are replaced by scene ID: 16 → `Anwesenheit 1`,
3 → `Anwesenheit 2`, 11 → `Anwesenheit 3`, 12 → `Anwesenheit 4`, 13 → `Anwesenheit 5`; no other value
may start with `Anwesenheit `. `aiocontrome.redact()` applies the same idea at runtime (IDs/MACs → typed placeholders, IPs → `**REDACTED**`) for diagnostics. Keep it that way – never add real identifiers to the repo, and check
new recordings (names, IDs, scene names) before copying them into `tests/fixtures/`.
