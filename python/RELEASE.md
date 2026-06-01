# Release process

This document describes how to publish `copilot-spend` to PyPI. Releases run
through GitHub Actions using PyPI Trusted Publishers (OIDC) — there are no
long-lived API tokens stored in this repository.

## 1. One-time setup

You only need to do this once per project, the very first time you publish.

### 1a. Configure Trusted Publisher on PyPI (required)

1. Go to <https://pypi.org/manage/account/publishing/>.
2. Under **Add a new pending publisher**, fill in:
   - **PyPI project name**: `copilot-spend`
   - **Owner**: `nkootstra`
   - **Repository name**: `copilot-spend`
   - **Workflow name**: `release.yml`
   - **Environment name**: `pypi`
3. Click **Add**. The publisher is now pending — the first successful
   workflow run will register and own the project name.

> **Name-hijack note.** A pending publisher reserves the name only after the
> first publish succeeds. If someone else publishes a project with the same
> name before your first release lands, your pending publisher silently
> stops matching. If you are concerned about that, publish an empty `0.0.0`
> placeholder to PyPI manually first using `twine upload`, then switch to
> the Trusted Publisher flow for `0.1.0` onward.

### 1b. Create the `pypi` GitHub Environment (required)

1. In the repo, go to **Settings → Environments → New environment**.
2. Create an environment called `pypi`. Recommended: add yourself as a
   required reviewer so production uploads need an explicit click.

The `release.yml` workflow references this environment name exactly.

### 1c. (Optional) Add TestPyPI staging

TestPyPI is gated behind the repo variable `PUBLISH_TO_TESTPYPI`. The
staging job is **skipped** by default; production releases work without
it. Enable staging when you want a dry-run target before each PyPI
upload:

1. Register the publisher on <https://test.pypi.org/manage/account/publishing/>
   using the same fields as 1a, except **Environment name** = `testpypi`.
2. Create a `testpypi` GitHub Environment (no protection rules needed).
3. In the repo, go to **Settings → Secrets and variables → Actions →
   Variables** and add a repository variable:
   - **Name**: `PUBLISH_TO_TESTPYPI`
   - **Value**: `true`
4. The next release run will fan out: `build` → TestPyPI (in parallel)
   and `build` → PyPI (gated on your `pypi` approval).

To disable staging later without removing the workflow, either delete
the variable or set it to anything other than `true`.

## 2. Per-release checklist

1. **Update `CHANGELOG.md`.** Move the relevant items from `[Unreleased]`
   into a new `## [X.Y.Z] - YYYY-MM-DD` section. Add a fresh empty
   `[Unreleased]` section above it. Update the version-link footer at the
   bottom of the file.
2. **Bump the version.** Edit `version` in `pyproject.toml` to `X.Y.Z`.
3. **Commit.** `git commit -am "release: vX.Y.Z"`.
4. **Tag.** `git tag vX.Y.Z`.
5. **Push.** `git push origin main vX.Y.Z`.
6. **Wait for `test` workflow.** Confirm the full matrix (Python 3.10–3.13
   × ubuntu + macOS) passes on the tag commit before drafting the release.
7. **Draft the GitHub release.** Use the `vX.Y.Z` tag. Paste the relevant
   CHANGELOG entry as the release body. Click **Publish release**.
8. **Watch the workflow.** The `release` workflow builds, then waits on
   the `pypi` environment for your approval before uploading. If TestPyPI
   staging is enabled (see 1c), that job runs in parallel with the PyPI
   approval gate.
9. **Verify.**
   - If TestPyPI staging is enabled:
     `pip install --index-url https://test.pypi.org/simple/ copilot-spend==X.Y.Z`
     in a throwaway venv, then `copilot-spend --version`.
   - After approving the production upload:
     `pipx run copilot-spend==X.Y.Z --version`.
   - Sanity-check the PyPI page lists the new version and Project URLs are
     intact.

## 3. Troubleshooting

**`invalid-publisher` from `pypa/gh-action-pypi-publish`.** The trusted
publisher config does not match the workflow run. Compare the workflow
file name, environment name, repo owner, and repo name against the entry
on pypi.org or test.pypi.org. All four must match exactly.

**Workflow stuck waiting on `pypi` environment.** The `pypi` environment
has a required reviewer set (recommended). Open the workflow run, click
**Review deployments**, approve.

**TestPyPI upload succeeds but PyPI step fails on `File already exists`.**
A version with that filename was already uploaded — PyPI does not allow
re-uploads even after a delete. Bump to the next patch version and re-tag.

**`twine check` fails in CI.** Usually a README rendering problem. Run
`python -m build && twine check --strict dist/*` locally to reproduce.

**Need to retract a bad release.** PyPI cannot truly delete a file, but
you can **yank** the release via the PyPI web UI. Yanked versions stay
installable by explicit pin but are hidden from solvers picking the
latest. Follow the yank with a fixed `X.Y.Z+1`.
