# Security Policy

## Supported versions

Only the latest released version of `copilot-spend` is supported. Security
fixes are released as a patch version against the most recent `0.x` line.

## Reporting a vulnerability

Please report security issues privately to **niels.kootstra@gmail.com**, or
open a GitHub security advisory at
https://github.com/nkootstra/copilot-spend/security/advisories/new.

Include enough detail to reproduce: affected version, command run,
environment (Python version, OS, install method), and the actual vs.
expected behavior. If the issue involves a credential disclosure, do not
include the credential itself — describe its source (`auth.json`,
opencode auth file, env var, etc.) and the disclosure path.

You can expect:

- Acknowledgement within a few business days.
- A coordinated disclosure timeline if a fix is needed before publication.
- Credit in the release notes for the patched version, unless you ask
  otherwise.

## Out of scope

- Vulnerabilities in GitHub's Copilot API itself (report those to GitHub).
- Issues that require an attacker to already have read access to your
  `~/.config/copilot-spend/` directory or your opencode auth file —
  protecting those files is your operating system's job.
- Token expiration, rate limiting, or upstream availability problems.
