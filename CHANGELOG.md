# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Reconfigure flow: change the address (e.g. after an IP address change) and credentials of an
  entry. The password is always entered again and checked against the device. As the API
  reports no serial number, the new address must hold the stored house with at least one of
  the selected rooms (otherwise `wrong_device`); an address of another entry aborts with
  `already_configured`. The unique ID and the generated title follow the new address.
- Diagnostics download: entry (host, username, password and title redacted), options, system
  info, status per coordinator (last success, last error without host or credentials) and the
  data of all coordinators. Sensor IDs, MACs and IP addresses are replaced by
  `aiocontrome.redact()`.
- README: Security section (plain HTTP, storage of credentials, dedicated Controme user).

### Changed

- Requires `aiocontrome` 0.2.0.

### Security

- After a form error in the setup, the password is no longer sent back to the form as a
  suggested value.
- Tests prove that the password appears neither in the log nor in error messages, flow
  results or the diagnostics.
