# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This is the TypeScript/npm build of copilot-spend. Its version tracks the
Python package's feature set; the first published version is `0.3.0` to
signal parity with Python `0.3.0`. npm release tags are prefixed `npm-v`
(e.g. `npm-v0.3.0`) to distinguish them from the Python package's bare
version tags within this monorepo.

## [Unreleased]

## [0.4.0] - 2026-09-23

Version bump to keep parity with Python `0.4.0`. No functional changes to
the CLI; the published bundle is unchanged in behavior.

### Changed

- Type-checked with TypeScript 7 (native compiler) and linted with Biome 2.

## [0.3.0] - 2026-06-01

Initial npm release: a faithful TypeScript port of the Python package at
full feature parity. Built with Bun; the published artifact is a single
bundled file that runs on Node 22+ with zero runtime dependencies.

### Added

- `copilot-spend` bare command: reads the current-period Copilot quota and
  prints used PRUs, included allowance, billable overage (at $0.04/PRU),
  and the period reset date.
- Token-based Copilot billing detection from `/copilot_internal/user`. Text
  output labels token-based accounts and reports the premium-interactions
  bucket as AI credits at $0.01 per credit, including legacy unlimited and
  overage-enabled snapshots.
- `copilot-spend login` subcommand: GitHub OAuth device flow against the
  well-known VS Code Copilot GitHub App client ID, with re-auth detection,
  `slow_down` handling, defensive timeout, SSRF host validation, Ctrl-C
  cancellation, and post-login verification against `/copilot_internal/user`
  before any token is persisted.
- `copilot-spend logout` subcommand: removes stored credentials
  idempotently and cleans up any legacy `session.json`.
- `copilot-spend whoami` subcommand: prints the active login, host,
  credential source (native vs opencode), Copilot plan, and billing mode.
  Falls back gracefully when the account has no Copilot quota.
- `copilot-spend --json` flag: renders the current spend as a stable,
  sort-keyed JSON object, schema-identical to the Python build.
- Multi-source auth resolution: prefers the native
  `~/.config/copilot-spend/auth.json`, falls back to an existing
  `~/.local/share/opencode/auth.json`.
- GitHub Enterprise host support for both the device flow and the quota
  fetch.
- Single-hop bearer path: the `ghu_`/`gho_` user token is sent directly as
  `Bearer` to `/copilot_internal/user`.
- Hardened on-disk secrets: `auth.json` written atomically with `0600`
  inside a `0700` config directory; refuses a config directory owned by a
  different uid or group/world writable.
- Token redaction in all user-facing error paths.
- One transparent retry on transient 5xx in the quota fetch, with backoff;
  401/403/404 fail fast.
- Honors `COPILOT_SPEND_QUIET`, `COPILOT_SPEND_DEBUG`,
  `COPILOT_SPEND_CONFIG_DIR`, and `XDG_CONFIG_HOME` identically to the
  Python build.
- Documented exit codes (`0` success, `1` unexpected, `2` auth, `3` API,
  `4` no Copilot quota) — identical to the Python build.

[Unreleased]: https://github.com/nkootstra/copilot-spend/compare/npm-v0.4.0...HEAD
[0.4.0]: https://github.com/nkootstra/copilot-spend/releases/tag/npm-v0.4.0
[0.3.0]: https://github.com/nkootstra/copilot-spend/releases/tag/npm-v0.3.0
