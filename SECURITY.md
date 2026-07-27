# Security Policy

This is a personal, local-only tool (binds to `localhost` by default, no
multi-tenant deployment). Still, if you find a security issue, please report
it responsibly rather than opening a public issue.

## Reporting a Vulnerability

Please use [GitHub's private vulnerability reporting](https://github.com/gab-es21/book-listing-automation/security/advisories/new)
for this repository, rather than a public issue or pull request.

You should expect an initial response within a few days. There's no bug
bounty - this is an unpaid personal project - but reports are genuinely
appreciated and will be credited unless you'd prefer otherwise.

## Scope

Since the app is meant to run on `localhost` for a single user, the realistic
threat model is narrow (e.g. a malicious site attempting a cross-origin
request while the app happens to be running - already mitigated by an
Origin/Referer check on all state-changing routes). Reports about that class
of issue, dependency vulnerabilities, or anything that would matter if
someone ran this on a shared/exposed host are all welcome.
