# Fixtures

Real responses of one Controme system (Smart-Heat NOVA 27, branch `uiv2`, Mini-Server 4,
three FBH-Gateway PRO 0–10 V – one per floor), recorded on 2026-11-13. Pseudonymized:
room/person names, MACs and 1-Wire IDs replaced consistently. Scene names that contained
initials are replaced by ID in **all** fixtures: 16 → `Anwesenheit 1`, 3 → `Anwesenheit 2`,
11 → `Anwesenheit 3`, 12 → `Anwesenheit 4`, 13 → `Anwesenheit 5` (no other value may start
with `Anwesenheit `).

| File | Endpoint | Scenario |
|---|---|---|
| `info.json` | `info/` | system info |
| `temps.json` | `temps/` | all sensors incl. radio multi-sensor (dict value), `letzte_uebertragung: null`, humidity strings, system room `hk_verteiler` |
| `outs_pro_a.json`, `outs_pro_b.json` | `outs/` | positions 12 % / 29 %, keys with leading space, rooms without outputs |
| `rltemps_<room>.json` | `rltemps/<room>/` | return sensors, time format `HH:MM:SS dd.mm.yyyy` |
| `room_details_morning*.json` | `room_details/` (± `skip_loops`) | normal state, all rooms follow the heating program |
| `room_details_own_schedule*.json` | `room_details/` | room 19 decoupled from heating program (`ownSchedule`) |
| `room_details_window_0_closed_pv_boost.json` | `room_details/` | before window test; PV boost active (FPS offsets +2…+5 K) |
| `room_details_window_1_open_10min.json` | `room_details/` | window open in room 23: `Fenster-offen-Erkennung` −10 K, dominant source `fenster_offen` |
| `room_details_window_2_open_20min.json` | `room_details/` | still open; radio sensor value unchanged (sends rarely) |
| `room_details_window_3_closed_again.json` | `room_details/` | closed again: offset back to 0; Smart Timing `vorheizen` in room 19 |
| `upcomingoffsets.json` | `upcomingoffsets/` | next heating program changes |
| `fps.json` | `fps/` | 11 FPS blocks (output/offset), evaluated variables, sliders |
| `vtr_empty.json`, `wetter_pro_empty.json`, `roomoffsets_empty.json` | | not configured → empty |
| `apiv1_disabled.json` | `/api/v1/…` | internal API disabled (default) |

## Live write test (2026-11-15)

Recorded by the maintainer with `curl` against the same system. Room 23 was used; all writes
were chosen to have no effect (unchanged setpoint, 0 K offsets, temporary mode expiring by itself).

| File | Endpoint | Scenario |
|---|---|---|
| `temps_temporary_mode.json` | `temps/` | after `set-ziel` (unchanged value, 30 min) in room 23: `is_temporary_mode: true`, `mode_end_datetime: "2026-11-15 14:50"`, `remaining_time: 1804` (int seconds; `""` otherwise) |
| `room_details_temporary_mode.json` | `room_details/` | same moment: `activeMode` id `-1`, `mod: "quickui"`, text = end time `"14:50"`, `use_offsets: false`; `sceneControl.currentSceneName: null`, `afterTimerSceneName`/`afterTimerTemperature` = scene after the temporary mode, `remainingTime: "00:30:00"` (≈ original duration, not time left → use `modeEndDatetime`), `originalDuration: 30`; `dominantOffsetSource` is `null` (room 23) or `luftfeuchte` in some rooms |
| `roomoffsets_api.json` | `roomoffsets/` | after `set-roomoffset` with `offset=0` (= remove) → still `[]` |
| `roomoffsets_after_house.json` | `roomoffsets/` | after `set-houseoffset` with `offset=0` (= remove) → still `[]` |

## Live API offset test (2026-11-17)

`set-roomoffset` with `offset=1` on room 23 → `200 OK`; a house offset was set (and reset to 0) before.

| File | Endpoint | Scenario |
|---|---|---|
| `room_details_api_offset_active.json` | `room_details/` | room 23: `offsets["api"] = {"raum": 1.0, "haus": 0.0}`, all other rooms `{"haus": 0.0}`; `totalOffset` 0.6 = Wetter −0.4 + api 1.0, `targetTemperature` 19.4 = `setpoint` 18.8 + 0.6; `dominantOffsetSource` stays `wetter`; offset sources vary per room (`Kalender` only in room 23, `Geolocation` missing in rooms 18, 24, 26) |

Findings:

1. `roomoffsets/` does **not** list API offsets – it stayed `[]` while room and house offsets were
   active (response not recorded; see `synthetic_roomoffsets_active.json`). The only source is
   `room_details/` → `offsets["api"]`.
2. `offsets["api"]` is `{"haus": x}`; the key `"raum"` appears only once a room offset was set and
   stays (with `0.0`) after a reset. Before any API offset it is `{}` (older fixtures).
3. `totalOffset` includes the API offset; `targetTemperature = setpoint + totalOffset` (holds in all
   `room_details_*` fixtures).
4. `dominantOffsetSource` ignores the API offset.
5. Offset sources vary per room; the parser keeps any key.

Raw HTTP responses (`curl -i`, cookies removed) of the write endpoints live in `write/`:

| File | Request | Response |
|---|---|---|
| `write/soll_403.txt` | `set-soll`, wrong password | `403 Forbidden`, empty `text/html` body |
| `write/soll_ok.txt` | `set-soll` | `200 OK`, empty `text/html` body |
| `write/ziel_ok.txt` | `set-ziel`, `duration=30` | `200 OK`, JSON `{"duration": 30, "full_expire_time": "2026-11-15 14:50", "temperature": 19.0, "time": "14:50"}` |
| `write/roomoffset_ok.txt` | `set-roomoffset`, `offset=0` (= remove), `offset_name` | `200 OK`, empty `text/html` body |
| `write/houseoffset_ok.txt` | `set-houseoffset`, `offset=0` (= remove), `offset_name` | `200 OK`, empty `text/html` body (fields accepted; effect not visible with 0 K) |

## Synthetic fixtures

Files prefixed `synthetic_` are **not recorded** from a real system. They are hand-written from
the documented behaviour to cover cases the recorded system cannot produce.

| File | Endpoint | Scenario |
|---|---|---|
| `synthetic_outs_relay.json` | `outs/` | relay gateway: values 0/1 only, key with leading space |
| `synthetic_roomoffsets_active.json` | `roomoffsets/` | while room and house API offsets are active: `[]`. Mirrors the live observation of 2026-11-17, but the response itself was **not recorded** |
| `synthetic_404_debug.html` | any unknown route | shortened Django debug 404 page (the real one is ~240 kB); tests pad it to full size |
