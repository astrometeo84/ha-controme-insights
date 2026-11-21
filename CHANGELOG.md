# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Reconfigure flow: change the address (e.g. after an IP address change) and credentials of an
  entry. The password is always entered again and checked against the device. As the API
  reports no serial number, at least one of the selected rooms must exist at the new address
  (without a selection: any room; otherwise `wrong_device`), checked before the credentials
  are sent. The house ID is no evidence: the tested one-house system returned house 1's data
  for house ID 99 (live test 2026-11-20). An address of another entry aborts with
  `already_configured`. The unique ID and the generated title follow the new address.
- Diagnostics download: entry (host, username, password and title redacted), options, system
  info, status per coordinator (last success, last error without host or credentials) and the
  data of all coordinators. Sensor IDs, MACs and IP addresses are replaced by
  `aiocontrome.redact()`.
- README: Security section (plain HTTP, storage of credentials, dedicated Controme user).

### Changed

- Requires `aiocontrome` 0.3.0.
- Setup, reauth and reconfigure verify the credentials with `verify_credentials()` and fail
  closed: rejected → `invalid_auth`, not reachable → `cannot_connect`, any unexpected answer →
  the new form error `cannot_verify`; nothing is saved. Read endpoints, `room_details/`
  included, do not check credentials (live test 2026-11-20), so previously wrong credentials
  could be stored. The check is a POST to `roomoffset/99999/` (a room that does not exist) with
  offset 0; it showed no effect live, but it is a write call and runs only in these flows,
  never while polling. Setup and reconfigure send it only after `temps/` matched, so the
  plain-text password never goes to an address without the expected system. Firmware without
  `room_details/` can be set up; only the room details entities are unavailable then.

### Security

- After a form error in the setup, the password is no longer sent back to the form as a
  suggested value.
- Tests prove that the password appears neither in the log nor in error messages, flow
  results or the diagnostics.
- Diagnostics also remove the HTML-escaped and URL-encoded password and the Basic Auth token
  from error texts.
