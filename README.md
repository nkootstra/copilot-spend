# copilot-spend

Find out what your Copilot habit actually costs.

A small Python CLI that reads your GitHub Copilot quota and prints
your current-period spend in dollars and PRUs, plus when the period resets.
Works against both `github.com` and GitHub Enterprise hosts.

## How it works

1. Reads your opencode-managed Copilot token from
   `~/.local/share/opencode/auth.json` (keys: `github-copilot.access` and
   `github-copilot.enterpriseUrl`).
2. Calls `GET /api/v3/copilot_internal/user` on your GHE host, or
   `GET https://api.github.com/copilot_internal/user` if no enterprise URL
   is configured.
3. Computes the billable overage:
   `billable_PRUs = max(0, consumed - entitlement)`, then
   `dollars_owed = billable_PRUs × $0.04`.
   The first `entitlement` PRUs each period are included with your plan
   and cost nothing.
4. Prints a plain-text summary on stdout.

No background daemon. No config files. No history. Just one HTTP request
and a few lines of output.

## Requirements

- Python 3.10 or newer
- macOS or Linux
- An opencode-authenticated GitHub Copilot token already on disk

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
copilot-spend
```

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

Flags: `--help`, `--version`. No other arguments.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Unexpected error |
| 2 | Auth error (missing/invalid `auth.json` or token) |
| 3 | API error (network, timeout, 4xx/5xx) |
| 4 | No Copilot quota on the account |

## Caveats

- The PRU price is hardcoded at $0.04 (correct as of 2026-05). Update the
  constant in `src/copilot_spend/quota.py` if GitHub changes it.
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
