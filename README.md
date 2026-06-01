# copilot-spend

Find out what your Copilot habit actually costs.

A small, zero-dependency CLI that reads your GitHub Copilot quota and
prints your current-period billing mode, quota bucket, and reset date.
Works against both `github.com` and GitHub Enterprise hosts.

This repository is a monorepo holding two implementations that behave
identically — same auth sources, same prompts, same output, same exit
codes, same stable JSON schema. Pick whichever fits your toolchain:

| Package | Language | Registry | Install | Docs |
|---------|----------|----------|---------|------|
| [`python/`](python/) | Python 3.10+ | [PyPI](https://pypi.org/project/copilot-spend/) | `pipx install copilot-spend` | [python/README.md](python/README.md) |
| [`typescript/`](typescript/) | TypeScript (Bun build, runs on Node 18+) | [npm](https://www.npmjs.com/package/copilot-spend) | `npm install -g copilot-spend` | [typescript/README.md](typescript/README.md) |

Both publish the same `copilot-spend` command name, so:

```sh
copilot-spend          # print current-period quota
copilot-spend --json   # same data as JSON (stable schema, jq-friendly)
copilot-spend whoami   # print active login, host, source, plan, and billing mode
copilot-spend login    # authenticate via GitHub OAuth device flow
copilot-spend logout   # remove copilot-spend's stored credentials
```

Example output:

```
GitHub Copilot - your-login (business)
  Used:      221 PRUs
  Allowance: $12.00  (300 PRUs included)
  Remaining: $3.16  (79 PRUs of free allowance left)
  Resets:    May 31, 2026 (in 15 days)
```

See each package's README for the full feature description, the
auth-resolution flowchart, the JSON schema, environment variables,
exit codes, and instructions for swapping in your own GitHub App.

## Repository layout

```
.
├── python/        # PyPI package (hatchling, pytest, ruff, mypy)
├── typescript/    # npm package (Bun build, bun:test, biome, tsc)
├── docs/          # design notes and plans
└── .github/
    └── workflows/
        ├── test.yml            # Python: runs only when python/** changes
        ├── release.yml         # Python: PyPI publish on a `v*` release tag
        ├── npm-test.yml        # runs only when typescript/** changes
        └── npm-release.yml     # npm publish on an `npm-v*` release tag
```

CI is path-filtered: changes under `python/**` never trigger the npm
workflows and vice versa.

## Releasing

The two packages version and ship independently, distinguished by the
release tag:

- **Python → PyPI:** publish a GitHub Release with a bare version tag
  (e.g. `v0.3.0`). `release.yml` builds the sdist/wheel from
  `python/` and publishes via PyPI Trusted Publishing (OIDC).
- **npm → npm:** publish a GitHub Release with an `npm-v`-prefixed tag
  (e.g. `npm-v0.3.0`). `npm-release.yml` builds the bundle from
  `typescript/` and publishes via npm Trusted Publishing (OIDC). The
  workflow verifies the tag matches `typescript/package.json` before
  publishing.

Neither release workflow needs a long-lived API token.

## License

[MIT](LICENSE)
