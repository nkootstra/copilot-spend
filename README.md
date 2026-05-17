# copilot-spend

Find out what your Copilot habit actually costs.

A small Python CLI that reads your GitHub Copilot quota and prints
your current-period spend in dollars and PRUs, plus when the period resets.
Works against both `github.com` and GitHub Enterprise hosts.

## How it works

1. Resolves a GitHub Copilot token from the first source that exists, in
   this order:
   1. Native: `~/.config/copilot-spend/auth.json`, created by running
      `copilot-spend login`.
   2. Opencode fallback: `~/.local/share/opencode/auth.json` (keys
      `github-copilot.access` and `github-copilot.enterpriseUrl`), if
      opencode is installed.
2. Exchanges the OAuth token for a short-lived Copilot session token via
   `/copilot_internal/v2/token`, caching it in
   `~/.config/copilot-spend/session.json` until it expires.
3. Calls `GET /api/v3/copilot_internal/user` on your GHE host, or
   `GET https://api.github.com/copilot_internal/user` if no enterprise
   host is configured, using the session token as `Bearer`.
4. Computes the billable overage:
   `billable_PRUs = max(0, consumed - entitlement)`, then
   `dollars_owed = billable_PRUs × $0.04`.
   The first `entitlement` PRUs each period are included with your plan
   and cost nothing.
5. Prints a plain-text summary on stdout.

No background daemon. No history. Two small JSON files under
`~/.config/copilot-spend/` and one HTTP request per run (plus a session
exchange roughly every 30 minutes).

## Requirements

- Python 3.10 or newer
- macOS or Linux
- A GitHub Copilot token, obtained by either:
  - running `copilot-spend login`, or
  - having opencode installed and authenticated already

## Install

PyPI publication is pending. Until then, install from a local clone:

```sh
git clone https://github.com/<you>/copilot-spend.git
cd copilot-spend

# Option A: pipx
pipx install .

# Option B: uv (persistent install)
uv tool install --from . copilot-spend

# Option C: uv (one-off run, no install)
uvx --from . copilot-spend
```

## Usage

```sh
copilot-spend          # print current-period quota
copilot-spend login    # authenticate via GitHub OAuth device flow
copilot-spend logout   # remove copilot-spend's stored credentials
```

`copilot-spend login` prompts for github.com or a GHE host, shows a
device code with a URL to visit, then polls until you complete the
flow in your browser. Credentials land in
`~/.config/copilot-spend/auth.json` (mode `0o600`). If you already have
opencode authenticated, the bare `copilot-spend` command continues to
work without login.

Example output (under your allowance):

```
GitHub Copilot - your-login (business)
  Used:      221 PRUs
  Allowance: $12.00  (300 PRUs included)
  Remaining: $3.16  (79 PRUs of free allowance left)
  Resets:    May 31, 2026 (in 15 days)
```

Example output (over your allowance — billable overage):

```
GitHub Copilot - your-login (business)
  Used:      4073 PRUs
  Allowance: $12.00  (300 PRUs included)
  Billable:  $150.92  (3773 PRUs over allowance at $0.04/PRU)
  Resets:    Jun 01, 2026 (in 16 days)
```

Flags: `--help`, `--version`. Subcommands: `login`, `logout`.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Unexpected error |
| 2 | Auth error (missing/invalid `auth.json` or token) |
| 3 | API error (network, timeout, 4xx/5xx) |
| 4 | No Copilot quota on the account |

## Switch to your own GitHub App

`copilot-spend login` runs the GitHub OAuth device flow against
Microsoft's well-known VS Code Copilot GitHub App
(`Iv1.b507a08c87ecfe98`). This is the same client ID used by every
working third-party Copilot tool — copilot.vim, avante.nvim, LiteLLM,
and others — because GitHub's session-token exchange endpoint
(`/copilot_internal/v2/token`) only accepts tokens issued by a GitHub
App, not by an OAuth App.

The trade-off: the GitHub consent screen during login says "GitHub for
VS Code" rather than "copilot-spend", and you depend on Microsoft not
rotating that app. To remove both, register your own GitHub App and
swap the constant:

1. Visit https://github.com/settings/apps and click **New GitHub App**.
   This must be a *GitHub App*, not an *OAuth App* — OAuth Apps issue
   `gho_…` tokens that the Copilot exchange endpoint rejects with 404.
2. Set Homepage URL and Callback URL to anything (the device flow does
   not use them).
3. Enable **Device flow** under "Identifying and authorizing users".
4. Account permissions: none required beyond user identification.
   The `read:user` OAuth scope is enough.
5. Note the resulting **Client ID** (starts with `Iv23` or `Iv1.`).
6. Replace the `CLIENT_ID` constant in
   `src/copilot_spend/login.py` with your new client ID.
7. Rebuild/reinstall (`pipx install --force .` or
   `uv tool install --force --from . copilot-spend`).

After the swap, the consent screen shows your app's name and your
copilot-spend install no longer breaks if Microsoft rotates
`Iv1.b507a08c87ecfe98`.

## Caveats

- The PRU price is hardcoded at $0.04 (correct as of 2026-05). Update the
  constant in `src/copilot_spend/quota.py` if GitHub changes it.
- v1 ships with VS Code's GitHub App ID `Iv1.b507a08c87ecfe98` for the
  device flow. See "Switch to your own GitHub App" above to remove the
  dependency.
- The billing model assumed: the first `entitlement` PRUs each period are
  included with your plan, and anything beyond that is billable at $0.04
  per PRU. This matches observed behavior on a business plan. Org-level
  caps or contracts may change what you actually pay — treat the
  `Billable` figure as a personal estimate, not an invoice.
- The reset-date field name in the Copilot API response is best-effort:
  `copilot-spend` tries the field names observed on a real response, plus
  a few defensive fallbacks, and prints `next reset: unknown` if none
  match. Adjust `RESET_FIELD_CANDIDATES` in `quota.py` if your response
  uses a different name.
- The `/copilot_internal/user` endpoint is not a public, documented API.
  GitHub may change its shape at any time.

## Development

```sh
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```
