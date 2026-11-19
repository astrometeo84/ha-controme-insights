# Controme Insights

Home Assistant custom integration that **complements the official Controme integration** with
valve positions, return-flow temperatures, offsets per source, next schedule change, Smart Timing,
FPS blocks, system sensors and transmission monitoring.

> Status: early development – not ready for use yet. Specification: `docs/ENTWURF.md` (German).

Requires a Controme Smart-Heat system with the local JSON API enabled. Not affiliated with
Controme GmbH. License: GPL-3.0.

## Security

- The Controme Mini-Server speaks **plain HTTP only** (no TLS). Username and password travel
  unencrypted in your local network (HTTP Basic Auth for the room details, form fields for
  writes). Use the integration only in a trusted local network.
- Home Assistant stores the credentials in `.storage/core.config_entries`, like those of every
  other integration. The integration keeps them out of logs, error messages and the diagnostics
  download.
- Recommended: create a dedicated Controme user for Home Assistant with the minimum rights it
  needs, instead of using your administrator account.
