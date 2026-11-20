---
name: security-secrets
description: Rules and checklist for handling credentials and other secrets in aiocontrome and ha-controme-insights (library, integration, tests, dev container, maintainer PC). Use whenever code touches username/password, logging, error messages, diagnostics, repairs, config entries, fixtures, or when reviewing a change for leaks.
---

# Handling secrets (aiocontrome + ha-controme-insights)

Keep this file identical in both repositories.

## What counts as a secret here
- Controme username and password (form fields `user`/`password` for every `set/json/v1/…` call).
  `room_details/` does not need Basic Auth (accepted but not checked, live test 2026-11-20); the
  client still sends it – to be changed in aiocontrome 0.3.0.
- Home Assistant tokens, GitHub App private key and installation tokens.
- Not secret, but private (treat the same way in the repo): host/IP, real room and person names,
  MACs, sensor IDs (see the pseudonymization section of skill `controme-api`).
  The host may appear in local log messages, error messages and the config entry title (as in
  HA Core), but never in diagnostics, repair texts, entity attributes or fixtures.

## Known limit – document it, do not hide it
The Mini-Server speaks **plain HTTP only**. Credentials travel unencrypted in the local network,
form fields on writes (and, until aiocontrome 0.3.0, Basic Auth on `room_details/` reads).
Neither the library nor the integration can change this. README files must say so; never claim
"secure transport".

## Library (aiocontrome)
1. Credentials live only in the `ContromeClient` instance (private attributes). Never in module
   globals, class attributes, `__repr__`/`__str__`, exception messages or log records.
2. Log URLs, methods and status codes only. Never log request bodies, headers or `data=`.
3. Error bodies may echo POST data (Django debug page): pass every response text that ends up in
   an exception through `ContromeClient._redact` first. Each new error path needs a test that
   asserts the password is absent from `str(err)`.
4. `aiocontrome.redact()` is the tool for diagnostics data; extend its sensitive-key list when a
   new endpoint returns secret-like fields.
5. No credentials in fixtures. Raw `curl -i` captures in `tests/fixtures/write/` must have cookies
   and `Authorization` headers removed.

## Integration (ha-controme-insights)
1. Username and password are stored **only in `entry.data`**, never in `entry.options`,
   `hass.data`, entity attributes, unique IDs, device info or translation placeholders.
   Home Assistant keeps `entry.data` in `.storage/core.config_entries` in plain text; there is no
   secret store in HA. That is accepted HA practice – do not invent own encryption.
2. Password fields in flows use `TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))`
   and are never pre-filled with the stored password (reauth/reconfigure ask again). After a
   form error, do not return the password as a suggested value (only host and username).
3. Auth failures raise `ConfigEntryAuthFailed` so HA starts the reauth flow. Keep a reauth flow
   and add a reconfigure flow; both validate against the device before saving.
4. Diagnostics: `async_redact_data` with at least `host`, `username`, `password`, and run raw API
   payloads through `aiocontrome.redact()` (sensor IDs, MACs, IPs).
5. Credentials never appear in logs, error messages or repairs. The host may appear in
   local log messages and the entry title; it is redacted in diagnostics and kept out of
   repair texts.
6. Tests must prove it: for setup, flows, diagnostics and a failing write, assert that the test
   password string does not appear in `caplog.text`, in diagnostics output or in error messages.
   Use an obviously fake password such as `"pw-test-SECRET"` so a search is unambiguous.

## Repository and dev container
- Never create, request or store credentials (also in `CLAUDE.md`). No `.env` files with
  passwords; `.gitignore` already covers `.env`, `.env.*`, `*.pem`.
- The GitHub App private key belongs to user `ghapp` only (mode `600`), the token cache too.
  `dev` gets short-lived installation tokens via `sudo -n -u ghapp /usr/local/bin/gh-app-token`;
  never print a token, never write it to a file in the repo or to shell history.
- Before every commit: `git diff --cached` must not contain passwords, tokens, private keys, real
  hosts or identifiers. A local `gitleaks` pre-commit hook may enforce this.
- GitHub secret scanning and push protection are enabled on both repos by the maintainer.

## Maintainer PC (live tests)
Claude never asks for or handles real credentials. Live tests are instructions for the user
(skill `live-test-plan`, script `controme-get.ps1`): credentials come from `Read-Host` (password
with `-AsSecureString`) or a SecretManagement vault; `Get-Credential` is avoided because its
dialog can stay hidden behind other windows (observed 2026-11-20). They reach curl via stdin
(`curl.exe -K -`), so they appear neither on the command line nor in the PowerShell history.

## Review checklist
- [ ] No secret in code, tests, fixtures, docs, commit message or PR text
- [ ] No secret in log calls, exception messages, `repr`, diagnostics, repairs, attributes
- [ ] Password only in `entry.data`; reauth/reconfigure re-validate
- [ ] New error paths: test asserts the password is absent
- [ ] Plain-HTTP limitation still documented
