# Controme Insights

Home Assistant custom integration that **complements the official Controme integration** with
valve positions, return-flow temperatures, offsets per source, next schedule change, Smart Timing,
FPS blocks, system sensors and transmission monitoring.

> Status: early development – not ready for use yet. Specification: `docs/ENTWURF.md` (German).

Not affiliated with Controme GmbH. License: GPL-3.0.

## Requirements

- A Controme Smart-Heat system with the local JSON API enabled.
- Username and password of a Controme user. Read endpoints do not check them (live test
  2026-11-20), so setup, reauthentication and reconfiguration verify them with a POST to
  `set/json/v1/<house>/roomoffset/99999/` (a room that does not exist) with offset 0: the
  Mini-Server checks the credentials before the room and answers 404 (valid) or 403 (wrong)
  (live test 2026-11-20 on a NOVA 27, room 99999, house 1). No effect was observed, but it is
  still a write call; it runs only in these flows, never while polling and never in the
  background. Setup and reconfiguration send it only after the address answered `temps/` with
  a Controme house with rooms (reconfiguration: one of the selected rooms). Any other answer stops with the error `cannot_verify` and nothing
  is saved.
- `room_details/` (undocumented) is optional: without it only the room details entities are
  unavailable.

## Security

- The Controme Mini-Server speaks **plain HTTP only** (no TLS). Username and password travel
  unencrypted in your local network as form fields of every write call and of the credential
  check. Read calls send no credentials (HTTP Basic Auth only as a fallback if `room_details/`
  answers 401/403). Use the integration only in a trusted local network.
- Reads do not check the credentials, so a changed Controme password is not noticed while
  polling. Planned: a write call answered with HTTP 403 starts reauthentication (this version
  has no write functions yet). Until then, and without write functions, enter the new password
  via **Reconfigure**.
- Home Assistant stores the credentials in `.storage/core.config_entries`, like those of every
  other integration. The integration keeps them out of logs, error messages and the diagnostics
  download.
- Recommended: create a dedicated Controme user for Home Assistant with the minimum rights it
  needs, instead of using your administrator account.
