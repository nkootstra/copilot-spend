# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-05-17

### Added

- `copilot-spend whoami` subcommand: prints the active login, host,
  credential source (native vs opencode), and Copilot plan. Falls back
  gracefully when the account has no Copilot quota.
- `copilot-spend --json` flag: renders the current spend as a stable,
  sort-keyed JSON object suitable for piping into `jq`, dashboards, or
  alerting. Documented schema; field additions are non-breaking.
- `COPILOT_SPEND_QUIET=1` silences the permissive-perms warning when
  the auth file isn't `0o600`. The warning itself now mentions the
  escape hatch.
- `COPILOT_SPEND_DEBUG=1` re-raises unexpected exceptions with a full
  traceback and emits a one-line diagnostic if the reset-date field
  can't be extracted from the API response.
- One transparent retry on transient 5xx in `fetch_quota`, with a 0.5s
  backoff. 401/403/404 still fail fast.
- GitHub device-flow HTTP errors now surface the GitHub
  `error_description` body, turning bare "GitHub returned 422" into
  diagnosable messages.
- Repo hygiene: `SECURITY.md`, Dependabot for pip and GitHub Actions,
  weekly CodeQL python analysis.

### Changed

- CI: new lint job runs `ruff check`, `ruff format --check`, and
  `mypy --strict` on every push and PR. Test job now collects coverage
  with a 80% floor (ratcheting up as features land).
- README documents the new subcommand, flag, and supported environment
  variables.
- `actions/upload-artifact` and `actions/download-artifact` bumped to v5
  in the release workflow.

## [0.1.0] - 2026-05-17

### Added

- `copilot-spend` bare command: reads the current-period Copilot quota and
  prints used PRUs, included allowance, billable overage (at $0.04/PRU), and
  the period reset date.
- `copilot-spend login` subcommand: GitHub OAuth device flow against the
  well-known VS Code Copilot GitHub App client ID, with re-auth detection,
  `slow_down` handling, defensive timeout, SSRF host validation, and
  post-login verification against `/copilot_internal/user` before any token
  is persisted.
- `copilot-spend logout` subcommand: removes stored credentials
  idempotently and cleans up any legacy `session.json` from earlier builds.
- Multi-source auth resolution: prefers the native
  `~/.config/copilot-spend/auth.json`, falls back to an existing
  `~/.local/share/opencode/auth.json` so users already authenticated to
  opencode work without re-running login.
- GitHub Enterprise host support: device flow and quota fetch both target
  `https://<ghe-host>/api/v3/...` when an enterprise host is configured.
- Single-hop bearer path: the `ghu_` or `gho_` user token is sent directly
  as `Bearer` to `/copilot_internal/user` — no separate session-token
  exchange, no `session.json` cache.
- Hardened on-disk secrets: `auth.json` written atomically with `0o600`
  inside a `0o700` config directory; refuses to use a config directory
  owned by a different uid or group/world writable.
- Token redaction in all user-facing error paths, including post-login
  verification failures.
- Documented exit codes (`0` success, `1` unexpected, `2` auth, `3` API,
  `4` no Copilot quota).
- Mermaid flowchart in the README covering the full login, logout, and
  bare-invocation flows.

[Unreleased]: https://github.com/nkootstra/copilot-spend/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/nkootstra/copilot-spend/releases/tag/v0.2.0
[0.1.0]: https://github.com/nkootstra/copilot-spend/releases/tag/v0.1.0
