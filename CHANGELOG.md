# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/nkootstra/copilot-spend/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/nkootstra/copilot-spend/releases/tag/v0.1.0
